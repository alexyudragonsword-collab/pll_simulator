"""Common architecture contract."""
from __future__ import annotations

import inspect
from abc import ABC, abstractmethod
from typing import Any

import numpy as np

from ..core.jitter import ldbc_from_sphi
from ..core.results import AnalysisResult, SimResult


class PLLBase(ABC):
    """analyze() = linear phase-domain model; simulate() = behavioral time domain.

    Every engine is constructed from a config dataclass and keeps it on `cfg`,
    and the whole library relies on that -- corners, Monte Carlo, the GUIs and
    the selector all reach for `pll.cfg`.  Declaring it here makes the contract
    part of the base class instead of a convention six subclasses happen to
    share; the type is deliberately loose because each engine has its own
    config type and they have no common base.
    """

    cfg: Any

    @abstractmethod
    def analyze(self, f: np.ndarray | None = None) -> AnalysisResult: ...

    @abstractmethod
    def simulate(self, n_cycles: int, *, noise: bool = True,
                 calibration: bool = True, seed: int = 0) -> SimResult: ...

    def design_report(self, ar: AnalysisResult | None = None) -> str:
        ar = ar or self.analyze()
        lines = [
            f"=== {type(self).__name__} design report ===",
            f"fout = {ar.f0 / 1e9:.6f} GHz",
            f"UGB = {ar.loop.f_ugb / 1e6:.3f} MHz   PM = {ar.loop.pm_deg:.1f} deg   "
            f"GM = {ar.loop.gm_db:.1f} dB",
            f"closed-loop f-3dB = {ar.loop.f_3db / 1e6:.3f} MHz   "
            f"peaking = {ar.loop.peaking_db:.2f} dB",
            f"RMS jitter ({ar.int_band[0]:.0f} Hz - {ar.int_band[1] / 1e6:.0f} MHz) "
            f"= {ar.jitter_fs:.1f} fs   IPN = {ar.ipn_dbc:.1f} dBc",
            f"dominant noise source: {ar.dominant_source()}",
        ]
        i = np.searchsorted(ar.f, 1e6)
        if i < ar.f.size:
            lines.append(f"L(1 MHz) total = {ldbc_from_sphi(ar.pn_breakdown['total'][i]):.1f} dBc/Hz")
        for k, v in ar.spurs_analytic.items():
            lines.append(f"spur[{k}] = {v:.1f} dBc (analytic)")
        for note in ar.notes:
            lines.append(f"note: {note}")
        return "\n".join(lines)


def start_offset_kwarg(pll) -> str | None:
    """The simulate() keyword that starts this architecture's oscillator off-target.

    ILCM and MDLL call it ``f_free_error``: their oscillator runs free and the
    FTL corrects it, so nothing "starts" off-target the way a locked loop does.
    The other architectures call the same quantity ``f_start_offset``.  Anything
    that hops a channel or sweeps a starting error has to ask, rather than
    assume one name and fail at the call.  None means the engine has no such
    knob at all.
    """
    params = inspect.signature(type(pll).simulate).parameters
    for name in ("f_start_offset", "f_free_error"):
        if name in params:
            return name
    return None


def supply_ripple_v(ripple, n_cycles: int, tref: float):
    """Per-cycle supply deviation [V] from a (amplitude_v, freq_hz) sine.

    Shared so that every engine spells supply pushing the same way: the knob
    lives on the common OscConfig (pushing_hz_v), and for a long time only the
    CPPLL actually read it, which made it a decoration on five architectures.
    """
    if ripple is None:
        return np.zeros(n_cycles)
    amp, f_sup = ripple
    return amp * np.sin(2.0 * np.pi * f_sup * np.arange(n_cycles) * tref)


def pull_hz(osc_cfg, n_cycles: int, tref: float) -> np.ndarray:
    """Per-cycle oscillator frequency perturbation from an aggressor [Hz].

    Shared for the same reason supply_ripple_v is: the knob lives on the common
    OscConfig, so every engine has to read it or it is a decoration.  Pulling
    is coupling into the tank, not into the loop, so it applies to all six
    architectures -- including the injection-locked ones, where the same
    realignment that highpasses oscillator noise also suppresses this.
    """
    if not getattr(osc_cfg, "pulled", False):
        return np.zeros(n_cycles)
    t = np.arange(n_cycles) * tref
    return osc_cfg.pull_lock_range_hz * np.sin(
        2.0 * np.pi * osc_cfg.pull_offset_hz * t)


def add_pull_offset(offsets, osc_cfg, fref: float):
    """Add the pulling beat to a spur-offset list when it is observable.

    Above fref/2 a reference-rate record cannot resolve it -- that offset is
    left out rather than reported at its alias, which would be a wrong number
    rather than a missing one.
    """
    if getattr(osc_cfg, "pulled", False) and osc_cfg.pull_offset_hz < 0.45 * fref:
        return (list(offsets) if offsets else []) + [osc_cfg.pull_offset_hz]
    return offsets


def pull_spur(osc_cfg, err_fr=None) -> dict[str, float]:
    """{"pull_spur": dBc} for an aggressor, after the loop's rejection.

    Empty when nothing is configured -- an absent aggressor is an absent key,
    not a number.  Also empty (with the caller warned separately) when the
    aggressor is inside the lock range, where the oscillator is captured and
    the weak-pulling expression does not describe anything.
    """
    if not getattr(osc_cfg, "pulled", False) or osc_cfg.within_lock_range():
        return {}
    gain = 1.0
    if err_fr is not None:
        gain = float(np.interp(osc_cfg.pull_offset_hz, err_fr.f,
                               np.abs(err_fr.h)))
    return {"pull_spur": osc_cfg.pull_spur_dbc(gain)}


def pull_notes(osc_cfg) -> list[str]:
    if not getattr(osc_cfg, "pulled", False):
        return []
    if osc_cfg.within_lock_range():
        return [f"aggressor is {osc_cfg.pull_offset_hz / 1e6:.2f} MHz away but "
                f"the lock range is {osc_cfg.pull_lock_range_hz / 1e6:.2f} MHz: "
                "the oscillator is CAPTURED, not pulled — no sideband is "
                "reported because the loop no longer owns the frequency"]
    return [f"injection pulling: f_L={osc_cfg.pull_lock_range_hz / 1e6:.2f} MHz "
            f"aggressor at {osc_cfg.pull_offset_hz / 1e6:.2f} MHz offset "
            "(coupling into the tank — the loop filter cannot fix it)"]


def attach_fine(sim: SimResult, fine: np.ndarray, m_os: int, fref: float,
                int_band: tuple[float, float], offsets=None) -> SimResult:
    """Re-derive the spur table and jitter from an oversampled phase record.

    A record sampled once per reference edge cannot show anything at fref: the
    reference spur sits exactly at that record's sampling rate, so it aliases
    to DC and reads as spurless.  Every engine that wants its reference spur to
    be observable has to keep an intra-period phase trace, and every one of
    them then post-processes it identically — hence this.

    ``jitter_fs`` is replaced, because the oversampled record is the honest one:
    it contains the intra-period ripple that the reference-rate record drops.
    """
    from ..core.jitter import rms_jitter_fs
    from ..core.spectrum import find_spurs, periodogram_psd
    fs_fine = m_os * fref
    n0 = fine.size // 4
    f_p, s_p = periodogram_psd(fine[n0:], fs_fine)
    sim.extra["fine_fs"] = fs_fine
    sim.extra["fine_f"], sim.extra["fine_psd"] = f_p, s_p
    want = [fref, 2.0 * fref] + list(offsets or [])
    sim.spurs_fft.update(find_spurs(f_p, s_p, [o for o in want
                                               if 0 < o < 0.45 * fs_fine]))
    sim.jitter_fs = rms_jitter_fs(f_p, s_p, sim.f0,
                                  max(int_band[0], f_p[0]),
                                  min(int_band[1], 0.45 * fs_fine))
    sim.notes.append(f"jitter integrated on the {m_os}x oversampled phase "
                     "(includes intra-period ripple)")
    return sim


def no_fine_note(sim: SimResult) -> SimResult:
    """Say plainly that the reference spur is not in this record."""
    sim.notes.append("jitter integrated at the reference rate: intra-period "
                     "ripple is NOT included and the reference spur aliases "
                     "to DC — pass fine_oversample>1 to capture both")
    return sim


def run_band_select(osc, cfg, rng, noise: bool, enabled: bool = True):
    """Binary coarse-band search before the loop closes.

    Returns the trace, or None when the bank is a single band or the caller
    disabled it.  Lives here because the search is identical for every
    architecture whose oscillator has a control voltage — it was CPPLL-only
    for a while, which made n_bands a decoration on the other analog loops
    while `export` happily emitted a band-search FSM for them.
    """
    if cfg.osc.n_bands <= 1 or not enabled:
        return None
    from ..calibration.gain_cal import BandSelect
    bs = BandSelect(cfg.osc.n_bands, cfg.fout)
    while not bs.done:
        osc.band = bs.band
        f_meas = osc.freq(0.0)
        if noise:      # counter accuracy over meas_n reference cycles
            f_meas += rng.normal(0.0, cfg.fref / (bs.meas_n * np.sqrt(12)))
        bs.observe(f_meas)
    osc.band = bs.band
    return np.asarray(bs.trace, dtype=float)
