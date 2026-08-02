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
    pedestal_v: float = 1e-3      # static sampling pedestal -> static phase offset
    gm_noise_a2hz: float | None = None
    temp_k: float = T0
    # Charge kicked onto the loop filter by the sampling clock itself, once per
    # reference period, and how long before the gm pulse it lands.
    #
    # This -- not the pedestal -- is what makes an SSPLL's reference spur.  The
    # pedestal adds to the HELD voltage, and the gm converts that same held
    # voltage to charge over the same window, so a type-II loop simply parks at
    # the phase offset where A*sin(perr) + pedestal = 0 and the gm then delivers
    # zero charge.  Zero charge is zero ripple: a static pedestal produces a
    # static phase offset and no spur at all.  That is a real property of the
    # architecture and a large part of why sub-sampling loops are known for
    # clean reference spurs, but it also means a pedestal-based spur formula is
    # predicting something the loop cannot do.
    #
    # Clock kickback is different because it lands at a DIFFERENT instant from
    # the gm pulse that cancels it, so the two form a doublet whose fref
    # component survives in proportion to their separation.
    kick_q_c: float = 0.0
    kick_delay_s: float = 0.0

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

    def segments(self, dq: float) -> list[tuple[float, float]]:
        """Control-node current as (amplitude, duration), kickback first.

        The kickback is a charge, not a current, so it is spread over a tenth of
        the gm window: narrow enough to act as an impulse at this timescale and
        wide enough that the sub-sampled record does not have to land on a
        zero-width event.
        """
        c = self.cfg
        segs = []
        if c.kick_q_c != 0.0:
            w = max(0.1 * c.pulse_width, 1e-15)
            segs.append((c.kick_q_c / w, w))
            gap = c.kick_delay_s - w
            if gap > 0:
                segs.append((0.0, gap))
        segs.append((dq / max(c.pulse_width, 1e-15), c.pulse_width))
        return segs

    def ripple_fundamental_a(self, tref: float) -> float:
        """Peak amplitude [A] of the control-node current at fref, in lock.

        In lock the gm charge exactly cancels the kickback (that is what the
        loop settles to), so the fundamental comes only from the two landing at
        different instants -- see the note on kick_q_c.
        """
        c = self.cfg
        if c.kick_q_c == 0.0:
            return 0.0
        w = 2j * np.pi / tref
        tot, t = 0j, 0.0
        for amp, dur in self.segments(-c.kick_q_c):
            tot += amp * (np.exp(-w * t) - np.exp(-w * (t + dur))) / w
            t += dur
        return float(2.0 * abs(tot) / tref)
