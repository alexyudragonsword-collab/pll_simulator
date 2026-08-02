"""Charge pump with mismatch, leakage and noise."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..core.colored import synth_from_psd
from ..core.noise import CurrentNoise


@dataclass
class CPConfig:
    icp: float                    # nominal current [A]
    mismatch_pct: float = 0.0     # (Iup - Idn)/Icp * 100
    leakage_a: float = 0.0        # static leakage on the control node [A]
    t_reset: float = 1e-9         # PFD reset (anti-backlash) pulse width [s]
    noise_a2hz: float | None = None   # thermal current noise when ON [A^2/Hz]
    flicker_corner: float = 100e3

    def default_noise(self) -> float:
        """4kT*gamma*2*gm rough default: scale with Icp (gm ~ Icp/(V*)) ."""
        if self.noise_a2hz is not None:
            return self.noise_a2hz
        gm = self.icp / 0.15      # V* = 150 mV overdrive-ish
        return 4 * 1.380649e-23 * 290.0 * (2.0 / 3.0) * 2.0 * gm


class ChargePump:
    def __init__(self, cfg: CPConfig, tref: float, rng: np.random.Generator,
                 noise: bool = True):
        self.cfg = cfg
        self.tref = tref
        self.rng = rng
        self.noise_on = noise
        # ON-time noise charge std per cycle: integrates S_i over the on window
        self._i2 = cfg.default_noise()
        self._flicker = None         # 1/f charge sequence, primed per run
        self._n = 0

    def charge(self, dt: float) -> float:
        """Net charge delivered for a PFD timing error dt.

        Convention: dt = t_div - t_ref with UP active for dt > 0, i.e. the
        divider edge is late, the UP source dumps Icp*dt onto the filter and
        vctrl rises to speed the VCO (negative-feedback sign is closed by the
        caller's loop equations).  Adds reset-pulse mismatch charge, leakage
        over the full period and integrated current noise over the on-time.
        """
        c = self.cfg
        up = c.icp * (1.0 + 0.005 * c.mismatch_pct)
        dn = c.icp * (1.0 - 0.005 * c.mismatch_pct)
        # both sources on during reset pulse: net mismatch charge every cycle
        dq = (up - dn) * c.t_reset
        # error-dependent charge (the acting source is up or dn depending on sign)
        dq += (up if dt > 0 else dn) * dt
        # leakage integrates over the whole period
        dq += c.leakage_a * self.tref
        if self.noise_on:
            t_on = abs(dt) + c.t_reset
            dq += self.rng.normal(0.0, np.sqrt(self._i2 * t_on))
            dq += self._flicker[self._n] if self._flicker is not None else 0.0
        self._n += 1
        return dq

    def prime_flicker(self, n_cycles: int) -> None:
        """Pre-generate the 1/f charge sequence for a run of n_cycles.

        noise_source() has always carried a flicker corner into analyze() while
        the time domain injected white noise only, so the two domains
        disagreed by the flicker content (~2 dB with the default 100 kHz
        corner once the CP dominates).  Shaped in the FFT domain the same way
        the oscillator's flicker is, rather than by an AR(1) state, which
        would give 1/f^2 above the pole instead of 1/f.
        """
        c = self.cfg
        if not self.noise_on or c.flicker_corner <= 0.0:
            self._flicker = None
            return
        # target: the flicker half of noise_source(), as CHARGE per cycle.
        # S_i,equiv = duty*i2*fc/f with duty = 2*t_reset*fref, and a charge
        # sequence maps as S_i,equiv = S_q * fref^2.
        duty = 2.0 * c.t_reset / self.tref
        fref = 1.0 / self.tref

        def s_q(f):
            return duty * self._i2 * c.flicker_corner / f / fref**2

        self._flicker = synth_from_psd(s_q, fref, n_cycles, self.rng)

    def noise_source(self) -> CurrentNoise:
        duty = self.cfg.t_reset / self.tref
        return CurrentNoise(name="cp", unit="A^2/Hz", i2=self._i2,
                            fc=self.cfg.flicker_corner, duty=2.0 * duty)
