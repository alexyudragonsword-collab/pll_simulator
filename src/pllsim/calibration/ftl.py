"""Frequency acquisition / tracking loops.

FLLStateMachine — SSPLL frequency-locked acquisition aid: a counter-based
frequency detector (VCO cycles per W reference periods, resolution fref/W)
drives a charge path while the SSPD is gated off; hysteretic engage/release
prevents chatter at handoff.

FTL — ILCM frequency-tracking loop: bang-bang (sign of the pre-injection
phase drift) correction of the oscillator free-running frequency with
optional gear-shifted step size.

InjTimingCal — LMS alignment of the injection instant: correlates the
post-injection residual phase with the applied timing offset dither.

Each update rule is a kernel (core.jit) over a small state vector, shared
with the engines' compiled loops; the classes are the object view.
"""
from __future__ import annotations

import math

import numpy as np

from ..core.jit import kernel, sgn

# FLL state vector (float64): state (0 idle / 1 acquiring), count accumulator,
# windows seen, quiet windows, last frequency error
FLL_STATE, FLL_CNT, FLL_W, FLL_QUIET, FLL_FERR = range(5)
FLL_IDLE, FLL_ACQ = 0.0, 1.0


@kernel
def fll_step(st: np.ndarray, cycles_this_ref: float, n_target: float, fref: float,
             window: int, f_engage: float, f_release: float, i_fll: float,
             hyst: int) -> float:
    """Feed the VCO cycle count for this reference period; returns the FLL
    charge [C] for the period."""
    st[FLL_CNT] += cycles_this_ref
    st[FLL_W] += 1.0
    if st[FLL_W] >= window:
        st[FLL_FERR] = (st[FLL_CNT] / st[FLL_W] - n_target) * fref
        st[FLL_CNT] = 0.0
        st[FLL_W] = 0.0
        if st[FLL_STATE] == FLL_ACQ:
            if abs(st[FLL_FERR]) < f_release:
                st[FLL_QUIET] += 1.0
                if st[FLL_QUIET] >= hyst:
                    st[FLL_STATE] = FLL_IDLE
                    st[FLL_QUIET] = 0.0
            else:
                st[FLL_QUIET] = 0.0
        else:
            if abs(st[FLL_FERR]) > f_engage:
                st[FLL_QUIET] += 1.0
                if st[FLL_QUIET] >= hyst:
                    st[FLL_STATE] = FLL_ACQ
                    st[FLL_QUIET] = 0.0
            else:
                st[FLL_QUIET] = 0.0
    if st[FLL_STATE] == FLL_ACQ:
        # bang-bang outside the release band, proportional inside: a hard
        # bang during the hysteresis wait would push the loop back out of
        # the SSPD capture range (limit cycle); zero drive there would
        # hand off sitting at the band edge.  Proportional taper converges
        # ferr toward zero before the SSPD takes over.
        scale = min(max(st[FLL_FERR] / f_release, -1.0), 1.0)
        return -scale * i_fll / fref   # charge per Tref
    return 0.0


class FLLStateMachine:
    IDLE, ACQ = 0, 1

    def __init__(self, n_target: float, fref: float, window: int = 64,
                 f_engage: float = 3e6, f_release: float = 500e3,
                 i_fll: float = 200e-6, hyst_windows: int = 3):
        self.n_target = n_target
        self.fref = fref
        self.window = window
        self.f_engage = f_engage
        self.f_release = f_release
        self.i_fll = i_fll
        self.hyst = hyst_windows
        self.st = np.array([FLL_ACQ, 0.0, 0.0, 0.0, 0.0])
        self.trace: list[int] = []

    @property
    def state(self) -> int:
        return int(self.st[FLL_STATE])

    @property
    def ferr(self) -> float:
        return float(self.st[FLL_FERR])

    def params(self) -> tuple[float, float, int, float, float, float, int]:
        return (float(self.n_target), float(self.fref), int(self.window),
                float(self.f_engage), float(self.f_release), float(self.i_fll),
                int(self.hyst))

    def step(self, cycles_this_ref: float) -> float:
        """Feed VCO cycle count for this ref period; returns FLL charge [C]."""
        dq = float(fll_step(self.st, float(cycles_this_ref), *self.params()))
        self.trace.append(self.state)
        return dq

    @property
    def engaged(self) -> bool:
        return self.state == self.ACQ


# FTL state vector (float64): frequency correction [Hz], step count
FTL_VALUE, FTL_N = range(2)


@kernel
def ftl_step(st: np.ndarray, drift_sign: float, f_lsb: float, mu: float,
             mu_final: float, gear_shift_n: float) -> float:
    """Bang-bang frequency correction; ``mu_final`` NaN / ``gear_shift_n``
    negative mean no gear shift."""
    mu_now = mu
    if gear_shift_n >= 0.0 and not math.isnan(mu_final) and st[FTL_N] > gear_shift_n:
        mu_now = mu_final
    st[FTL_VALUE] -= mu_now * f_lsb * sgn(drift_sign)
    st[FTL_N] += 1.0
    return st[FTL_VALUE]


class FTL:
    """Bang-bang frequency tracking for injection-locked oscillators."""

    def __init__(self, f_lsb: float, mu: float = 1.0,
                 gear_shift_n: int | None = None, mu_final: float | None = None):
        self.f_lsb = f_lsb        # frequency DAC LSB [Hz]
        self.mu = mu
        self.mu_final = mu_final
        self.gear_shift_n = gear_shift_n
        self.st = np.zeros(2)
        self.trace: list[float] = []

    @property
    def value(self) -> float:
        return float(self.st[FTL_VALUE])

    @property
    def n(self) -> int:
        return int(self.st[FTL_N])

    def params(self) -> tuple[float, float, float, float]:
        return (float(self.f_lsb), float(self.mu),
                float("nan") if self.mu_final is None else float(self.mu_final),
                -1.0 if self.gear_shift_n is None else float(self.gear_shift_n))

    def step(self, drift_sign: float) -> float:
        v = float(ftl_step(self.st, float(drift_sign), *self.params()))
        self.trace.append(v)
        return v


@kernel
def inj_timing_step(st: np.ndarray, true_drift_rad: float, t_step: float,
                    mu: float) -> float:
    st[0] += mu * t_step * sgn(true_drift_rad)
    return st[0]


class InjTimingCal:
    """Injection/FTL path offset calibration.

    A detector offset in the FTL path makes the FTL settle with a residual
    frequency drift (the FTL nulls its *measured* drift, not the true one),
    which turns directly into the fref injection spur.  A second observation
    — the phase jump the injection itself causes, e_post - e_pre, measurable
    by sampling the replica PD on both sides of the injection instant — sees
    the TRUE drift and drives a bang-bang correction of the offset.
    """

    def __init__(self, t_step: float, mu: float = 1.0):
        self.t_step = t_step      # correction LSB [s]
        self.mu = mu
        self.st = np.zeros(1)     # timing/offset correction [s]
        self.trace: list[float] = []

    @property
    def value(self) -> float:
        return float(self.st[0])

    def step(self, true_drift_rad: float) -> float:
        """Feed the pre-injection minus post-injection phase (= true drift)."""
        v = float(inj_timing_step(self.st, float(true_drift_rad), float(self.t_step),
                                  float(self.mu)))
        self.trace.append(v)
        return v
