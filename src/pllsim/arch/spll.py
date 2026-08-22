"""(Reference-)Sampling PLL — the dual of the SSPLL.

Here a divided VCO edge samples the *reference* sine, so the PD gain is
referred to REFERENCE phase (A volts per rad at fref).  Consequently sampler
and gm noise ARE multiplied by N to the output — the honest comparison with
the SSPLL (see ex04): same sampler front-end, ~20logN worse in-band PD noise,
but a full +/-pi capture range at the reference carrier and a conventional
divider for frequency acquisition.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..blocks.loopfilter import FilterDesign, LoopFilter
from ..blocks.oscillator import OscConfig, Oscillator
from ..blocks.sampler import SamplerConfig, SamplingPD
from ..calibration.ftl import FLLStateMachine
from ..core.colored import synth_from_psd
from ..core.engine import detect_lock, postprocess
from ..core.freqresp import FreqResponse, default_grid, loop_metrics
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
    pull_hz,
    pull_notes,
    pull_spur,
    run_band_select,
    supply_ripple_v,
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
                raise ValueError("fout/fref fractional part does not match "
                                 "FracConfig.frac")
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
                    "exactly 1 UI, matching a practical DTC range")


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
        m = loop_metrics(gol)
        bd = output_psd(paths, f)
        # Same accounting as the SSPLL: the pedestal shifts the held voltage
        # and the gm converts that same held voltage over the same window, so
        # the loop parks where the gm delivers zero charge and there is no
        # ripple to make a spur from.  The kickback is the mechanism that
        # survives, because it lands at a different instant.
        from ..blocks.sampler import SamplingPD
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
                    lambda r: -r / c.fout - d.range_s / 2.0,
                    c.fref, c.fout, ntf=h, gain_eps=eps_g).items():
                spurs[f"frac_spur@{off:.0f}Hz"] = dbc
        spurs.update(pull_spur(c.osc, err))
        notes = [f"PD gain referred to reference phase: sampler/gm noise "
                 f"multiplied by N={n} at the output (contrast with SSPLL)"]
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
                              ntfs={"gol": gol, "h": h, "err": err}, notes=notes)

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
        pd = SamplingPD(c.sampler, tref, rng, noise=noise)
        fll = FLLStateMachine(n, c.fref, window=c.fll_window,
                              f_engage=c.fll_engage, f_release=c.fll_release,
                              i_fll=c.fll_i) if fll_enable else None

        # fractional-N: EFM residue -> DTC delays the DIVIDED edge so it
        # always samples the reference sine at the same phase
        mash = dtc = dtc_cal = None
        frac_word = 0
        n_int = 0
        if c.frac is not None:
            from ..blocks.dtc import DTC
            mash = c.frac.make_mash()
            frac_word = c.frac.frac_word
            n_int = int(c.fout // c.fref)
            dtc = DTC(c.frac.dtc, rng, noise=noise,
                      gain_error=dtc_gain_init_error)
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
        prev_on = 0.0
        t_div = 0.0
        phi_out = 0.0
        v_sup = supply_ripple_v(supply_ripple, n_cycles, tref)
        f_pull = pull_hz(c.osc, n_cycles, tref)
        fv = osc.freq(lf.vctrl, v_sup[0], f_pull[0])

        phase_err = np.empty(n_cycles)
        freq_out = np.empty(n_cycles)
        vctrl_rec = np.empty(n_cycles)
        fll_state = np.empty(n_cycles)

        cal_trace = np.empty(n_cycles) if dtc_cal is not None else None
        m_os = max(int(fine_oversample), 1)
        fine = np.empty(n_cycles * m_os) if m_os > 1 else None

        for nn in range(n_cycles):
            d_osc = osc_noise[nn] - prev_on
            prev_on = osc_noise[nn]

            dq = 0.0
            engaged = False
            if fll is not None:
                dq += fll.step(fv / c.fref)
                engaged = fll.engaged
            residual_ui = 0.0
            d_dtc = 0.0
            if mash is not None and dtc is not None:
                if dtc_gain_drift is not None:
                    dtc.gain_error = dtc_gain_drift[nn]
                # EFM1 residue in (-1, 0]: the divided edge is EARLY by
                # |residual|·Tvco -> delay it by -residual·Tvco in (0, Tvco],
                # cancelling the DTC's bipolar mid-range offset
                residual_ui = mash.residual_ui()
                t_target = -residual_ui / c.fout - c.frac.dtc.range_s / 2.0
                d_dtc = dtc.delay(t_target)
            if not engaged:
                # (DTC-delayed) divided VCO edge samples the reference sine
                perr_ref = TWOPI * c.fref * (t_div + d_dtc + jit_div[nn]
                                             - nn * tref - jit_ref[nn])
                perr_ref = ((perr_ref + np.pi) % TWOPI) - np.pi
                vs = pd.sample(perr_ref)
                dq += pd.charge(vs)     # divider late -> vs>0 -> speed up VCO
                if dtc_cal is not None and dtc is not None:
                    # target delay ∝ -residual: under-delay correlates vs
                    # POSITIVELY with residual -> err = +vs
                    dtc_cal.step(vs, residual_ui)
                    dtc.gain_corr = dtc_cal.value
            if cal_trace is not None:
                cal_trace[nn] = dtc_cal.value if dtc_cal is not None else 1.0
            if fine is None:
                lf.update_pulse(dq / max(c.sampler.pulse_width, 1e-12),
                                c.sampler.pulse_width)
                fv = max(osc.freq(lf.vctrl, v_sup[nn], f_pull[nn]),
                         0.05 * c.osc.f0)
            else:
                # kickback and gm pulse land at different instants; that
                # separation is the reference-spur mechanism here
                vsub = lf.drive_fine(pd.segments(dq), m_os)
                f_sub = np.maximum(
                    np.array([osc.freq(v, v_sup[nn], f_pull[nn]) for v in vsub]),
                    0.05 * c.osc.f0)
                fv = float(f_sub[-1])

            n_next = n if mash is None else n_int + mash.step(frac_word)
            t_div += n_next / fv - d_osc / (TWOPI * fv)
            if fine is None:
                phi_out += TWOPI * (fv - c.fout) * tref + d_osc
            else:
                inc = TWOPI * (f_sub - c.fout) * (tref / m_os) + d_osc / m_os
                fine[nn * m_os:(nn + 1) * m_os] = phi_out + np.cumsum(inc)
                phi_out = float(fine[(nn + 1) * m_os - 1])
            phase_err[nn] = phi_out
            freq_out[nn] = fv
            vctrl_rec[nn] = lf.vctrl
            fll_state[nn] = 1.0 if engaged else 0.0

        t = np.arange(n_cycles) * tref
        lock = detect_lock(t, freq_out - c.fout, tol_hz=c.fout * 1e-5)
        sim = SimResult(fs=c.fref, f0=c.fout, t=t, phase_err_out=phase_err,
                        freq_out=freq_out, ctrl=vctrl_rec, lock_time_s=lock)
        sim.cal_traces["fll_engaged"] = fll_state
        if cal_trace is not None:
            sim.cal_traces["dtc_gain"] = cal_trace
        spur_offsets = None
        if c.frac is not None:
            from .cppll import frac_spur_offsets
            spur_offsets = frac_spur_offsets(c.frac.frac, c.fref,
                                             fmin=8.0 * c.fref / n_cycles)
        if band_trace is not None:
            sim.cal_traces["band_select"] = band_trace
        if supply_ripple is not None and supply_ripple[1] < 0.45 * c.fref:
            spur_offsets = (spur_offsets or []) + [supply_ripple[1]]
        spur_offsets = add_pull_offset(spur_offsets, c.osc, c.fref)
        sim = postprocess(sim, int_band=c.int_band, spur_offsets=spur_offsets)
        if fine is not None:
            return attach_fine(sim, fine, m_os, c.fref, c.int_band, spur_offsets)
        return sim
