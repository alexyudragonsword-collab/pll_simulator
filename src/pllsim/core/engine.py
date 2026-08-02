"""Reference-edge-driven simulation engine.

Architectures implement step(n) -> dict of recorded signals; the engine owns
the RNG, the main loop, warmup/settle bookkeeping and post-processing of the
recorded phase sequence into a PSD + spur table.
"""
from __future__ import annotations

import numpy as np

from .jitter import rms_jitter_fs
from .results import SimResult
from .spectrum import periodogram_psd, phase_psd


def detect_lock(t: np.ndarray, ferr: np.ndarray, tol_hz: float, hold: int = 200) -> float | None:
    """First time |ferr| < tol for `hold` consecutive samples."""
    ok = np.abs(ferr) < tol_hz
    if ok.size < hold:
        return None
    run = 0
    for i, v in enumerate(ok):
        run = run + 1 if v else 0
        if run >= hold:
            return float(t[i - hold + 1])
    return None


def postprocess(sim: SimResult, settle_frac: float = 0.25,
                int_band: tuple[float, float] = (1e3, 100e6),
                spur_offsets=None) -> SimResult:
    """Attach PSD, jitter and spur estimates from the settled portion."""
    n0 = int(sim.phase_err_out.size * settle_frac)
    ph = sim.phase_err_out[n0:]
    # A background calibration can still be converging well past settle_frac --
    # a DTC gain LMS that gear-shifts at 100k cycles leaves a fractional spur
    # that dominates everything before it.  The jitter number is then real but
    # answers a different question, so say so rather than let it read as the
    # locked performance.
    half = ph.size // 2
    if half >= 1024:
        early, late = float(np.std(ph[:half])), float(np.std(ph[half:]))
        if early > 1.3 * max(late, 1e-30):
            sim.notes.append(
                f"still settling: phase error is {early / late:.1f}x larger in "
                "the first half of the analysed window than the second — the "
                "jitter below includes an acquisition/calibration transient. "
                "Run more cycles.")
    if ph.size >= 2048:
        f_w, s_w = phase_psd(ph, sim.fs)
        sim.f_psd, sim.s_phi_psd = f_w, s_w
        f1 = max(int_band[0], f_w[0])
        f2 = min(int_band[1], sim.fs / 2 * 0.9)
        sim.jitter_fs = rms_jitter_fs(f_w, s_w, sim.f0, f1, f2)
        if spur_offsets is not None:
            from .spectrum import find_spurs
            f_p, s_p = periodogram_psd(ph, sim.fs)
            sim.spurs_fft = find_spurs(f_p, s_p, spur_offsets)
    return sim
