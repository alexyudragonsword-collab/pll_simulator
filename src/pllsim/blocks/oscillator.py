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
    # ---- second-order effects (all default off) ----
    nl1: float = 0.0              # Kvco nonlinearity: f = f0 + gain·v·(1+nl1·v+nl2·v²)
    nl2: float = 0.0
    pushing_hz_v: float = 0.0     # supply pushing [Hz per volt of supply ripple]
    band_step_hz: float = 0.0     # coarse-tuning band pitch (0 = single band)
    n_bands: int = 1              # number of coarse bands, centered on f0
    # ---- control-voltage range ----
    # None = unlimited, which is what every existing configuration gets and what
    # the loop assumed implicitly.  An unlimited varactor is why a coarse band
    # bank could be configured and still have nothing to do: one band reached any
    # frequency, so a band search always succeeded on the band it started in.
    # A real varactor is limited by the supply, and that limit is the whole reason
    # the capacitor bank exists.
    v_min: float | None = None
    v_max: float | None = None

    def leeson(self, name: str = "vco") -> LeesonOscillator:
        return LeesonOscillator.from_spot(name, self.pn_dbchz, self.pn_foffset,
                                          f_1f3=self.pn_f1f3,
                                          floor_dbchz=self.pn_floor_dbchz)

    def clamp_v(self, v: float) -> float:
        """Control voltage as the varactor actually sees it."""
        if self.v_min is not None:
            v = max(v, self.v_min)
        if self.v_max is not None:
            v = min(v, self.v_max)
        return v

    @property
    def v_limited(self) -> bool:
        return self.v_min is not None or self.v_max is not None

    def band_center_hz(self, band: int) -> float:
        """Free-running frequency of a coarse band."""
        if self.n_bands <= 1:
            return self.f0
        return self.f0 + (band - (self.n_bands - 1) / 2.0) * self.band_step_hz

    def band_range_hz(self, band: int) -> tuple[float, float]:
        """Frequencies a band can reach, given the control-voltage range.

        Unbounded when no range is set, which is the honest answer: with an
        unlimited varactor every band reaches every frequency.
        """
        if not self.v_limited:
            return (-np.inf, np.inf)
        lo = self.freq_law(self.v_min, band)
        hi = self.freq_law(self.v_max, band)
        return (min(lo, hi), max(lo, hi))

    def band_covers(self, f_target: float, band: int) -> bool:
        """Whether a band can be tuned to a frequency without railing."""
        lo, hi = self.band_range_hz(band)
        return bool(lo <= f_target <= hi)

    def band_overlap_hz(self) -> float:
        """How far adjacent bands overlap [Hz].  Negative means a **gap**.

        The sizing rule for a coarse bank, and it is easy to get wrong in a way
        that shows up only as a frequency the loop cannot reach: a band spans
        roughly ``2 * gain * v_max`` and the bank steps by ``band_step_hz``, so
        the bank is only continuous when the span exceeds the step.  A bank with
        150 MHz of pitch and 60 MHz of span leaves 90 MHz holes, and a target in
        one of them rails whichever band the search picks -- which reads as a
        broken loop rather than as a mis-sized oscillator.
        """
        if self.n_bands <= 1 or not self.v_limited:
            return float("inf")
        lo, hi = self.band_range_hz(0)
        return float((hi - lo) - self.band_step_hz)

    def band_bank_is_continuous(self) -> bool:
        """Whether every frequency in the bank's range is reachable."""
        return self.band_overlap_hz() > 0.0

    def bank_range_hz(self) -> tuple[float, float]:
        """Frequencies the whole bank can reach, lowest band to highest."""
        if self.n_bands <= 1:
            return self.band_range_hz(0)
        lo = self.band_range_hz(0)[0]
        hi = self.band_range_hz(self.n_bands - 1)[1]
        return (lo, hi)

    def freq_law(self, v: float, band: int = 0) -> float:
        """f(v, band) including Kvco nonlinearity and coarse band offset.

        The control voltage is clamped to ``[v_min, v_max]`` when a range is set,
        so a band that cannot reach the target rails instead of pretending to.
        """
        v = self.clamp_v(v)
        f_band = self.band_center_hz(band)
        return f_band + self.gain * v * (1.0 + self.nl1 * v + self.nl2 * v * v)

    def kvco_at(self, v: float) -> float:
        """Local small-signal gain df/dv at operating point v."""
        return self.gain * (1.0 + 2.0 * self.nl1 * v + 3.0 * self.nl2 * v * v)

    def v_for(self, f_target: float, band: int | None = None) -> float:
        """Control voltage solving freq_law(v, band) = f_target (real root
        nearest the linear estimate).

        Not clamped: this is the voltage the target *would* need, so a caller can
        see that it is out of range rather than being handed a railed one.
        """
        if band is None:
            band = (self.n_bands - 1) // 2 if self.n_bands > 1 else 0
        f_band = self.band_center_hz(band)
        target = (f_target - f_band) / self.gain
        if self.nl1 == 0.0 and self.nl2 == 0.0:
            return target
        roots = np.roots([self.nl2, self.nl1, 1.0, -target])
        real = roots[np.abs(roots.imag) < 1e-9].real
        if real.size == 0:
            return target
        return float(real[np.argmin(np.abs(real - target))])


class Oscillator:
    def __init__(self, cfg: OscConfig, fs: float, rng: np.random.Generator,
                 noise: bool = True, name: str = "vco"):
        self.cfg = cfg
        self.noise_on = noise
        self.gen = OscPhaseNoiseGen(cfg.leeson(name), fs, rng) if noise else None
        self.phi_acc_noise = 0.0     # accumulated (random-walk) phase noise [rad]
        self.band = (cfg.n_bands - 1) // 2 if cfg.n_bands > 1 else 0

    def freq(self, ctrl: float, v_supply: float = 0.0) -> float:
        f = self.cfg.freq_law(ctrl, self.band)
        if self.cfg.pushing_hz_v != 0.0:
            f += self.cfg.pushing_hz_v * v_supply
        return f

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
