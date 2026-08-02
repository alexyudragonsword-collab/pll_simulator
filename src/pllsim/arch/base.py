"""Common architecture contract."""
from __future__ import annotations

import inspect
from abc import ABC, abstractmethod

import numpy as np

from ..core.jitter import ldbc_from_sphi
from ..core.results import AnalysisResult, SimResult


class PLLBase(ABC):
    """analyze() = linear phase-domain model; simulate() = behavioral time domain."""

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
