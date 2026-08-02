"""Digital lock detector.

What a chip actually reports as LOCK, as opposed to what a plotting script
decides after the fact.  A window comparator on the PFD timing error feeds an
up/down counter: every cycle inside the window counts up, every cycle outside
counts down by ``down_weight`` (asymmetric, so one noisy cycle does not undo a
long run), and LOCK asserts when the counter saturates.  De-assertion needs the
counter to fall back to zero, which gives the hysteresis that keeps the flag
from chattering on noise.

This differs from ``core.engine.detect_lock`` in a way that matters: that
function looks at the FREQUENCY error over the whole record with hindsight,
which is fine for a report but is not available to the chip and says nothing
when a loop is frequency-locked yet phase-slipping.  The detector here sees
only the present cycle's phase error, which is the quantity the silicon has.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class LockDetectConfig:
    window_s: float                 # |dt| inside this counts as "in lock"
    count: int = 64                 # consecutive-ish in-window cycles to assert
    down_weight: int = 4            # penalty per out-of-window cycle


class LockDetector:
    def __init__(self, cfg: LockDetectConfig):
        self.cfg = cfg
        self.acc = 0
        self.locked = False
        self.trace: list[float] = []
        self._n = 0
        self.first_lock_cycle: int | None = None

    def step(self, dt: float) -> bool:
        c = self.cfg
        if abs(dt) <= c.window_s:
            self.acc = min(self.acc + 1, c.count)
        else:
            self.acc = max(self.acc - c.down_weight, 0)
        if self.acc >= c.count:
            if not self.locked:
                self.locked = True
                if self.first_lock_cycle is None:
                    self.first_lock_cycle = self._n
        elif self.acc == 0:
            self.locked = False
        self.trace.append(1.0 if self.locked else 0.0)
        self._n += 1
        return self.locked

    def lock_time_s(self, tref: float) -> float | None:
        """When LOCK first asserted, or None if it never did."""
        if self.first_lock_cycle is None:
            return None
        return float(self.first_lock_cycle * tref)

    @property
    def trace_array(self) -> np.ndarray:
        return np.asarray(self.trace, dtype=float)


@dataclass
class LockStats:
    """What the detector saw over a whole run."""

    lock_time_s: float | None
    lock_fraction: float            # of cycles with LOCK asserted
    n_unlock_events: int            # times LOCK dropped after being asserted

    @staticmethod
    def from_trace(trace: np.ndarray, tref: float,
                   first_cycle: int | None) -> "LockStats":
        tr = np.asarray(trace, dtype=float)
        drops = int(np.sum((tr[:-1] > 0.5) & (tr[1:] < 0.5))) if tr.size > 1 else 0
        return LockStats(
            lock_time_s=None if first_cycle is None else float(first_cycle * tref),
            lock_fraction=float(tr.mean()) if tr.size else 0.0,
            n_unlock_events=drops)
