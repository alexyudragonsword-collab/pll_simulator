"""Channel-hop settling analysis: frequency pull-in and phase settling.

A channel hop is simulated as acquisition from the previous channel's
operating point: `f_start_offset = f_from - fout` presets the loop state
(control voltage / OTW) exactly where the old channel left it — the same
continuity a real retune has.  Two settling instants are extracted from
the trajectory:

  t_freq  — LAST time |f - fout| exceeds f_tol (frequency pull-in done;
            for FLL-assisted loops this is dominated by the FLL segment)
  t_phase — LAST time |phi - phi_final| exceeds phase_tol_rad (the phase
            transient has decayed; this is what a TX/RX actually waits for)

Both are "last excursion" detectors, immune to overshoot ringing fooling
a first-crossing test.  hop_statistics() runs a seed population for the
distribution — settling time is a yield quantity, not a single number
(noise, initial DSM/DTC state and the FLL hand-off all move it).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .arch.base import start_offset_kwarg
from .core.results import SimResult


@dataclass
class HopResult:
    f_from: float
    f_to: float
    t_freq_s: float
    t_phase_s: float
    fll_engaged_s: float | None      # time spent with the FLL engaged
    jitter_fs: float | None          # post-settling jitter (settled tail)
    f_tol_eff: float = 0.0           # tolerance actually used (noise floor)
    sim: SimResult | None = field(repr=False, default=None)


def _last_excursion(t: np.ndarray, x: np.ndarray, tol: float) -> float:
    bad = np.nonzero(np.abs(x) > tol)[0]
    if bad.size == 0:
        return 0.0
    if bad[-1] >= x.size - 2:
        return float("inf")               # never settles inside the window
    return float(t[bad[-1] + 1])


def hop_settling(pll, f_from: float, *, n_cycles: int = 200_000,
                 f_tol: float | None = None, phase_tol_rad: float = 0.05,
                 seed: int = 0, **sim_kwargs) -> HopResult:
    """Settle onto pll.cfg.fout starting from channel f_from."""
    c = pll.cfg
    if f_tol is None:
        f_tol = 1e-6 * c.fout                 # 1 ppm
    start = start_offset_kwarg(pll)
    if start is None:
        raise TypeError(f"{type(pll).__name__}.simulate() cannot start off "
                        "channel, so there is no hop to settle")
    sim = pll.simulate(n_cycles, seed=seed,
                       **{start: f_from - c.fout}, **sim_kwargs)
    t = sim.t
    # frequency judged like a counter would: moving average over w cycles
    # (instantaneous per-cycle frequency carries noise above ppm tols)
    w = min(256, max(8, n_cycles // 100))
    f_avg = np.convolve(sim.freq_out, np.ones(w) / w, mode="same")
    f_avg[:w] = f_avg[w]                      # edge guard
    f_avg[-w:] = f_avg[-w - 1]
    # the loop's own settled frequency wander floors the resolvable tol:
    # below ~8 sigma of the tail the detector reads noise, not settling
    sig_tail = float(np.std(f_avg[int(0.9 * n_cycles):]))
    f_tol_eff = max(f_tol, 8.0 * sig_tail)
    t_freq = _last_excursion(t, f_avg - c.fout, f_tol_eff)

    n0 = int(0.9 * t.size)                    # phase reference: settled tail
    phi_final = float(np.mean(sim.phase_err_out[n0:]))
    t_phase = _last_excursion(t, sim.phase_err_out - phi_final,
                              phase_tol_rad)

    fll_t = None
    if "fll_engaged" in sim.cal_traces:
        fll_t = float(sim.cal_traces["fll_engaged"].sum() / c.fref)
    return HopResult(f_from=f_from, f_to=c.fout, t_freq_s=t_freq,
                     t_phase_s=t_phase, fll_engaged_s=fll_t,
                     jitter_fs=sim.jitter_fs, f_tol_eff=f_tol_eff, sim=sim)


def fll_stability(pll) -> dict:
    """Bang-bang FLL hand-off criterion for the sampling loops.

    The FLL measures once per `window` reference cycles and bangs i_fll in
    between, so the frequency moves by

        slew_per_window = Kvco * i_fll * window / (fref * C1)

    per decision.  With the one-window measurement latency the limit-cycle
    amplitude is ~2x that; if it exceeds f_release the FLL oscillates
    around zero without ever dwelling inside the release band — it NEVER
    hands off to the phase detector, no matter how long you wait:

        i_fll < f_release * fref * C1 / (2 * Kvco * window)

    Returns the slew, the bound and the margin (>1 = stable hand-off).
    """
    c = pll.cfg
    # only the two sampling loops hand off from a current-mode FLL; asking any
    # other architecture used to surface as an AttributeError on cfg.fll_i
    missing = [a for a in ("fll_i", "fll_window", "fll_release", "filt")
               if not hasattr(c, a)]
    if missing:
        raise TypeError(
            f"{type(pll).__name__} has no FLL hand-off to check: this bound is "
            "about a bang-bang FLL charging the loop filter, and that "
            "architecture has no such stage")
    slew = c.osc.gain * c.fll_i * c.fll_window / (c.fref * c.filt.c1)
    i_max = c.fll_release * c.fref * c.filt.c1 / (2.0 * c.osc.gain
                                                  * c.fll_window)
    return {"slew_per_window_hz": float(slew), "i_fll_max_a": float(i_max),
            "margin": float(i_max / c.fll_i)}


def hop_statistics(make_pll, f_from: float, seeds=range(20),
                   **kwargs) -> dict:
    """Settling-time distribution over a seed population.

    make_pll: factory returning a FRESH instance per run (calibrators
    carry state).  Returns arrays plus percentiles of t_phase.
    """
    freq_s, phase_s = [], []
    for s in seeds:
        r = hop_settling(make_pll(), f_from, seed=s, **kwargs)
        freq_s.append(r.t_freq_s)
        phase_s.append(r.t_phase_s)
    tf, tp = np.asarray(freq_s), np.asarray(phase_s)
    ok = np.isfinite(tp)
    return {"t_freq_s": tf, "t_phase_s": tp,
            "p50_s": float(np.percentile(tp[ok], 50)) if ok.any() else
            float("inf"),
            "p95_s": float(np.percentile(tp[ok], 95)) if ok.any() else
            float("inf"),
            "worst_s": float(np.max(tp[ok])) if ok.any() else float("inf"),
            "fail_frac": float(1.0 - ok.mean())}
