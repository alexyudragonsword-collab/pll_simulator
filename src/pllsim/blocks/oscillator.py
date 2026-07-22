"""Behavioral controlled oscillator (VCO/DCO).

Frequency law plus a Leeson noise profile.  Time-domain sims run at reference
rate; the per-step OscPhaseNoiseGen sample represents the oscillator phase
error accumulated over that interval.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..core.colored import OscPhaseNoiseGen
from ..core.noise import LeesonOscillator


@dataclass
class OscConfig:
    f0: float                     # free-running / center frequency [Hz]
    gain: float                   # Kvco [Hz/V] or Kdco [Hz/LSB]
    pn_dbchz: float = -110.0      # spot phase noise on the 1/f^2 asymptote
    pn_foffset: float = 1e6       # offset of the spot [Hz]
    pn_f1f3: float = 2e5          # 1/f^3 corner [Hz]
    pn_floor_dbchz: float = -150.0

    def leeson(self, name: str = "vco") -> LeesonOscillator:
        return LeesonOscillator.from_spot(name, self.pn_dbchz, self.pn_foffset,
                                          f_1f3=self.pn_f1f3,
                                          floor_dbchz=self.pn_floor_dbchz)


class Oscillator:
    def __init__(self, cfg: OscConfig, fs: float, rng: np.random.Generator,
                 noise: bool = True, name: str = "vco"):
        self.cfg = cfg
        self.noise_on = noise
        self.gen = OscPhaseNoiseGen(cfg.leeson(name), fs, rng) if noise else None
        self.phi_acc_noise = 0.0     # accumulated (random-walk) phase noise [rad]

    def freq(self, ctrl: float) -> float:
        return self.cfg.f0 + self.cfg.gain * ctrl

    def noise_step(self) -> float:
        """Total oscillator phase-noise sample for this step [rad]."""
        if not self.noise_on:
            return 0.0
        d, add = self.gen.step()
        self.phi_acc_noise += d
        return self.phi_acc_noise + add

    def noise_steps(self, n: int) -> np.ndarray:
        if not self.noise_on:
            return np.zeros(n)
        d, add = self.gen.steps(n)
        walk = self.phi_acc_noise + np.cumsum(d)
        self.phi_acc_noise = float(walk[-1])
        return walk + add
