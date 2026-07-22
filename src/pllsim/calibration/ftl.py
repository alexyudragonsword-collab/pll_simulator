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
"""
from __future__ import annotations

import numpy as np


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
        self.state = self.ACQ
        self._cnt_acc = 0.0
        self._w = 0
        self._quiet = 0
        self.ferr = 0.0
        self.trace: list[int] = []

    def step(self, cycles_this_ref: float) -> float:
        """Feed VCO cycle count for this ref period; returns FLL charge [C]."""
        self._cnt_acc += cycles_this_ref
        self._w += 1
        if self._w >= self.window:
            self.ferr = (self._cnt_acc / self._w - self.n_target) * self.fref
            self._cnt_acc = 0.0
            self._w = 0
            if self.state == self.ACQ:
                if abs(self.ferr) < self.f_release:
                    self._quiet += 1
                    if self._quiet >= self.hyst:
                        self.state = self.IDLE
                        self._quiet = 0
                else:
                    self._quiet = 0
            else:
                if abs(self.ferr) > self.f_engage:
                    self._quiet += 1
                    if self._quiet >= self.hyst:
                        self.state = self.ACQ
                        self._quiet = 0
                else:
                    self._quiet = 0
        self.trace.append(self.state)
        if self.state == self.ACQ:
            # bang-bang outside the release band, proportional inside: a hard
            # bang during the hysteresis wait would push the loop back out of
            # the SSPD capture range (limit cycle); zero drive there would
            # hand off sitting at the band edge.  Proportional taper converges
            # ferr toward zero before the SSPD takes over.
            scale = float(np.clip(self.ferr / self.f_release, -1.0, 1.0))
            return -scale * self.i_fll / self.fref   # charge per Tref
        return 0.0

    @property
    def engaged(self) -> bool:
        return self.state == self.ACQ


class FTL:
    """Bang-bang frequency tracking for injection-locked oscillators."""

    def __init__(self, f_lsb: float, mu: float = 1.0,
                 gear_shift_n: int | None = None, mu_final: float | None = None):
        self.f_lsb = f_lsb        # frequency DAC LSB [Hz]
        self.mu = mu
        self.mu_final = mu_final
        self.gear_shift_n = gear_shift_n
        self.value = 0.0          # frequency correction [Hz]
        self.n = 0
        self.trace: list[float] = []

    def step(self, drift_sign: float) -> float:
        mu = self.mu
        if self.gear_shift_n is not None and self.mu_final is not None \
                and self.n > self.gear_shift_n:
            mu = self.mu_final
        self.value -= mu * self.f_lsb * np.sign(drift_sign)
        self.n += 1
        self.trace.append(self.value)
        return self.value


class InjTimingCal:
    """Sign-sign LMS on the injection timing offset."""

    def __init__(self, t_step: float, mu: float = 1.0):
        self.t_step = t_step
        self.mu = mu
        self.value = 0.0          # timing correction [s]
        self.trace: list[float] = []

    def step(self, resid_sign: float, dither_sign: float) -> float:
        self.value -= self.mu * self.t_step * np.sign(resid_sign) * np.sign(dither_sign)
        self.trace.append(self.value)
        return self.value
