"""Sub-sampling PLL.

The VCO waveform is sampled directly by the reference edge — no divider in
the main loop.  The PD gain (A volts per rad of *output* phase) is what kills
the classic N^2 noise multiplication: charge-pump/gm and loop-filter noise
are NOT multiplied by N to the output.  Reference phase noise still is
(x N inherent to frequency multiplication).

A counter-based FLL acquires frequency (the SSPD alone has a capture range of
only ~loop-BW and false-lock points every pi of output phase) and hands off
with hysteresis.
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

TWOPI = 2.0 * np.pi


@dataclass
class SSPLLConfig:
    fref: float
    fout: float                     # N*fref, or (N+frac)*fref with frac config
    osc: OscConfig
    sampler: SamplerConfig
    filt: FilterDesign
    ref_pn_dbchz: float = -160.0
    ref_pn_fc: float = 20e3
    fll_i: float = 200e-6
    fll_window: int = 64
    fll_engage: float = 3e6
    fll_release: float = 500e3
    frac: "object | None" = None    # FracConfig (DTC-assisted fractional-N)
    int_band: tuple[float, float] = (1e3, 100e6)

    @property
    def n_mult(self) -> float:
        n = self.fout / self.fref
        if self.frac is None:
            if abs(n - round(n)) > 1e-9:
                raise ValueError("integer-N SSPLL requires integer fout/fref; "
                                 "provide FracConfig for fractional operation")
            return int(round(n))
        return n

    def __post_init__(self):
        if self.frac is not None:
            if abs((self.fout / self.fref) % 1.0 - self.frac.frac) > 1e-6:
                raise ValueError("fout/fref fractional part does not match "
                                 "FracConfig.frac")
            if self.frac.dtc is None:
                raise ValueError("fractional SSPLL requires a DTC in FracConfig "
                                 "(the sampler needs edge alignment)")
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
                    "fractional SSPLL uses a 1st-order EFM: its residue spans "
                    "exactly 1 UI, matching a practical DTC range (MASH-2/3 "
                    "spans 4-8 UI and saturates the DTC)")


class SSPLL(PLLBase):
    def __init__(self, cfg: SSPLLConfig):
        self.cfg = cfg

    # ------------------------------------------------------------- analyze
    def analyze(self, f: np.ndarray | None = None) -> AnalysisResult:
        c = self.cfg
        if f is None:
            f = default_grid(1e2, 1e9)
        n = c.n_mult
        s = c.sampler
        lf = LoopFilter(c.filt, 1.0 / c.fref)
        z = FreqResponse(f, lf.transimpedance(f))
        # exact discrete loop (SSPLLs run aggressive UGB/fref, the continuous
        # 1/s approximation misses the sampled-loop rolloff above UGB):
        # dq = K_q*phi_err; vctrl = Hq(z)*dq; phi += 2π·Kvco·vctrl·Tref
        k_q = s.amp_v * s.gm * s.pulse_width            # charge per rad
        hq = FreqResponse(f, lf.charge_tf_z(f))         # V/C, discrete-exact
        zinv = np.exp(-2j * np.pi * f / c.fref)
        acc = FreqResponse(f, zinv / (1.0 - zinv))
        gol = hq * acc * (k_q * TWOPI * c.osc.gain / c.fref)
        vco_int = FreqResponse.integrator(f, TWOPI * c.osc.gain)
        h = gol.feedback()
        err = 1.0 / (1.0 + gol)
        # the z-model is periodic in fref: loop-injected noise images beyond
        # fref/2 are physically attenuated by the vctrl zero-order hold; the
        # continuous VCO is NOT touched by the sampled model's image dips
        zoh = FreqResponse.zoh(f, c.fref)
        h_loop = h * zoh
        err_vco = FreqResponse(f, np.where(f < c.fref / 2, err.h, 1.0))

        paths = [
            NoisePath(FlickerFloorPhase.from_spot("ref", c.ref_pn_dbchz, c.ref_pn_fc),
                      h_loop * n),
            NoisePath(SampledKTC(name="sampler_ktc", unit="V^2/Hz",
                                 c_farad=s.c_samp, fs=c.fref),
                      h_loop * (1.0 / s.amp_v)),
            # the gm stage dumps ONE charge packet per reference cycle, so it
            # is a sampled source (2x alias factor), not a duty-cycled current
            NoisePath(SampledChargeNoise(name="gm", unit="C^2/Hz",
                                         i2=s.gm_i2(), tau=s.pulse_width,
                                         fs=c.fref),
                      h_loop * (1.0 / (s.amp_v * s.gm * s.pulse_width))),
            NoisePath(ResistorNoise(name="lf_r2", unit="V^2/Hz", r_ohm=c.filt.r2),
                      FreqResponse(f, self._r2_tf(f)) * vco_int * err_vco),
            NoisePath(c.osc.leeson("vco"), err_vco),
        ]
        if c.frac is not None:
            from ..core.noise import NoiseSource, ShapedQuantization
            d = c.frac.dtc
            paths.append(NoisePath(
                ShapedQuantization(name="dtc_quant", unit="rad^2/Hz",
                                   q=TWOPI * d.t_res * c.fout, fs=c.fref,
                                   order=0), h_loop))
            if d.jitter_rms_s > 0:
                paths.append(NoisePath(
                    NoiseSource(name="dtc_jitter", unit="rad^2/Hz",
                                level=2.0 * (TWOPI * c.fout * d.jitter_rms_s) ** 2
                                / c.fref), h_loop))
            eps = getattr(d, "gain_error_residual", 0.01)
            paths.append(NoisePath(
                ShapedQuantization(name="dsm_residual", unit="rad^2/Hz",
                                   q=TWOPI * eps, fs=c.fref, order=0), h_loop))
        m = loop_metrics(gol)
        bd = output_psd(paths, f)
        jit = rms_jitter_fs(f, bd["total"], c.fout, *c.int_band)
        # Reference spur: from the sampling clock's kickback, NOT the pedestal.
        # The pedestal shifts the held voltage and the gm converts that same
        # held voltage over the same window, so the loop parks where the gm
        # delivers zero charge -- zero charge is zero ripple.  See
        # SamplerConfig.kick_q_c.
        pd_a = SamplingPD(s, 1.0 / c.fref, np.random.default_rng(0), noise=False)
        zf = np.interp(np.log10(c.fref), np.log10(f), np.abs(z.h))
        i1 = pd_a.ripple_fundamental_a(1.0 / c.fref)
        beta = c.osc.gain * (i1 * zf) / c.fref
        spurs = {}
        if i1 > 0:
            spurs["ref_spur"] = float(20 * np.log10(beta / 2))
        spurs.update(pull_spur(c.osc, err_vco))
        if c.frac is not None:
            from ..core.dtcspurs import dtc_spur_table
            d = c.frac.dtc
            eps = getattr(d, "gain_error_residual", 0.01)
            for off, dbc in dtc_spur_table(
                    c.frac,
                    lambda r: (1.0 + r) / c.fout - d.range_s / 2.0,
                    c.fref, c.fout, ntf=h, gain_eps=eps).items():
                spurs[f"frac_spur@{off:.0f}Hz"] = dbc
        notes = [f"PD gain referred to output phase: CP/LF noise not multiplied "
                 f"by N={n} (the SSPLL advantage)"] + pull_notes(c.osc)
        if i1 == 0.0:
            notes.append(
                "no reference spur reported: the sampling pedestal produces a "
                "static phase offset, not ripple — the gm converts the held "
                "voltage over the same window the loop uses to cancel it, so "
                "in lock it delivers no charge.  Set SamplerConfig.kick_q_c "
                "and kick_delay_s to model the sampling clock's kickback, "
                "which is what actually makes this architecture's ref spur")
        return AnalysisResult(f=f, f0=c.fout, pn_breakdown=bd, loop=m,
                              jitter_fs=jit,
                              ipn_dbc=ipn_dbc(f, bd["total"], *c.int_band),
                              int_band=c.int_band, spurs_analytic=spurs,
                              ntfs={"gol": gol, "h": h, "err": err}, notes=notes)

    def _r2_tf(self, f):
        d = self.cfg.filt
        sc = 2j * np.pi * f
        zc1 = 1.0 / (sc * d.c1)
        zc2 = 1.0 / (sc * d.c2)
        return zc2 / (d.r2 + zc1 + zc2)

    # ------------------------------------------------------------ simulate
    def simulate(self, n_cycles: int, *, noise: bool = True, calibration: bool = True,
                 seed: int = 0, f_start_offset: float = 0.0,
                 fll_enable: bool = True,
                 supply_ripple: tuple[float, float] | None = None,
                 band_select: bool = True,
                 dtc_gain_init_error: float = 0.0,
                 fine_oversample: int = 1,
                 mod_freq: np.ndarray | None = None,
                 mod_dp_gain: float = 1.0,
                 dtc_gain_drift: np.ndarray | None = None) -> SimResult:
        """fine_oversample: record M control-voltage samples per reference
        period instead of one, so the intra-period ripple that carries the
        reference spur is observable at all (at M=1 it sits exactly at the
        record's sampling rate and aliases to DC).
        mod_freq: two-point modulation trajectory [Hz] on the fref grid
        (pllsim.modulation).  Lowpass point: the sampling instant is shifted
        by the accumulated modulation phase (DTC path, Markulic-style);
        highpass point: direct VCO frequency push scaled by mod_dp_gain
        (1.0 = matched two-point)."""
        c = self.cfg
        rng = np.random.default_rng(seed)
        tref = 1.0 / c.fref
        n = c.n_mult

        lf = LoopFilter(c.filt, tref)
        vlock = (c.fout - c.osc.f0) / c.osc.gain
        osc = Oscillator(c.osc, c.fref, rng, noise=noise)
        band_trace = run_band_select(osc, c, rng, noise, band_select)
        lf.reset((0.0 if band_trace is not None else vlock)
                 + f_start_offset / c.osc.gain)
        pd = SamplingPD(c.sampler, tref, rng, noise=noise)
        fll = FLLStateMachine(n, c.fref, window=c.fll_window,
                              f_engage=c.fll_engage, f_release=c.fll_release,
                              i_fll=c.fll_i) if fll_enable else None

        # fractional-N: EFM residue -> DTC shifts the sampling instant so the
        # reference edge always lands on a VCO zero crossing
        mash = dtc = dtc_cal = None
        frac_word = 0
        if c.frac is not None:
            from ..blocks.dtc import DTC
            mash = c.frac.make_mash()
            frac_word = c.frac.frac_word
            dtc = DTC(c.frac.dtc, rng, noise=noise,
                      gain_error=dtc_gain_init_error)
            if calibration:
                dtc_cal = c.frac.dtc_cal

        jit_ref = (synth_from_psd(
            FlickerFloorPhase.from_spot("ref", c.ref_pn_dbchz, c.ref_pn_fc).psd,
            c.fref, n_cycles, rng) / (TWOPI * c.fref)) if noise else np.zeros(n_cycles)

        osc_noise = osc.noise_steps(n_cycles) if noise else np.zeros(n_cycles)
        prev_on = 0.0
        phi_frac = 0.0          # VCO phase modulo 2pi at the sampling instant
        phi_out = 0.0
        v_sup = supply_ripple_v(supply_ripple, n_cycles, tref)
        f_pull = pull_hz(c.osc, n_cycles, tref)
        fv = osc.freq(lf.vctrl, v_sup[0])

        phase_err = np.empty(n_cycles)
        freq_out = np.empty(n_cycles)
        vctrl_rec = np.empty(n_cycles)
        fll_state = np.empty(n_cycles)
        cal_trace = np.empty(n_cycles) if dtc_cal is not None else None
        prev_extra = 0.0
        phi_m = 0.0                     # accumulated modulation phase [rad]
        m_os = max(int(fine_oversample), 1)
        fine = np.empty(n_cycles * m_os) if m_os > 1 else None

        for nn in range(n_cycles):
            d_osc = osc_noise[nn] - prev_on
            prev_on = osc_noise[nn]
            # sampling-instant shift this cycle: ref jitter + DTC alignment
            extra = jit_ref[nn]
            if mod_freq is not None:
                # lowpass point: expect the VCO zero crossing at +phi_m —
                # sample earlier by phi_m (wrapped to one VCO period; a
                # wrap only renumbers the sampled edge).  One cycle behind
                # the direct point: fv carries mod_freq[nn-1] this cycle.
                phi_m += TWOPI * (mod_freq[nn - 1] if nn > 0 else 0.0) * tref
                phi_w = ((phi_m + np.pi) % TWOPI) - np.pi
                # convert with the CURRENT VCO frequency: using the nominal
                # fout leaks 2*pi*mod/fv per wrap, data-correlated
                extra -= phi_w / (TWOPI * fv)
            residual_ui = 0.0
            if mash is not None and dtc is not None:
                if dtc_gain_drift is not None:
                    dtc.gain_error = dtc_gain_drift[nn]
                residual_ui = mash.residual_ui()
                # EFM1 residue is one-sided in (-1, 0]: aim for a delay of
                # (1+residual)*Tvco in (0, Tvco], cancelling the DTC's internal
                # bipolar mid-range offset so no codes clip at zero
                t_target = (1.0 + residual_ui) / c.fout - c.frac.dtc.range_s / 2.0
                extra += dtc.delay(t_target)
            dt_period = tref + extra - prev_extra
            prev_extra = extra
            cycles = fv * dt_period + d_osc / TWOPI
            phi_frac = (phi_frac + TWOPI * cycles) % TWOPI

            dq = 0.0
            engaged = False
            if fll is not None:
                dq_fll = fll.step(cycles)
                engaged = fll.engaged
                dq += dq_fll
            if not engaged:
                perr = ((phi_frac + np.pi) % TWOPI) - np.pi
                vs = pd.sample(perr)
                # inverting gm: VCO phase ahead (perr>0) must pull vctrl down
                dq -= pd.charge(vs)
                if dtc_cal is not None and dtc is not None:
                    # under-delayed DTC samples early -> vs anti-correlates
                    # with the residue; positive update needs err = -vs
                    dtc_cal.step(-vs, residual_ui)
                    dtc.gain_corr = dtc_cal.value
            if cal_trace is not None:
                cal_trace[nn] = dtc_cal.value if dtc_cal is not None else 1.0
            if mash is not None:
                mash.step(frac_word)
            if fine is None:
                lf.update_pulse(dq / max(c.sampler.pulse_width, 1e-12),
                                c.sampler.pulse_width)
                fv = max(osc.freq(lf.vctrl, v_sup[nn], f_pull[nn]),
                         0.05 * c.osc.f0)
                if mod_freq is not None:    # highpass point: direct VCO push
                    fv += mod_freq[nn] * mod_dp_gain
            else:
                # clock kickback and the gm pulse land at different instants;
                # that separation is the whole reference-spur mechanism here
                v_sub = lf.drive_fine(pd.segments(dq), m_os)
                f_sub = np.maximum(
                    np.array([osc.freq(v, v_sup[nn], f_pull[nn]) for v in v_sub]),
                    0.05 * c.osc.f0)
                if mod_freq is not None:
                    f_sub = f_sub + mod_freq[nn] * mod_dp_gain
                fv = float(f_sub[-1])

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
