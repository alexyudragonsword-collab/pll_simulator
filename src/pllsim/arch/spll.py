"""(Reference-)Sampling PLL — the dual of the SSPLL.

Here a divided VCO edge samples the *reference* sine, so the PD gain is
referred to REFERENCE phase (A volts per rad at fref).  Consequently sampler
and gm noise ARE multiplied by N to the output — the honest comparison with
the SSPLL (see ex04): same sampler front-end, ~20logN worse in-band PD noise,
but a full +/-pi capture range at the reference carrier and a conventional
divider for frequency acquisition.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np

from ..blocks.dtc import dtc_code, dtc_inl_s, dtc_time
from ..blocks.loopfilter import FilterDesign, LoopFilter, lf_drive_fine, lf_pulse
from ..blocks.oscillator import OscConfig, Oscillator, osc_freq
from ..blocks.sampler import (
    SamplerConfig,
    SamplingPD,
    pd_charge_det,
    pd_sample_det,
    pd_segments,
)
from ..calibration.ftl import FLL_ACQ, FLL_STATE, FLLStateMachine, fll_step
from ..calibration.lms import CAL_VALUE, lms_step
from ..core.colored import synth_from_psd
from ..core.deltasigma import mash_residual, mash_step
from ..core.engine import detect_lock, postprocess
from ..core.freqresp import FreqResponse, default_grid, loop_metrics
from ..core.jit import kernel
from ..core.jitter import ipn_dbc, rms_jitter_fs
from ..core.noise import (
    FlickerFloorPhase,
    NoisePath,
    ResistorNoise,
    SampledChargeNoise,
    SampledKTC,
    output_psd,
)
from ..core.results import AnalysisResult, SimResult
from .base import (
    PLLBase,
    add_pull_offset,
    attach_fine,
    cal_kernel_args,
    dtc_kernel_args,
    dtc_t_target_of,
    flicker_corner_hz,
    fll_kernel_args,
    mash_kernel_args,
    no_fine_note,
    osc_law_args,
    pull_hz,
    pull_notes,
    pull_spur,
    run_band_select,
    supply_ripple_v,
    tuning_notes,
    tuning_sim_notes,
)
from .cppll import FracConfig

TWOPI = 2.0 * np.pi


@dataclass
class SPLLConfig:
    fref: float
    fout: float
    osc: OscConfig
    sampler: SamplerConfig
    filt: FilterDesign
    ref_pn_dbchz: float = -160.0
    ref_pn_fc: float = 20e3
    div_pn_dbchz: float = -160.0
    div_pn_fc: float = 100e3
    fll_i: float = 1e-6
    fll_window: int = 64
    fll_engage: float = 3e6
    fll_release: float = 500e3
    frac: FracConfig | None = None  # EFM1 + DTC on the divided edge
    int_band: tuple[float, float] = (1e3, 100e6)

    @property
    def n_div(self) -> float:
        n = self.fout / self.fref
        if self.frac is None:
            if abs(n - round(n)) > 1e-9:
                raise ValueError("integer-N SPLL requires integer fout/fref; "
                                 "provide FracConfig for fractional operation")
            return int(round(n))
        return n

    def __post_init__(self):
        if self.frac is not None:
            if abs((self.fout / self.fref) % 1.0 - self.frac.frac) > 1e-6:
                raise ValueError(
                    f"fout/fref fractional part {(self.fout / self.fref) % 1.0:.6f} "
                    f"does not match FracConfig.frac {self.frac.frac}: the divider "
                    f"locks at (n_int + frac)*fref, not at fout -- change fout or "
                    f"frac together with fref")
            if self.frac.dtc is None:
                raise ValueError("fractional SPLL requires a DTC in FracConfig")
            if self.frac.dtc_lut_cal is not None:
                raise ValueError(
                    "dtc_lut_cal is wired for the CPPLL only. Its update"
                    " regresses the PD's TIMING error against the MASH"
                    " residue; this architecture's detector exposes a"
                    " different quantity, and wiring it naively measurably"
                    " made the INL spur WORSE with either update sign, so it"
                    " is refused rather than silently ignored.")
            if self.frac.mash_order != 1:
                raise ValueError(
                    "fractional SPLL uses a 1st-order EFM: its residue spans "
                    "exactly 1 UI, matching a practical DTC range (measured "
                    "2026-09: a MASH-2 residue spans 2 UI and MASH-3 4 UI, "
                    "while the shipped DTCs cover 1.0-1.6 UI -- a higher order "
                    "needs a DTC of >= 2 UI plus a bipolar target mapping)")


@kernel
def spll_kernel(n_cycles: int, tref: float, fref: float, fout: float, f_floor: float,
                n_nom: float, n_int: int,
                band: int, f0: float, gain: float, nl1: float, nl2: float,
                band_step: float, n_bands: int, v_lo: float, v_hi: float,
                pushing: float, v_sup: np.ndarray, f_pull: np.ndarray,
                osc_noise: np.ndarray, jit_ref: np.ndarray, jit_div: np.ndarray,
                noise_on: bool, zn: np.ndarray,
                has_mash: bool, mash_order: int, mash_bits: int, mash_st: np.ndarray,
                frac_word: int, dtc_range_s: float, dtc_t_res: float, dtc_code_max: int,
                dtc_inl_poly: np.ndarray, dtc_has_sin: bool, dtc_sin_amp: float,
                dtc_sin_cyc: float, dtc_sin_ph: float, dtc_jitter: float,
                dtc_gain_error: float, has_drift: bool, dtc_gain_drift: np.ndarray,
                has_cal: bool, cal_kind: int, cal_st: np.ndarray, cal_mu: float,
                cal_mu_final: float, cal_gear: float, cal_ema: float, cal_center: bool,
                cal_trace: np.ndarray,
                has_fll: bool, fll_st: np.ndarray, fll_n_target: float, fll_fref: float,
                fll_window: int, fll_engage: float, fll_release: float, fll_i: float,
                fll_hyst: int,
                pd_amp: float, pd_pedestal: float, pd_ktc_sigma: float, pd_gm: float,
                pd_pw: float, pd_sig_q: float, pd_kick_q: float, pd_kick_delay: float,
                lf_x: np.ndarray, lf_ad: np.ndarray, lf_b: np.ndarray, lf_w: np.ndarray,
                lf_v: np.ndarray, lf_vinv: np.ndarray, lf_vinv_b: np.ndarray,
                lf_tmp: np.ndarray, lf_xe: np.ndarray, lf_xe0: np.ndarray,
                m_os: int, fine: np.ndarray, f_sub: np.ndarray, seg_amp: np.ndarray,
                seg_dur: np.ndarray, vs_sub: np.ndarray,
                phase_err: np.ndarray, freq_out: np.ndarray, vctrl_rec: np.ndarray,
                fll_state: np.ndarray) -> int:
    """The reference-sampling loop, one reference cycle per iteration: the
    (DTC-delayed) divided edge samples the reference sine, FLL or sampler
    charge into the filter, VCO, divider edge.  Returns the normal draws
    consumed."""
    nlf = lf_x.shape[0]
    sub = tref / m_os
    prev_on = 0.0
    t_div = 0.0
    phi_out = 0.0
    gain_corr = 1.0
    gain_err = dtc_gain_error
    zi = 0
    fv = osc_freq(lf_x[nlf - 1], band, v_sup[0], f_pull[0], pushing, f0, gain, nl1, nl2,
                  band_step, n_bands, v_lo, v_hi)

    for nn in range(n_cycles):
        d_osc = osc_noise[nn] - prev_on
        prev_on = osc_noise[nn]

        dq = 0.0
        engaged = False
        if has_fll:
            dq += fll_step(fll_st, fv / fref, fll_n_target, fll_fref, fll_window,
                           fll_engage, fll_release, fll_i, fll_hyst)
            engaged = fll_st[FLL_STATE] == FLL_ACQ
        residual_ui = 0.0
        d_dtc = 0.0
        if has_mash:
            if has_drift:
                gain_err = dtc_gain_drift[nn]
            # EFM1 residue in (-1, 0]: the divided edge is EARLY by
            # |residual|·Tvco -> delay it by -residual·Tvco in (0, Tvco],
            # cancelling the DTC's bipolar mid-range offset
            residual_ui = mash_residual(mash_bits, mash_st)
            t_target = -residual_ui / fout - dtc_range_s / 2.0
            code = dtc_code(t_target, dtc_range_s, gain_corr, dtc_t_res, dtc_code_max)
            inl = dtc_inl_s(code, dtc_code_max, dtc_inl_poly, dtc_has_sin, dtc_sin_amp,
                            dtc_sin_cyc, dtc_sin_ph)
            d_dtc = dtc_time(code, dtc_t_res, gain_err, inl)
            if noise_on and dtc_jitter > 0:
                d_dtc += dtc_jitter * zn[zi]
                zi += 1
        if not engaged:
            # (DTC-delayed) divided VCO edge samples the reference sine
            perr_ref = TWOPI * fref * (t_div + d_dtc + jit_div[nn]
                                       - nn * tref - jit_ref[nn])
            perr_ref = ((perr_ref + math.pi) % TWOPI) - math.pi
            vs = pd_sample_det(perr_ref, pd_amp, pd_pedestal)
            if noise_on:
                vs += pd_ktc_sigma * zn[zi]
                zi += 1
            q = pd_charge_det(vs, pd_gm, pd_pw)
            if noise_on:
                q += pd_sig_q * zn[zi]
                zi += 1
            dq += q     # divider late -> vs>0 -> speed up VCO
            if has_cal and has_mash:
                # target delay ∝ -residual: under-delay correlates vs
                # POSITIVELY with residual -> err = +vs
                gain_corr = lms_step(cal_kind, cal_st, vs, residual_ui, cal_mu,
                                     cal_mu_final, cal_gear, cal_ema, cal_center)
        if has_cal:
            cal_trace[nn] = cal_st[CAL_VALUE]
        if m_os == 1:
            lf_pulse(lf_x, lf_ad, lf_b, lf_w, lf_v, lf_vinv, lf_vinv_b,
                     dq / max(pd_pw, 1e-12), pd_pw, tref, lf_tmp, lf_xe)
            fv = max(osc_freq(lf_x[nlf - 1], band, v_sup[nn], f_pull[nn], pushing, f0,
                              gain, nl1, nl2, band_step, n_bands, v_lo, v_hi), f_floor)
        else:
            # kickback and gm pulse land at different instants; that
            # separation is the reference-spur mechanism here
            nseg = pd_segments(dq, pd_kick_q, pd_kick_delay, pd_pw, seg_amp, seg_dur)
            lf_drive_fine(lf_x, lf_w, lf_v, lf_vinv, lf_vinv_b, tref, seg_amp, seg_dur,
                          nseg, m_os, 0.0, 0.0, vs_sub, lf_xe0, lf_xe)
            for k in range(m_os):
                f_sub[k] = max(osc_freq(vs_sub[k], band, v_sup[nn], f_pull[nn], pushing,
                                        f0, gain, nl1, nl2, band_step, n_bands, v_lo,
                                        v_hi), f_floor)
            fv = f_sub[m_os - 1]

        n_next = n_nom
        if has_mash:
            n_next = float(n_int + mash_step(mash_order, mash_bits, mash_st, frac_word))
        t_div += n_next / fv - d_osc / (TWOPI * fv)
        if m_os == 1:
            phi_out += TWOPI * (fv - fout) * tref + d_osc
        else:
            cs = 0.0
            for k in range(m_os):
                cs += TWOPI * (f_sub[k] - fout) * sub + d_osc / m_os
                fine[nn * m_os + k] = phi_out + cs
            phi_out = fine[(nn + 1) * m_os - 1]
        phase_err[nn] = phi_out
        freq_out[nn] = fv
        vctrl_rec[nn] = lf_x[nlf - 1]
        fll_state[nn] = 1.0 if engaged else 0.0
    return zi


class SPLL(PLLBase):
    def __init__(self, cfg: SPLLConfig):
        self.cfg = cfg

    def analyze(self, f: np.ndarray | None = None) -> AnalysisResult:
        c = self.cfg
        if f is None:
            f = default_grid(1e2, 1e9)
        n = c.n_div
        s = c.sampler
        duty = s.pulse_width * c.fref
        lf = LoopFilter(c.filt, 1.0 / c.fref)
        z = FreqResponse(f, lf.transimpedance(f))
        vco_int = FreqResponse.integrator(f, TWOPI * c.osc.gain)
        # K_pd referred to REFERENCE phase: A [V/rad@fref]; divider closes /N
        k_cp = s.amp_v * s.gm * duty
        gol = z * vco_int * k_cp * (1.0 / n)
        h = gol.feedback()
        err = 1.0 / (1.0 + gol)

        paths = [
            NoisePath(FlickerFloorPhase.from_spot("ref", c.ref_pn_dbchz, c.ref_pn_fc),
                      h * n),
            NoisePath(FlickerFloorPhase.from_spot("divider", c.div_pn_dbchz,
                                                  c.div_pn_fc), h * n),
            # sampler/gm noise referred to ref phase -> x N to the output
            NoisePath(SampledKTC(name="sampler_ktc", unit="V^2/Hz",
                                 c_farad=s.c_samp, fs=c.fref),
                      h * (n / s.amp_v)),
            # one charge packet per reference cycle: sampled, not duty-cycled
            NoisePath(SampledChargeNoise(name="gm", unit="C^2/Hz",
                                         i2=s.gm_i2(), tau=s.pulse_width,
                                         fs=c.fref),
                      h * (n / (s.amp_v * s.gm * s.pulse_width))),
            NoisePath(ResistorNoise(name="lf_r2", unit="V^2/Hz", r_ohm=c.filt.r2),
                      FreqResponse(f, self._r2_tf(f)) * vco_int * err),
            NoisePath(c.osc.leeson("vco"), err),
        ]
        if c.frac is not None:
            # DTC timing error at the sampling instant is a REFERENCE phase
            # error 2π·fref·δt -> xN to output: equivalently q = 2π·fout·δt
            # through H — the same output-referred form as the SSPLL
            from ..core.noise import NoiseSource, ShapedQuantization
            d = c.frac.dtc
            paths.append(NoisePath(
                ShapedQuantization(name="dtc_quant", unit="rad^2/Hz",
                                   q=TWOPI * d.t_res * c.fout, fs=c.fref,
                                   order=0), h))
            if d.jitter_rms_s > 0:
                paths.append(NoisePath(
                    NoiseSource(name="dtc_jitter", unit="rad^2/Hz",
                                level=2.0 * (TWOPI * c.fout * d.jitter_rms_s) ** 2
                                / c.fref), h))
            eps = getattr(d, "gain_error_residual", 0.01)
            paths.append(NoisePath(
                ShapedQuantization(name="dsm_residual", unit="rad^2/Hz",
                                   q=TWOPI * eps, fs=c.fref, order=0), h))
        m = loop_metrics(gol, f_limit=c.fref / 2)
        bd = output_psd(paths, f)
        # Same accounting as the SSPLL: the pedestal shifts the held voltage
        # and the gm converts that same held voltage over the same window, so
        # the loop parks where the gm delivers zero charge and there is no
        # ripple to make a spur from.  The kickback is the mechanism that
        # survives, because it lands at a different instant.
        pd_a = SamplingPD(s, 1.0 / c.fref, np.random.default_rng(0), noise=False)
        zf = np.interp(np.log10(c.fref), np.log10(f), np.abs(z.h))
        i1 = pd_a.ripple_fundamental_a(1.0 / c.fref)
        spurs = {}
        if i1 > 0:
            beta = c.osc.gain * (i1 * zf) / c.fref
            spurs["ref_spur"] = float(20 * np.log10(beta / 2))
        if c.frac is not None:
            from ..core.dtcspurs import dtc_spur_table
            d = c.frac.dtc
            eps_g = getattr(d, "gain_error_residual", 0.01)
            for off, dbc in dtc_spur_table(
                    c.frac,
                    dtc_t_target_of(self),
                    c.fref, c.fout, ntf=h, gain_eps=eps_g).items():
                spurs[f"frac_spur@{off:.0f}Hz"] = dbc
        spurs.update(pull_spur(c.osc, err))
        notes = [f"PD gain referred to reference phase: sampler/gm noise "
                 f"multiplied by N={n} at the output (contrast with SSPLL)"]
        # the same continuous-time approximation as the CPPLL, and until now
        # the only CT architecture without this warning -- README claimed it
        from ..core.boundaries import CT_UGB_RATIO, ct_approx_exceeded
        if ct_approx_exceeded(m.f_ugb, c.fref):
            notes.append(f"UGB {m.f_ugb / 1e6:.1f} MHz > fref/"
                         f"{CT_UGB_RATIO:.0f}: continuous-time "
                         "approximation degrading")
        from ..core.boundaries import conditionally_stable
        if conditionally_stable(m.n_crossings):
            notes.append(
                f"open loop crosses unity gain {m.n_crossings}x below "
                "fref/2: conditionally stable — phase margin at the first "
                "crossing does not describe the loop")
        notes.extend(pull_notes(c.osc))
        if i1 == 0.0:
            notes.append(
                "no reference spur reported: the sampling pedestal produces a "
                "static phase offset, not ripple — set SamplerConfig.kick_q_c "
                "and kick_delay_s for the sampling clock's kickback, which is "
                "what actually makes this architecture's ref spur")
        return AnalysisResult(f=f, f0=c.fout, pn_breakdown=bd, loop=m,
                              jitter_fs=rms_jitter_fs(f, bd["total"], c.fout,
                                                      *c.int_band),
                              ipn_dbc=ipn_dbc(f, bd["total"], *c.int_band),
                              int_band=c.int_band, spurs_analytic=spurs,
                              ntfs={"gol": gol, "h": h, "err": err},
                              notes=notes + tuning_notes(c.osc, c.osc.v_for(c.fout)))

    def _r2_tf(self, f):
        d = self.cfg.filt
        sc = 2j * np.pi * f
        zc1 = 1.0 / (sc * d.c1)
        zc2 = 1.0 / (sc * d.c2)
        return zc2 / (d.r2 + zc1 + zc2)

    def simulate(self, n_cycles: int, *, noise: bool = True, calibration: bool = True,
                 seed: int = 0, f_start_offset: float = 0.0,
                 fll_enable: bool = True,
                 supply_ripple: tuple[float, float] | None = None,
                 band_select: bool = True,
                 dtc_gain_init_error: float = 0.0,
                 fine_oversample: int = 1,
                 dtc_gain_drift: np.ndarray | None = None) -> SimResult:
        """dtc_gain_drift: per-cycle TRUE DTC gain-error trajectory (e.g. a
        temperature ramp); overrides dtc_gain_init_error when given.
        fine_oversample: record M control-voltage samples per reference period
        so the intra-period ripple carrying the reference spur is observable
        (at M=1 it aliases to DC)."""
        c = self.cfg
        rng = np.random.default_rng(seed)
        tref = 1.0 / c.fref
        n = c.n_div

        lf = LoopFilter(c.filt, tref)
        osc = Oscillator(c.osc, c.fref, rng, noise=noise)
        band_trace = run_band_select(osc, c, rng, noise, band_select)
        lf.reset((0.0 if band_trace is not None
                  else (c.fout - c.osc.f0) / c.osc.gain)
                 + f_start_offset / c.osc.gain)
        fll = FLLStateMachine(n, c.fref, window=c.fll_window,
                              f_engage=c.fll_engage, f_release=c.fll_release,
                              i_fll=c.fll_i) if fll_enable else None

        # fractional-N: EFM residue -> DTC delays the DIVIDED edge so it
        # always samples the reference sine at the same phase
        mash = dtc_cal = None
        n_int = 0
        if c.frac is not None:
            mash = c.frac.make_mash()
            n_int = int(c.fout // c.fref)
            if calibration:
                dtc_cal = c.frac.dtc_cal

        if noise:
            jit_ref = synth_from_psd(
                FlickerFloorPhase.from_spot("ref", c.ref_pn_dbchz, c.ref_pn_fc).psd,
                c.fref, n_cycles, rng) / (TWOPI * c.fref)
            jit_div = synth_from_psd(
                FlickerFloorPhase.from_spot("div", c.div_pn_dbchz, c.div_pn_fc).psd,
                c.fref, n_cycles, rng) / (TWOPI * c.fref)
        else:
            jit_ref = np.zeros(n_cycles)
            jit_div = np.zeros(n_cycles)

        osc_noise = osc.noise_steps(n_cycles) if noise else np.zeros(n_cycles)
        v_sup = supply_ripple_v(supply_ripple, n_cycles, tref)
        f_pull = pull_hz(c.osc, n_cycles, tref)

        phase_err = np.empty(n_cycles)
        freq_out = np.empty(n_cycles)
        vctrl_rec = np.empty(n_cycles)
        fll_state = np.empty(n_cycles)
        cal_trace = np.empty(n_cycles if dtc_cal is not None else 0)
        m_os = max(int(fine_oversample), 1)
        fine_rec = np.empty(n_cycles * m_os) if m_os > 1 else np.empty(0)
        # at most three draws per cycle (DTC jitter, kT/C, gm charge), from
        # a pool in the order the loop consumes them
        zn = rng.standard_normal(3 * n_cycles) if noise else np.zeros(0)
        dtc_args = dtc_kernel_args(c.frac.dtc if c.frac is not None else None)
        mash_args = mash_kernel_args(mash, c.frac)
        cal_args = cal_kernel_args(dtc_cal)
        cal_st = cal_args[2]
        args: tuple[Any, ...] = (
            n_cycles, tref, float(c.fref), float(c.fout), 0.05 * c.osc.f0, float(n),
            int(n_int), int(osc.band), *osc_law_args(c.osc), float(c.osc.pushing_hz_v),
            v_sup, f_pull, osc_noise, jit_ref, jit_div, bool(noise), zn,
            *mash_args, *dtc_args,
            float(dtc_gain_init_error), dtc_gain_drift is not None,
            (np.asarray(dtc_gain_drift, dtype=float) if dtc_gain_drift is not None
             else np.zeros(0)),
            *cal_args, cal_trace,
            *fll_kernel_args(fll),
            float(c.sampler.amp_v), float(c.sampler.pedestal_v),
            float(c.sampler.ktc_sigma_v), float(c.sampler.gm),
            float(c.sampler.pulse_width), float(c.sampler.charge_sigma()),
            float(c.sampler.kick_q_c), float(c.sampler.kick_delay_s),
            lf.x, lf.ad, lf.b, lf._w, lf._v, lf._vinv, lf._vinv_b, lf._tmp, lf._xe,
            lf._xe0,
            m_os, fine_rec, np.empty(m_os), np.empty(3), np.empty(3), np.empty(m_os),
            phase_err, freq_out, vctrl_rec, fll_state)
        spll_kernel(*args)
        if dtc_cal is not None:
            dtc_cal.load_state(cal_st)
            dtc_cal.trace.extend(cal_trace[fll_state == 0.0].tolist())
        fine: np.ndarray | None = fine_rec if m_os > 1 else None

        t = np.arange(n_cycles) * tref
        lock = detect_lock(t, freq_out - c.fout, tol_hz=c.fout * 1e-5)
        sim = SimResult(fs=c.fref, f0=c.fout, t=t, phase_err_out=phase_err,
                        freq_out=freq_out, ctrl=vctrl_rec, lock_time_s=lock)
        sim.cal_traces["fll_engaged"] = fll_state
        if dtc_cal is not None:
            sim.cal_traces["dtc_gain"] = cal_trace
        spur_offsets = None
        if c.frac is not None:
            from ..core.dtcspurs import frac_spur_offsets
            spur_offsets = frac_spur_offsets(c.frac.frac, c.fref,
                                             fmin=8.0 * c.fref / n_cycles)
        if band_trace is not None:
            sim.cal_traces["band_select"] = band_trace
        if supply_ripple is not None and supply_ripple[1] < 0.45 * c.fref:
            spur_offsets = (spur_offsets or []) + [supply_ripple[1]]
        spur_offsets = add_pull_offset(spur_offsets, c.osc, c.fref)
        sim = postprocess(sim, int_band=c.int_band, spur_offsets=spur_offsets,
                          flicker_corner_hz=flicker_corner_hz(c))
        sim = tuning_sim_notes(sim, c.osc)
        if fine is not None:
            return attach_fine(sim, fine, m_os, c.fref, c.int_band, spur_offsets)
        return no_fine_note(sim)
