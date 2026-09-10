"""Sampling phase detector front-end (SSPLL / SPLL).

The sample, charge and segment laws are kernels (core.jit) shared with the
sampling loops' compiled engines; the class is the object view with its own
RNG.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from ..core.jit import kernel

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

    def __post_init__(self):
        for name in ("amp_v", "c_samp", "gm", "pulse_width", "temp_k"):
            if not getattr(self, name) > 0:
                raise ValueError(f"SamplerConfig {name} must be positive, "
                                 f"got {getattr(self, name)}")
        if self.kick_delay_s < 0:
            raise ValueError(f"SamplerConfig kick_delay_s cannot be negative, got {self.kick_delay_s}")

    @property
    def ktc_sigma_v(self) -> float:
        return float(np.sqrt(KB * self.temp_k / self.c_samp))

    def gm_i2(self) -> float:
        if self.gm_noise_a2hz is not None:
            return self.gm_noise_a2hz
        return 4.0 * KB * self.temp_k * (2.0 / 3.0) * 2.0 * self.gm

    def charge_sigma(self) -> float:
        """Std of the gm pulse's integrated current noise charge [C]."""
        return float(np.sqrt(self.gm_i2() * self.pulse_width))


@kernel
def pd_sample_det(phase_err_rad: float, amp_v: float, pedestal_v: float) -> float:
    """The held voltage before kT/C noise: A*sin(err) + pedestal."""
    return amp_v * math.sin(phase_err_rad) + pedestal_v


@kernel
def pd_charge_det(v_held: float, gm: float, pulse_width: float) -> float:
    """The gm pulse's charge before its current noise: gm * v * tau."""
    return gm * v_held * pulse_width


@kernel
def pd_segments(dq: float, kick_q_c: float, kick_delay_s: float,
                pulse_width: float, amp: np.ndarray, dur: np.ndarray) -> int:
    """Control-node current as (amplitude, duration) segments, kickback
    first; fills ``amp``/``dur`` (length >= 3) and returns the count.

    The kickback is a charge, not a current, so it is spread over a tenth of
    the gm window: narrow enough to act as an impulse at this timescale and
    wide enough that the sub-sampled record does not have to land on a
    zero-width event.
    """
    n = 0
    if kick_q_c != 0.0:
        w = max(0.1 * pulse_width, 1e-15)
        amp[n] = kick_q_c / w
        dur[n] = w
        n += 1
        gap = kick_delay_s - w
        if gap > 0:
            amp[n] = 0.0
            dur[n] = gap
            n += 1
    amp[n] = dq / max(pulse_width, 1e-15)
    dur[n] = pulse_width
    n += 1
    return n


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
        self._sig_q = cfg.charge_sigma()

    def sample(self, phase_err_rad: float) -> float:
        v = float(pd_sample_det(phase_err_rad, self.cfg.amp_v, self.cfg.pedestal_v))
        if self.noise_on:
            v += self.cfg.ktc_sigma_v * self.rng.standard_normal()
        return v

    def charge(self, v_held: float) -> float:
        dq = float(pd_charge_det(v_held, self.cfg.gm, self.cfg.pulse_width))
        if self.noise_on:
            dq += self._sig_q * self.rng.standard_normal()
        return dq

    def segments(self, dq: float) -> list[tuple[float, float]]:
        """Control-node current as (amplitude, duration), kickback first."""
        c = self.cfg
        amp, dur = np.empty(3), np.empty(3)
        n = int(pd_segments(dq, c.kick_q_c, c.kick_delay_s, c.pulse_width, amp, dur))
        return [(float(amp[i]), float(dur[i])) for i in range(n)]

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
