"""Time-to-digital converter models: flash TDC and bang-bang PD."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class TDCConfig:
    t_res: float                  # LSB [s]
    n_bits: int = 7               # range = 2^bits * t_res (should cover ~1 Tdco)
    inl_sin: tuple = ()           # (amp_s, cycles, phase) over the code range
    jitter_rms_s: float = 0.0     # input-referred random jitter
    gain_error: float = 0.0       # true LSB = t_res*(1+gain_error), unknown to loop


class TDC:
    """Flash TDC measuring a time interval in [0, range)."""

    def __init__(self, cfg: TDCConfig, rng: np.random.Generator, noise: bool = True):
        self.cfg = cfg
        self.rng = rng
        self.noise_on = noise
        self.code_max = (1 << cfg.n_bits) - 1
        self.t_lsb_true = cfg.t_res * (1.0 + cfg.gain_error)

    def measure(self, dt: float) -> int:
        """Quantize dt >= 0 to a code with the *true* (unknown) LSB + INL."""
        if self.noise_on and self.cfg.jitter_rms_s > 0:
            dt = dt + self.rng.normal(0.0, self.cfg.jitter_rms_s)
        code = int(dt / self.t_lsb_true)
        if self.cfg.inl_sin:
            amp, cyc, ph = self.cfg.inl_sin
            x = min(code, self.code_max) / self.code_max
            dt_inl = amp * np.sin(2 * np.pi * cyc * x + ph)
            code = int((dt + dt_inl) / self.t_lsb_true)
        return min(max(code, 0), self.code_max)


class BBPD:
    """Bang-bang phase detector: sign of the timing error plus jitter.

    ``meta_window_s`` is the resolution window of the sampling flop.  Inside it
    the flop cannot resolve in the time available, so the decision is a coin
    flip -- it still puts out +/-1, just not the right one.  That is a gain
    loss, not a noise gain: the output power stays at 1 either way, while the
    slope of the averaged characteristic drops (see meta_gain_penalty).
    """

    def __init__(self, jitter_rms_s: float, rng: np.random.Generator,
                 noise: bool = True, meta_window_s: float = 0.0):
        self.jitter = jitter_rms_s
        self.rng = rng
        self.noise_on = noise
        self.meta_window_s = meta_window_s
        self.n_meta = 0

    def sample(self, dt: float) -> int:
        if self.noise_on and self.jitter > 0:
            dt = dt + self.rng.normal(0.0, self.jitter)
        if self.meta_window_s > 0 and abs(dt) < self.meta_window_s:
            self.n_meta += 1
            if self.noise_on:
                return 1 if self.rng.random() < 0.5 else -1
        return 1 if dt >= 0 else -1


def meta_gain_penalty(meta_window_s: float, sigma_t: float) -> float:
    """Factor on Kbb from a metastability window, in (0, 1].

    With input jitter sigma and a coin-flip window +/-W, the averaged
    characteristic is E[out|dt] = Q((W-dt)/sigma) - Q((W+dt)/sigma), whose
    slope at the origin is 2*phi(W/sigma)/sigma.  Dividing by the W=0 value
    sqrt(2/pi)/sigma leaves

        Kbb(W)/Kbb(0) = exp(-W^2 / (2 sigma^2)) .

    The output power is unchanged (a coin flip is still +/-1), so the whole
    effect lands on the gain: input-referred noise rises by exactly the
    reciprocal.  A window equal to sigma costs 4.34 dB.
    """
    if meta_window_s <= 0.0 or sigma_t <= 0.0:
        return 1.0
    return float(np.exp(-0.5 * (meta_window_s / sigma_t) ** 2))
