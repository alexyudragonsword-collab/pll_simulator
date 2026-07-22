"""Sampling phase detector front-end (SSPLL / SPLL)."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

KB = 1.380649e-23
T0 = 290.0


@dataclass
class SamplerConfig:
    amp_v: float = 0.4            # sampled waveform amplitude at the PD [V]
    c_samp: float = 50e-15        # sampling capacitor [F]
    gm: float = 2e-3              # pulser/gm stage transconductance [A/V]
    pulse_width: float = 500e-12  # gm-on pulse width per ref cycle [s]
    pedestal_v: float = 1e-3      # static sampling pedestal (ref spur source)
    gm_noise_a2hz: float | None = None
    temp_k: float = T0

    @property
    def ktc_sigma_v(self) -> float:
        return float(np.sqrt(KB * self.temp_k / self.c_samp))

    def gm_i2(self) -> float:
        if self.gm_noise_a2hz is not None:
            return self.gm_noise_a2hz
        return 4.0 * KB * self.temp_k * (2.0 / 3.0) * 2.0 * self.gm


class SamplingPD:
    """Sample-and-slope PD: v = A*sin(phase_err) + kT/C noise, then a gm pulse
    converts the held voltage to charge: dq = gm * v * tau."""

    def __init__(self, cfg: SamplerConfig, tref: float, rng: np.random.Generator,
                 noise: bool = True):
        self.cfg = cfg
        self.tref = tref
        self.rng = rng
        self.noise_on = noise
        self._i2 = cfg.gm_i2()

    def sample(self, phase_err_rad: float) -> float:
        v = self.cfg.amp_v * np.sin(phase_err_rad) + self.cfg.pedestal_v
        if self.noise_on:
            v += self.rng.normal(0.0, self.cfg.ktc_sigma_v)
        return v

    def charge(self, v_held: float) -> float:
        dq = self.cfg.gm * v_held * self.cfg.pulse_width
        if self.noise_on:
            dq += self.rng.normal(0.0, np.sqrt(self._i2 * self.cfg.pulse_width))
        return dq
