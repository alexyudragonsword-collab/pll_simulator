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
from ..core.noise import (CurrentNoise, FlickerFloorPhase, NoisePath,
                          ResistorNoise, SampledKTC, output_psd)
from ..core.results import AnalysisResult, SimResult
from .base import PLLBase

TWOPI = 2.0 * np.pi


@dataclass
class SSPLLConfig:
    fref: float
    fout: float                     # integer multiple of fref
    osc: OscConfig
    sampler: SamplerConfig
    filt: FilterDesign
    ref_pn_dbchz: float = -160.0
    ref_pn_fc: float = 20e3
    fll_i: float = 200e-6
    fll_window: int = 64
    fll_engage: float = 3e6
    fll_release: float = 500e3
    int_band: tuple[float, float] = (1e3, 100e6)

    @property
    def n_mult(self) -> int:
        n = self.fout / self.fref
        if abs(n - round(n)) > 1e-9:
            raise ValueError("SSPLL requires integer fout/fref")
        return int(round(n))


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
        duty = s.pulse_width * c.fref
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
        k_cp = s.amp_v * s.gm * duty                    # average A/rad (spur calc)
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
            NoisePath(CurrentNoise(name="gm", unit="A^2/Hz", i2=s.gm_i2(),
                                   duty=duty),
                      h_loop * (1.0 / k_cp)),
            NoisePath(ResistorNoise(name="lf_r2", unit="V^2/Hz", r_ohm=c.filt.r2),
                      FreqResponse(f, self._r2_tf(f)) * vco_int * err_vco),
            NoisePath(c.osc.leeson("vco"), err_vco),
        ]
        m = loop_metrics(gol)
        bd = output_psd(paths, f)
        jit = rms_jitter_fs(f, bd["total"], c.fout, *c.int_band)
        # ref spur: pedestal charge ripple through Z at fref
        dq = abs(s.gm * s.pedestal_v * s.pulse_width)
        zf = np.interp(np.log10(c.fref), np.log10(f), np.abs(z.h))
        beta = c.osc.gain * 2.0 * dq * c.fref * zf / (2.0 * c.fref)
        spurs = {"ref_spur": float(20 * np.log10(max(beta / 2, 1e-30)))}
        notes = [f"PD gain referred to output phase: CP/LF noise not multiplied "
                 f"by N={n} (the SSPLL advantage)"]
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
                 fll_enable: bool = True) -> SimResult:
        c = self.cfg
        rng = np.random.default_rng(seed)
        tref = 1.0 / c.fref
        n = c.n_mult

        lf = LoopFilter(c.filt, tref)
        vlock = (c.fout - c.osc.f0) / c.osc.gain
        lf.reset(vlock + f_start_offset / c.osc.gain)
        osc = Oscillator(c.osc, c.fref, rng, noise=noise)
        pd = SamplingPD(c.sampler, tref, rng, noise=noise)
        fll = FLLStateMachine(n, c.fref, window=c.fll_window,
                              f_engage=c.fll_engage, f_release=c.fll_release,
                              i_fll=c.fll_i) if fll_enable else None

        jit_ref = (synth_from_psd(
            FlickerFloorPhase.from_spot("ref", c.ref_pn_dbchz, c.ref_pn_fc).psd,
            c.fref, n_cycles, rng) / (TWOPI * c.fref)) if noise else np.zeros(n_cycles)

        osc_noise = osc.noise_steps(n_cycles) if noise else np.zeros(n_cycles)
        prev_on = 0.0
        phi_frac = 0.0          # VCO phase modulo 2pi at the sampling instant
        phi_out = 0.0
        fv = osc.freq(lf.vctrl)

        phase_err = np.empty(n_cycles)
        freq_out = np.empty(n_cycles)
        vctrl_rec = np.empty(n_cycles)
        fll_state = np.empty(n_cycles)

        for nn in range(n_cycles):
            d_osc = osc_noise[nn] - prev_on
            prev_on = osc_noise[nn]
            # VCO cycles elapsed in this (jittered) ref period
            dt_period = tref + (jit_ref[nn] - jit_ref[nn - 1] if nn else jit_ref[0])
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
            lf.update_pulse(dq / max(c.sampler.pulse_width, 1e-12),
                            c.sampler.pulse_width)
            fv = max(osc.freq(lf.vctrl), 0.05 * c.osc.f0)

            phi_out += TWOPI * (fv - c.fout) * tref + d_osc
            phase_err[nn] = phi_out
            freq_out[nn] = fv
            vctrl_rec[nn] = lf.vctrl
            fll_state[nn] = 1.0 if engaged else 0.0

        t = np.arange(n_cycles) * tref
        lock = detect_lock(t, freq_out - c.fout, tol_hz=c.fout * 1e-5)
        sim = SimResult(fs=c.fref, f0=c.fout, t=t, phase_err_out=phase_err,
                        freq_out=freq_out, ctrl=vctrl_rec, lock_time_s=lock)
        sim.cal_traces["fll_engaged"] = fll_state
        return postprocess(sim, int_band=c.int_band)
