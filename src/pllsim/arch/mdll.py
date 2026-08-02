"""Multiplying DLL (MDLL).

The ILCM's limiting case: once per reference period the oscillator edge is
not merely pulled toward the reference — it is REPLACED by the clean
reference edge (mux select).  Accumulated oscillator jitter is therefore
reset to zero every Tref, and only the intra-period accumulation survives:

    theta_osc(t) = W(t) - W(t_k)   for t in [t_k, t_k+1)

i.e. the oscillator noise sees  NTF = 1 - ZOH(f)  (sample-and-subtract),
|NTF| ~ pi f/fref at low offset — a highpass with corner ~ fref/pi, far more
aggressive than any realizable PLL bandwidth.  The reference path is a flat
xN up to Nyquist (ZOH-shaped).

A digital tuning loop (bang-bang PD on the pre-select error, integrator on
the DCO word) keeps the ring's free-running period at Tvco: its residual
frequency error produces the deterministic per-period phase ramp and hence
the fref spur — exactly the ILCM mechanism, with the same sawtooth analytic.

Time domain: per reference cycle, exact.  Between selects the ring
accumulates (f_free - N fref) drift + open-loop noise; at the select instant
the phase error is replaced by the reference/mux error.  Intra-period
oversampled recording (analytic ramp) exposes the fref spur and the true
sawtooth-of-random-walk noise floor.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..blocks.oscillator import OscConfig, Oscillator
from ..core.colored import synth_from_psd
from ..core.engine import postprocess
from ..core.freqresp import FreqResponse, LoopMetrics, default_grid
from ..core.jitter import ipn_dbc, rms_jitter_fs
from ..core.noise import FlickerFloorPhase, NoisePath, NoiseSource, output_psd
from ..core.results import AnalysisResult, SimResult
from .base import PLLBase
from .ilcm import injection_spur_dbc

TWOPI = 2.0 * np.pi


@dataclass
class MDLLConfig:
    fref: float
    fout: float                      # N * fref
    osc: OscConfig                   # ring: f0 free-running, gain = Hz/LSB
    mux_jitter_rms_s: float = 50e-15   # select-path/mux random jitter
    ref_pn_dbchz: float = -155.0
    ref_pn_fc: float = 20e3
    # digital tuning loop: bang-bang PD on the pre-select error driving an
    # integrator on the DCO word (step size in LSB per reference cycle)
    tune_ki_lsb: float = 0.02
    int_band: tuple[float, float] = (1e3, 100e6)

    @property
    def n_mult(self) -> int:
        n = self.fout / self.fref
        if abs(n - round(n)) > 1e-9:
            raise ValueError("MDLL requires integer fout/fref")
        return int(round(n))


class MDLL(PLLBase):
    def __init__(self, cfg: MDLLConfig):
        self.cfg = cfg

    # ------------------------------------------------------------- analyze
    def analyze(self, f: np.ndarray | None = None,
                f_free_error: float = 0.0) -> AnalysisResult:
        c = self.cfg
        if f is None:
            f = default_grid(1e2, 1e9)
        n = c.n_mult
        # oscillator: sample-and-subtract NTF = 1 - ZOH (edge replacement)
        ntf_osc = 1.0 - FreqResponse.zoh(f, c.fref)
        ntf_osc = FreqResponse(f, np.where(f < 0.5 * c.fref, ntf_osc.h, 1.0))
        # reference & mux: flat to the output (xN), ZOH images beyond Nyquist
        zoh = FreqResponse.zoh(f, c.fref)

        paths = [
            NoisePath(c.osc.leeson("ring"), ntf_osc),
            NoisePath(FlickerFloorPhase.from_spot("ref", c.ref_pn_dbchz,
                                                  c.ref_pn_fc), zoh * n),
            NoisePath(NoiseSource(name="mux_jitter", unit="rad^2/Hz",
                                  level=2.0 * (TWOPI * c.fout
                                               * c.mux_jitter_rms_s) ** 2
                                  / c.fref), zoh),
        ]
        bd = output_psd(paths, f)
        jit = rms_jitter_fs(f, bd["total"], c.fout, *c.int_band)
        f_c = c.fref / np.pi
        m = LoopMetrics(f_ugb=f_c, pm_deg=float("nan"), gm_db=float("inf"),
                        f_3db=f_c, peaking_db=0.0, n_crossings=1)
        dphi = TWOPI * f_free_error / c.fref
        # nothing to report without a residual frequency error to make a
        # sawtooth out of; -600 dBc reads as "spurless by design"
        spurs = ({"ref_spur": injection_spur_dbc(dphi, 1.0)}
                 if f_free_error else {})
        notes = [f"edge replacement: oscillator noise highpassed with corner "
                 f"~fref/pi = {f_c / 1e6:.1f} MHz (beta=1 limit of the ILCM)"]
        return AnalysisResult(f=f, f0=c.fout, pn_breakdown=bd, loop=m,
                              jitter_fs=jit,
                              ipn_dbc=ipn_dbc(f, bd["total"], *c.int_band),
                              int_band=c.int_band, spurs_analytic=spurs,
                              ntfs={"ntf_osc": ntf_osc, "zoh": zoh},
                              notes=notes)

    # ------------------------------------------------------------ simulate
    def simulate(self, n_cycles: int, *, noise: bool = True, calibration: bool = True,
                 seed: int = 0, f_free_error: float = 0.0,
                 fine_oversample: int = 4) -> SimResult:
        c = self.cfg
        rng = np.random.default_rng(seed)
        tref = 1.0 / c.fref

        osc = Oscillator(c.osc, c.fref, rng, noise=noise)
        jit_ref = (synth_from_psd(
            FlickerFloorPhase.from_spot("ref", c.ref_pn_dbchz, c.ref_pn_fc).psd,
            c.fref, n_cycles, rng) / (TWOPI * c.fref)) if noise else np.zeros(n_cycles)

        osc_noise = osc.noise_steps(n_cycles) if noise else np.zeros(n_cycles)
        prev_on = 0.0

        e = 0.0                       # output phase error at select instants
        tune_acc = 0.0                # DCO integrator [LSB]
        phase_err = np.empty(n_cycles)
        freq_out = np.empty(n_cycles)
        ctrl = np.empty(n_cycles)
        m_os = max(int(fine_oversample), 1)
        fine = np.empty(n_cycles * m_os) if m_os > 1 else None

        for nn in range(n_cycles):
            d_osc = osc_noise[nn] - prev_on
            prev_on = osc_noise[nn]
            f_free = c.osc.freq_law(tune_acc) + f_free_error
            dphi_drift = TWOPI * (f_free - c.fout) * tref
            e_pre = e + dphi_drift + d_osc
            if fine is not None:
                fine[nn * m_os:(nn + 1) * m_os] = \
                    e + (dphi_drift + d_osc) * np.arange(m_os) / m_os
            # edge replacement: output phase becomes the reference/mux edge
            phi_inj = TWOPI * c.fout * jit_ref[nn]
            if noise and c.mux_jitter_rms_s > 0:
                phi_inj += TWOPI * c.fout * rng.normal(0.0, c.mux_jitter_rms_s)
            # digital tuning loop observes the pre-select error (BB + integ.)
            if calibration:
                s = np.sign(e_pre - phi_inj)
                tune_acc -= c.tune_ki_lsb * s
            e = phi_inj

            phase_err[nn] = e
            freq_out[nn] = f_free
            ctrl[nn] = tune_acc

        t = np.arange(n_cycles) * tref
        sim = SimResult(fs=c.fref, f0=c.fout, t=t, phase_err_out=phase_err,
                        freq_out=freq_out, ctrl=ctrl, lock_time_s=None)
        sim.cal_traces["tune_acc"] = ctrl.copy()
        sim = postprocess(sim, int_band=c.int_band)
        if fine is not None:
            from ..core.spectrum import find_spurs, periodogram_psd
            n0 = fine.size // 4
            f_p, s_p = periodogram_psd(fine[n0:], m_os * c.fref)
            sim.extra["fine_fs"] = m_os * c.fref
            sim.extra["fine_f"], sim.extra["fine_psd"] = f_p, s_p
            sim.spurs_fft.update(find_spurs(f_p, s_p, [c.fref, 2 * c.fref]))
            # the honest MDLL jitter includes the intra-period accumulation
            # that ref-rate sampling misses entirely (e = mux/ref only)
            sim.jitter_fs = rms_jitter_fs(
                f_p, s_p, c.fout,
                max(c.int_band[0], f_p[0]), min(c.int_band[1], 0.45 * m_os * c.fref))
            sim.notes.append(
                f"jitter integrated on the {m_os}x oversampled phase "
                "(includes intra-period accumulation)")
        else:
            sim.notes.append("jitter integrated at the reference rate: "
                             "intra-period accumulation is NOT included — "
                             "pass fine_oversample>1 to capture it")
        return sim
