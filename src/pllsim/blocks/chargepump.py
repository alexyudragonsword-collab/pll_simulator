"""Charge pump with mismatch, leakage and noise."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..core.colored import synth_from_psd
from ..core.noise import CurrentNoise


@dataclass
class CPConfig:
    icp: float                    # nominal current [A]
    mismatch_pct: float = 0.0     # (Iup - Idn)/Icp * 100, at v_ref
    leakage_a: float = 0.0        # static leakage on the control node [A], at v_ref
    t_reset: float = 1e-9         # PFD reset (anti-backlash) pulse width [s]
    noise_a2hz: float | None = None   # thermal current noise when ON [A^2/Hz]
    flicker_corner: float = 100e3
    # ---- control-voltage dependence (both default off) ----
    # Iup and Idn come from sources with different output impedance, so their
    # mismatch is a function of the control node, not a constant: it typically
    # passes through zero somewhere mid-range and grows toward both rails.
    # A constant mismatch predicts one reference spur for the whole tuning
    # range, which is exactly the measurement that never agrees -- the spur is
    # a V-shape across channels, best near the crossing and worst at the rails.
    mismatch_slope_pct_v: float = 0.0     # d(mismatch_pct)/d(vctrl)
    leakage_slope_a_v: float = 0.0        # d(leakage)/d(vctrl); junction/switch
    v_ref: float = 0.0                    # control voltage the two above refer to
    # ---- PFD ----
    # Residual dead zone AFTER the anti-backlash pulse: a phase error whose
    # pulse is narrower than this fails to switch the sources on at all, so the
    # loop is gainless inside the window and wanders across it.  t_reset is the
    # standard cure, so a well-sized PFD leaves this at zero.
    dead_zone_s: float = 0.0
    # "clamp": saturating detector, |dt| limited to 0.45*Tref -- monotone
    # pull-in, no slips.  "wrap": textbook tri-state PFD, linear over +/-2pi of
    # divider phase and wrapping with period 4pi, which is what produces real
    # cycle slipping (the error signal periodically REVERSES during a large
    # frequency error, so acquisition is far slower and can stall).
    pfd_mode: str = "clamp"

    def __post_init__(self):
        if self.pfd_mode not in ("clamp", "wrap"):
            raise ValueError("pfd_mode must be 'clamp' or 'wrap'")

    def default_noise(self) -> float:
        """4kT*gamma*2*gm rough default: scale with Icp (gm ~ Icp/(V*)) ."""
        if self.noise_a2hz is not None:
            return self.noise_a2hz
        gm = self.icp / 0.15      # V* = 150 mV overdrive-ish
        return 4 * 1.380649e-23 * 290.0 * (2.0 / 3.0) * 2.0 * gm

    def mismatch_at(self, vctrl: float) -> float:
        """(Iup-Idn)/Icp * 100 at a control voltage."""
        return self.mismatch_pct + self.mismatch_slope_pct_v * (vctrl - self.v_ref)

    def leakage_at(self, vctrl: float) -> float:
        """Static control-node leakage [A] at a control voltage."""
        return self.leakage_a + self.leakage_slope_a_v * (vctrl - self.v_ref)

    @property
    def v_dependent(self) -> bool:
        return self.mismatch_slope_pct_v != 0.0 or self.leakage_slope_a_v != 0.0


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

    def charge(self, dt: float, vctrl: float | None = None) -> float:
        """Net charge delivered for a PFD timing error dt.

        Convention: dt = t_div - t_ref with UP active for dt > 0, i.e. the
        divider edge is late, the UP source dumps Icp*dt onto the filter and
        vctrl rises to speed the VCO (negative-feedback sign is closed by the
        caller's loop equations).  Adds reset-pulse mismatch charge, leakage
        over the full period and integrated current noise over the on-time.

        Pass the present control voltage to get the mismatch and leakage that
        actually apply there; without it both are evaluated at cfg.v_ref, which
        is the old constant-mismatch behaviour.
        """
        c = self.cfg
        v = c.v_ref if vctrl is None else vctrl
        mm = c.mismatch_at(v)
        up = c.icp * (1.0 + 0.005 * mm)
        dn = c.icp * (1.0 - 0.005 * mm)
        # both sources on during reset pulse: net mismatch charge every cycle
        dq = (up - dn) * c.t_reset
        # error-dependent charge (the acting source is up or dn depending on
        # sign), suppressed entirely inside a residual dead zone
        if abs(dt) >= c.dead_zone_s:
            dq += (up if dt > 0 else dn) * dt
        # leakage integrates over the whole period
        dq += c.leakage_at(v) * self.tref
        return dq + self.noise_charge(dt)

    def noise_charge(self, dt: float) -> float:
        """The stochastic part of one cycle's charge, in isolation.

        Split out so the segment-level model can inject it as an impulse
        without re-drawing: both entry points consume exactly one sample of the
        thermal draw and one of the primed flicker sequence per cycle, so a run
        gives the same noise whichever level of detail it asks for.
        """
        if not self.noise_on:
            self._n += 1
            return 0.0
        t_on = abs(dt) + self.cfg.t_reset
        dq = self.rng.normal(0.0, np.sqrt(self._i2 * t_on))
        dq += self._flicker[self._n] if self._flicker is not None else 0.0
        self._n += 1
        return dq

    def segments(self, dt: float, vctrl: float | None = None
                 ) -> list[tuple[float, float]]:
        """The CP output current as (amplitude [A], duration [s]) segments.

        A tri-state PFD raises whichever output its early edge belongs to, then
        raises the other on the late edge and resets t_reset afterwards.  So one
        source conducts alone for |dt| and BOTH conduct for t_reset:

            dt > 0 (divider late, ref first):  +Iup for dt, then (Iup-Idn) for t_reset
            dt < 0 (divider early):            -Idn for |dt|, then (Iup-Idn) for t_reset

        Their sum is exactly what charge() returns, which is why lumping them
        into one net pulse is fine for the loop dynamics and useless for the
        reference spur: in lock the loop parks at the static offset that makes
        the NET zero, so a net-charge model puts zero ripple on the control node
        and predicts no reference spur at all.  The spur comes from the shape --
        a down pulse followed by an up pulse that cancel in area but not in
        time, which is precisely what these segments carry.
        """
        c = self.cfg
        v = c.v_ref if vctrl is None else vctrl
        mm = c.mismatch_at(v)
        up = c.icp * (1.0 + 0.005 * mm)
        dn = c.icp * (1.0 - 0.005 * mm)
        segs = []
        if abs(dt) >= c.dead_zone_s and dt != 0.0:
            segs.append((up if dt > 0 else -dn, abs(dt)))
        if c.t_reset > 0:
            segs.append((up - dn, c.t_reset))
        return segs

    def lock_offset_s(self, vctrl: float | None = None) -> float:
        """Static PFD offset the loop parks at so the net charge is zero.

        Mismatch and leakage both push charge every period; a type-II loop has
        infinite DC gain, so it answers by sitting at whatever timing error
        makes the total come out zero.  That offset is the deterministic part of
        the reference spur mechanism.
        """
        c = self.cfg
        v = c.v_ref if vctrl is None else vctrl
        mm = c.mismatch_at(v)
        up, dn = c.icp * (1.0 + 0.005 * mm), c.icp * (1.0 - 0.005 * mm)
        s = (up - dn) * c.t_reset + c.leakage_at(v) * self.tref
        return -s / (dn if s > 0 else up)

    def ripple_fundamental_a(self, vctrl: float | None = None) -> float:
        """Peak amplitude [A] of the CP current's fref component in lock.

        The exact Fourier coefficient of the steady-state segment waveform,
        which is NOT the same as treating the per-period impairment charge as a
        single impulse.  In lock the loop has already zeroed the net charge, so
        what is left is a pair of opposite-sign pulses: they cancel in area and
        the fundamental survives only through their separation in time,

            |I(fref)| = 2*fref*|sum_k q_k exp(-j2pi fref t_k)|
                      ~ 2*fref*dq * 2 sin(pi fref dt_sep)

        For MISMATCH the two pulses sit inside the same reset window, dt_sep is
        of order t_reset, and the suppression is severe -- ~38 dB for a 200 ps
        reset at 19.2 MHz.  Treating that charge as one impulse (as this model
        used to) overstates the mismatch-driven reference spur by exactly that
        factor.  For LEAKAGE the suppression does not apply: a constant current
        has no fref component at all, so the entire fundamental comes from the
        narrow correction pulse and the single-impulse answer is correct.  Both
        fall out of the segment sum without special-casing.
        """
        w = 2j * np.pi / self.tref
        dt = self.lock_offset_s(vctrl)
        tot, t = 0j, 0.0
        for amp, dur in self.segments(dt, vctrl):
            tot += amp * (np.exp(-w * t) - np.exp(-w * (t + dur))) / w
            t += dur
        return float(2.0 * abs(tot) / self.tref)

    def pfd_error(self, dt: float) -> tuple[float, bool]:
        """Detector output for a raw timing error, and whether it slipped.

        clamp: saturating, |dt| <= 0.45*Tref.
        wrap:  tri-state PFD -- linear over +/-2pi of divider phase (|dt| <
               Tref) and periodic in 4pi beyond, so a large frequency error
               drives the characteristic through its own reversal and the loop
               slips cycles instead of pulling in monotonically.
        """
        t = self.tref
        if self.cfg.pfd_mode == "clamp":
            return min(max(dt, -0.45 * t), 0.45 * t), abs(dt) > 0.45 * t
        wrapped = ((dt + t) % (2.0 * t)) - t
        return wrapped, abs(dt) > t

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
