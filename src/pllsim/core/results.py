"""Structured results consumed by plotting and reports."""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from .freqresp import FreqResponse, LoopMetrics


@dataclass
class AnalysisResult:
    """Frequency-domain (linear phase-domain model) analysis output."""

    f: np.ndarray                                  # offset grid [Hz]
    f0: float                                      # output carrier [Hz]
    pn_breakdown: dict[str, np.ndarray]            # per-source S_phi [rad^2/Hz] + 'total'
    loop: LoopMetrics
    jitter_fs: float                               # RMS jitter over the integration band
    ipn_dbc: float
    int_band: tuple[float, float] = (1e3, 100e6)
    spurs_analytic: dict[str, float] = field(default_factory=dict)   # name -> dBc
    ntfs: dict[str, FreqResponse] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def ipn_shares(self) -> list[tuple[str, float, float]]:
        """Per-source (name, share of integrated phase power, jitter [fs]).

        Sorted worst first.  The shares sum to 1 because the sources are
        uncorrelated and `total` is their sum -- checked to 1e-6 on every
        benchmark preset, which is what lets this be drawn as a pie at all.

        The *share* is of power, not of jitter: a source holding half the
        power contributes 1/sqrt(2) of the total RMS jitter, not half of it,
        which is why the per-source jitter is returned alongside rather than
        left for the reader to divide.
        """
        from .jitter import integrate_pn
        rows = []
        for k, s in self.pn_breakdown.items():
            if k == "total":
                continue
            p = integrate_pn(self.f, s, *self.int_band)
            rows.append((k, p, 1e15 * math.sqrt(p) / (2.0 * math.pi * self.f0)))
        tot = sum(p for _k, p, _j in rows)
        if tot <= 0.0:
            return [(k, 0.0, j) for k, _p, j in rows]
        return sorted(((k, p / tot, j) for k, p, j in rows),
                      key=lambda r: -r[1])

    def dominant_source(self) -> str:
        """Source with the largest contribution to integrated phase power."""
        shares = self.ipn_shares()
        return shares[0][0] if shares else ""


@dataclass
class SimResult:
    """Time-domain simulation output (reference-edge granularity unless noted)."""

    fs: float                                      # sample rate of the sequences [Hz]
    f0: float                                      # output carrier [Hz]
    t: np.ndarray                                  # sample times [s]
    phase_err_out: np.ndarray                      # output-referred phase error [rad]
    freq_out: np.ndarray                           # instantaneous output freq [Hz]
    ctrl: np.ndarray                               # vctrl [V] or OTW [LSB]
    cal_traces: dict[str, np.ndarray] = field(default_factory=dict)
    lock_time_s: float | None = None
    f_psd: np.ndarray | None = None                # cached periodogram (settled portion)
    s_phi_psd: np.ndarray | None = None
    spurs_fft: dict[float, float] = field(default_factory=dict)
    jitter_fs: float | None = None                 # from time-domain PSD if computed
    notes: list[str] = field(default_factory=list)  # caveats about the numbers
    extra: dict = field(default_factory=dict)
