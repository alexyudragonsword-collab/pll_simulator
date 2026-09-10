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

The counter is a kernel (core.jit) over an int64 state vector, shared with
the CPPLL's compiled loop; the class is the object view.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..core.jit import kernel


@dataclass
class LockDetectConfig:
    window_s: float                 # |dt| inside this counts as "in lock"
    count: int = 64                 # consecutive-ish in-window cycles to assert
    down_weight: int = 4            # penalty per out-of-window cycle

    def __post_init__(self):
        if not self.window_s > 0:
            raise ValueError(f"LockDetectConfig window_s must be positive, got {self.window_s}")
        if int(self.count) < 1:
            raise ValueError(f"LockDetectConfig count must be >= 1, got {self.count}")
        if self.down_weight < 0:
            raise ValueError(f"LockDetectConfig down_weight cannot be negative, got {self.down_weight}")


# state vector (int64): counter, LOCK flag, cycles seen, first lock cycle (-1
# = never)
LD_ACC, LD_LOCKED, LD_N, LD_FIRST = range(4)


@kernel
def lockdet_step(st: np.ndarray, dt: float, window_s: float, count: int,
                 down_weight: int) -> bool:
    if abs(dt) <= window_s:
        st[LD_ACC] = min(st[LD_ACC] + 1, count)
    else:
        st[LD_ACC] = max(st[LD_ACC] - down_weight, 0)
    if st[LD_ACC] >= count:
        if st[LD_LOCKED] == 0:
            st[LD_LOCKED] = 1
            if st[LD_FIRST] < 0:
                st[LD_FIRST] = st[LD_N]
    elif st[LD_ACC] == 0:
        st[LD_LOCKED] = 0
    st[LD_N] += 1
    return st[LD_LOCKED] != 0


def new_lockdet_state() -> np.ndarray:
    return np.array([0, 0, 0, -1], dtype=np.int64)


class LockDetector:
    def __init__(self, cfg: LockDetectConfig):
        self.cfg = cfg
        self.st = new_lockdet_state()
        self.trace: list[float] = []

    @property
    def acc(self) -> int:
        return int(self.st[LD_ACC])

    @property
    def locked(self) -> bool:
        return bool(self.st[LD_LOCKED] != 0)

    @property
    def first_lock_cycle(self) -> int | None:
        return None if self.st[LD_FIRST] < 0 else int(self.st[LD_FIRST])

    def step(self, dt: float) -> bool:
        c = self.cfg
        locked = bool(lockdet_step(self.st, float(dt), float(c.window_s),
                                   int(c.count), int(c.down_weight)))
        self.trace.append(1.0 if locked else 0.0)
        return locked

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
                   first_cycle: int | None) -> LockStats:
        tr = np.asarray(trace, dtype=float)
        drops = int(np.sum((tr[:-1] > 0.5) & (tr[1:] < 0.5))) if tr.size > 1 else 0
        return LockStats(
            lock_time_s=None if first_cycle is None else float(first_cycle * tref),
            lock_fraction=float(tr.mean()) if tr.size else 0.0,
            n_unlock_events=drops)
