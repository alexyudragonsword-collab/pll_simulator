"""Injection-locked clock multiplier (ILCM).

Per-reference-cycle realignment model — exact for pulse injection:

    e[n+1] = (1-beta) * (e[n] + dphi_drift + phi_osc[n]) + beta * phi_inj[n]

  e          oscillator phase error at the injection instant [rad]
  beta       realignment factor (0..1); LC: beta ~ derived from Iinj/Iosc & Q
  dphi_drift 2π (f_free - N fref) Tref  — frequency-error phase ramp
  phi_osc    open-loop oscillator phase noise accumulated over one Tref
  phi_inj    reference edge noise + injection timing error, in rad at fout

Frequency domain (z = e^{j2πf/fref}) follows directly:
  oscillator noise NTF  Hosc(z) = (1-beta)/(1 - (1-beta) z^-1)   (highpass-ish)
  reference/timing NTF  Hinj(z) = beta/(1 - (1-beta) z^-1)       (lowpass), xN
  injection "bandwidth" ~ -fref·ln(1-beta)/(2π) ~ beta·fref/(2π) for small beta.

Lock range: the injection realigns toward the NEAREST edge (wrap at +/-pi),
so steady state requires |dphi_drift/beta| < pi  =>  |f_free - N fref| <
beta*fref/2.  LC-tank cross-check: Δf_L = f0 · Iinj/(2 Q Iosc).

Injection spur: the steady-state sawtooth phase ripple e* = dphi_drift(1-beta)/beta
peak-to-peak dphi_drift; first Fourier coefficient of the sawtooth at fref
offset: spur ≈ 20 log10(dphi_ripple_fundamental/2).

The FTL (bang-bang frequency tracking of f_free) keeps dphi_drift near zero —
its residual sets the spur, which ex06 sweeps.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..blocks.oscillator import OscConfig, Oscillator
from ..calibration.ftl import FTL
from ..core.colored import synth_from_psd
from ..core.engine import postprocess
from ..core.freqresp import FreqResponse, LoopMetrics, default_grid
from ..core.jitter import ipn_dbc, rms_jitter_fs
from ..core.noise import FlickerFloorPhase, NoisePath, output_psd
from ..core.results import AnalysisResult, SimResult
from .base import PLLBase, attach_fine, no_fine_note, supply_ripple_v

TWOPI = 2.0 * np.pi


@dataclass
class ILCMConfig:
    fref: float
    fout: float                     # N * fref
    osc: OscConfig                  # f0 = free-running frequency
    beta: float = 0.5               # realignment factor
    q_tank: float | None = None     # LC: report Adler lock range for cross-check
    i_ratio: float | None = None    # Iinj/Iosc for the Adler cross-check
    inj_jitter_rms_s: float = 20e-15   # injection path random jitter
    ref_pn_dbchz: float = -160.0
    ref_pn_fc: float = 20e3
    ftl: bool = True
    ftl_f_lsb: float = 50e3         # frequency DAC LSB
    ftl_mu: float = 1.0
    ftl_det_offset_s: float = 0.0   # FTL detector input-referred offset: the
                                    # FTL then parks with a residual drift,
                                    # which IS the injection spur (ex06)
    timing_cal: bool = False        # InjTimingCal corrects that offset
    timing_cal_step_s: float = 50e-15
    int_band: tuple[float, float] = (1e3, 100e6)

    def __post_init__(self):
        if self.osc.n_bands > 1:
            raise ValueError("ILCM models no coarse-band search: "
                             "its oscillator runs free and the FTL corrects it in Hz")
        # The FTL corrects the free-running frequency directly in Hz
        # (ftl_f_lsb), so this architecture never evaluates a control-voltage
        # law: OscConfig's tuning knobs would be accepted and ignored.
        o = self.osc
        ignored = [n for n in ("nl1", "nl2", "pushing_hz_v")
                   if getattr(o, n, 0.0)] \
            + [n for n in ("v_min", "v_max") if getattr(o, n, None) is not None]
        if ignored:
            raise ValueError(
                f"ILCM does not evaluate a tuning law, so OscConfig "
                f"{', '.join(ignored)} would have no effect: its FTL corrects "
                "the free-running frequency directly in Hz (ftl_f_lsb), and "
                "the injection sets the bandwidth")

    @property
    def n_mult(self) -> int:
        n = self.fout / self.fref
        if abs(n - round(n)) > 1e-9:
            raise ValueError("ILCM requires integer fout/fref")
        return int(round(n))

    def lock_range_hz(self) -> float:
        """Discrete realignment lock bound on |f_free - N fref|.

        The injection realigns toward the NEAREST output edge (phase wraps at
        +/-pi): steady state needs |dphi_drift / beta| < pi, i.e.
        |f_free - N fref| < beta * fref / 2.
        """
        return self.beta * self.fref / 2.0

    def adler_lock_range_hz(self) -> float | None:
        if self.q_tank and self.i_ratio:
            return self.fout * self.i_ratio / (2.0 * self.q_tank)
        return None


def injection_spur_dbc(dphi_drift: float, beta: float) -> float:
    """Spur at fref offset from the periodic sawtooth phase ripple."""
    ripple_pp = abs(dphi_drift)          # phase jumps by ~dphi_drift each Tref
    b1 = ripple_pp / np.pi               # sawtooth fundamental amplitude
    return float(20.0 * np.log10(max(b1 / 2.0, 1e-30)))


class ILCM(PLLBase):
    def __init__(self, cfg: ILCMConfig):
        self.cfg = cfg

    # ------------------------------------------------------------- analyze
    def analyze(self, f: np.ndarray | None = None,
                f_free_error: float = 0.0) -> AnalysisResult:
        c = self.cfg
        if f is None:
            f = default_grid(1e2, 1e9)
        n = c.n_mult
        b = c.beta
        zinv = np.exp(-2j * np.pi * f / c.fref)
        den = 1.0 - (1.0 - b) * zinv
        # the oscillator enters as per-cycle phase INCREMENTS w[n] (differenced
        # random walk): e(z) = (1-b) w(z)/den, and S_w = |1-z^-1|^2 S_phi,open
        # => phase-PSD NTF = (1-b)(1-z^-1)/den  (highpass, -> (1-b)/b · 2πf/fref)
        h_osc = FreqResponse(f, (1.0 - b) * (1.0 - zinv) / den)
        h_inj = FreqResponse(f, b / den)
        # continuous oscillator beyond fref/2: images not physical
        h_osc_eff = FreqResponse(f, np.where(f < c.fref / 2, h_osc.h, 1.0))

        paths = [
            NoisePath(c.osc.leeson("osc"), h_osc_eff),
            NoisePath(FlickerFloorPhase.from_spot("ref", c.ref_pn_dbchz, c.ref_pn_fc),
                      h_inj * n),
            NoisePath(FlickerFloorPhase(name="inj_jitter", unit="rad^2/Hz",
                                        level=2.0 * (TWOPI * c.fout
                                                     * c.inj_jitter_rms_s) ** 2
                                        / c.fref, fc=0.0),
                      h_inj),
        ]
        bd = output_psd(paths, f)
        jit = rms_jitter_fs(f, bd["total"], c.fout, *c.int_band)

        f_bw = -c.fref * np.log(1.0 - b) / TWOPI
        m = LoopMetrics(f_ugb=f_bw, pm_deg=float("nan"), gm_db=float("inf"),
                        f_3db=f_bw, peaking_db=0.0, n_crossings=1)
        dphi = TWOPI * f_free_error / c.fref
        # the spur IS the residual frequency error; with none given there is
        # nothing to report, and -600 dBc reads as "spurless by design"
        spurs = ({"inj_spur_ref_offset": injection_spur_dbc(dphi, b)}
                 if f_free_error else {})
        notes = [f"lock range |f_free-N·fref| < {c.lock_range_hz() / 1e6:.1f} MHz "
                 f"(realignment bound)"]
        alr = c.adler_lock_range_hz()
        if alr is not None:
            notes.append(f"Adler LC cross-check lock range: {alr / 1e6:.1f} MHz")
        notes.append(f"injection bandwidth ~ {f_bw / 1e6:.2f} MHz (beta={b})")
        return AnalysisResult(f=f, f0=c.fout, pn_breakdown=bd, loop=m,
                              jitter_fs=jit,
                              ipn_dbc=ipn_dbc(f, bd["total"], *c.int_band),
                              int_band=c.int_band, spurs_analytic=spurs,
                              ntfs={"h_osc": h_osc, "h_inj": h_inj}, notes=notes)

    # ------------------------------------------------------------ simulate
    def simulate(self, n_cycles: int, *, noise: bool = True, calibration: bool = True,
                 seed: int = 0, f_free_error: float = 0.0,
                 supply_ripple: tuple[float, float] | None = None,
                 fine_oversample: int = 4) -> SimResult:
        """f_free_error: initial free-running frequency error [Hz].

        fine_oversample=M > 1 additionally records the intra-period phase ramp
        at M points per Tref (analytic within a cycle — no time stepping), so
        the injection spur at fref offset is visible in the spectrum instead
        of aliasing to DC at reference-rate sampling.
        """
        c = self.cfg
        rng = np.random.default_rng(seed)
        tref = 1.0 / c.fref
        v_sup = supply_ripple_v(supply_ripple, n_cycles, tref)
        c.n_mult          # validates the integer multiple; raises if not
        b = c.beta

        osc = Oscillator(c.osc, c.fref, rng, noise=noise)
        ftl = FTL(f_lsb=c.ftl_f_lsb, mu=c.ftl_mu) if (c.ftl and calibration) else None
        from ..calibration.ftl import InjTimingCal
        tcal = InjTimingCal(t_step=c.timing_cal_step_s) \
            if (c.timing_cal and calibration) else None

        jit_ref = (synth_from_psd(
            FlickerFloorPhase.from_spot("ref", c.ref_pn_dbchz, c.ref_pn_fc).psd,
            c.fref, n_cycles, rng) / (TWOPI * c.fref)) if noise else np.zeros(n_cycles)

        osc_noise = osc.noise_steps(n_cycles) if noise else np.zeros(n_cycles)
        prev_on = 0.0

        e = 0.0                       # phase error at injection instants [rad@fout]
        f_corr = 0.0                  # FTL frequency correction [Hz]
        n_slips = 0
        phase_err = np.empty(n_cycles)
        freq_out = np.empty(n_cycles)
        ctrl = np.empty(n_cycles)
        m_os = int(fine_oversample)
        fine = np.empty(n_cycles * m_os) if m_os > 1 else None

        for nn in range(n_cycles):
            d_osc = osc_noise[nn] - prev_on
            prev_on = osc_noise[nn]
            f_free = (c.osc.f0 + f_free_error + f_corr
                      + c.osc.pushing_hz_v * v_sup[nn])
            dphi_drift = TWOPI * (f_free - c.fout) * tref
            e_pre = e + dphi_drift + d_osc          # drifted phase at injection
            if fine is not None:
                # intra-period linear phase ramp from post-injection e to e_pre
                fine[nn * m_os:(nn + 1) * m_os] = \
                    e + (dphi_drift + d_osc) * np.arange(m_os) / m_os
            phi_inj = TWOPI * c.fout * jit_ref[nn]
            if noise and c.inj_jitter_rms_s > 0:
                phi_inj += TWOPI * c.fout * rng.normal(0.0, c.inj_jitter_rms_s)
            # the pulse realigns toward the NEAREST output edge: wrap at +/-pi
            # (this nonlinearity is what limits the lock range to beta*fref/2)
            e_wrap = ((e_pre + np.pi) % TWOPI) - np.pi
            if abs(e_wrap - e_pre) > 1e-9:
                n_slips += 1
            e = (1.0 - b) * e_wrap + b * phi_inj    # realignment

            if ftl is not None:
                # FD observes the pre-injection drift (replica/gated PD) plus
                # its input-referred offset; the FTL nulls the MEASURED drift
                t_off = c.ftl_det_offset_s + (tcal.value if tcal else 0.0)
                drift_obs = (e_pre - e) / b + TWOPI * c.fout * t_off
                f_corr = ftl.step(np.sign(drift_obs))
                if tcal is not None:
                    # second detector: the injection's own phase jump sees the
                    # TRUE drift and bang-bang corrects the offset
                    tcal.step(e_pre - e)
            phase_err[nn] = e
            freq_out[nn] = f_free
            ctrl[nn] = f_corr

        t = np.arange(n_cycles) * tref
        sim = SimResult(fs=c.fref, f0=c.fout, t=t, phase_err_out=phase_err,
                        freq_out=freq_out, ctrl=ctrl, lock_time_s=None)
        sim.extra["slips"] = n_slips
        if ftl is not None:
            sim.cal_traces["ftl_fcorr"] = np.asarray(ftl.trace)
        if tcal is not None:
            sim.cal_traces["inj_timing"] = np.asarray(tcal.trace)
        sim = postprocess(sim, int_band=c.int_band)
        # realignment resets the accumulated phase once per reference period,
        # so ref-rate sampling sees only the residual AT the edge and misses
        # what built up in between
        if fine is not None:
            return attach_fine(sim, fine, m_os, c.fref, c.int_band)
        return no_fine_note(sim)
