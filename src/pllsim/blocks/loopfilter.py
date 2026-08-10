"""Passive loop-filter state-space model with exact discrete-time updates.

Topologies (charge-pump drives node 1, vctrl taken at node 1):

  2nd order:  C2 from node1 to gnd, series (R2 + C1) from node1 to gnd
  3rd order:  2nd order + series R3 to node2 with C3 to gnd (vctrl at node2)

States are capacitor voltages.  The CP current is treated as an impulse of
charge dq per reference cycle near lock (|t_on| << Tref); during acquisition a
pulse-width-aware two-segment update is available (update_pulse).

Exact discretization: x(t+T) = e^{AT} x(t) + (charge impulse enters as an
instantaneous state jump dq/C_eff distributed by the input vector).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.linalg import expm


@dataclass
class FilterDesign:
    """Component values; c3/r3 = 0 disables the third pole."""

    c1: float
    r2: float
    c2: float
    r3: float = 0.0
    c3: float = 0.0

    @property
    def order(self) -> int:
        return 3 if (self.c3 > 0 and self.r3 > 0) else 2


class LoopFilter:
    """Exact discrete state-space integrator for the passive CP filter."""

    def __init__(self, design: FilterDesign, tstep: float):
        self.d = design
        self.tstep = tstep
        self._build()

    def _build(self):
        d = self.d
        if d.order == 2:
            # states: v1 (C1 voltage), v2 (C2 = node voltage)
            # node eq: i_in = C2 dv2/dt + (v2 - v1)/R2 ; C1 dv1/dt = (v2 - v1)/R2
            a = np.array([
                [-1.0 / (d.r2 * d.c1), 1.0 / (d.r2 * d.c1)],
                [1.0 / (d.r2 * d.c2), -1.0 / (d.r2 * d.c2)],
            ])
            b = np.array([0.0, 1.0 / d.c2])       # per amp of input current
            c = np.array([0.0, 1.0])              # vctrl = v2 (node voltage)
        else:
            # states: v1 (C1), v2 (C2 node), v3 (C3 node = vctrl)
            a = np.array([
                [-1.0 / (d.r2 * d.c1), 1.0 / (d.r2 * d.c1), 0.0],
                [1.0 / (d.r2 * d.c2), -1.0 / d.c2 * (1.0 / d.r2 + 1.0 / d.r3), 1.0 / (d.r3 * d.c2)],
                [0.0, 1.0 / (d.r3 * d.c3), -1.0 / (d.r3 * d.c3)],
            ])
            b = np.array([0.0, 1.0 / d.c2, 0.0])
            c = np.array([0.0, 0.0, 1.0])
        self.a, self.b, self.c = a, b, c
        self.ad = expm(a * self.tstep)
        self.x = np.zeros(a.shape[0])
        # eigendecomposition for cheap per-cycle e^{At}: A = V diag(w) V^-1
        # (passive RC: distinct eigenvalues incl. the type-II zero eigenvalue)
        self._w, self._v = np.linalg.eig(a)
        self._vinv = np.linalg.inv(self._v)
        self._vinv_b = self._vinv @ b

    def reset(self, vctrl: float = 0.0):
        self.x = np.full(self.a.shape[0], vctrl)

    @property
    def vctrl(self) -> float:
        # both topologies take vctrl at the last state (C @ x == x[-1])
        return float(self.x[-1])

    def update_impulse(self, dq: float) -> float:
        """One tstep with the CP charge dq applied as an impulse at the start.

        Impulse response: state jump x += b * dq (b in 1/C units), then free
        evolution over tstep.  Valid when the CP on-time << tstep.
        """
        self.x = self.ad @ (self.x + self.b * dq)
        return self.vctrl

    def update_pulse(self, i_cp: float, t_on: float) -> float:
        """One tstep with constant current i_cp for t_on, then free evolution.

        A is singular (the type-II integrator pole: total charge is conserved
        with zero input); the input integral is evaluated per eigenvalue with
        the d->0 limit handled explicitly.  For t_on << tstep the charge
        impulse approximation (precomputed e^{A T}) is exact to O(t_on/tau)
        and avoids the per-cycle eigen-reconstruction entirely.
        """
        t_on = min(abs(t_on), self.tstep)
        if t_on < 0.02 * self.tstep:
            return self.update_impulse(i_cp * t_on)
        # e^{A t_on} and gamma = int_0^t e^{As} ds b via the eigenbasis;
        # (e^{wt}-1)/w cancels catastrophically for the near-zero (type-II)
        # eigenvalue, so use the Taylor branch there
        wt = self._w * t_on
        ew = np.exp(wt)
        small = np.abs(wt) < 1e-8
        g = np.where(small,
                     t_on * (1.0 + wt / 2.0 + wt * wt / 6.0),
                     (ew - 1.0) / np.where(small, 1.0, self._w))
        xe = self._vinv @ self.x
        xe = ew * xe + g * self._vinv_b * i_cp
        rest = self.tstep - t_on
        if rest > 0:
            xe = np.exp(self._w * rest) * xe
        self.x = np.real(self._v @ xe)
        return self.vctrl

    def drive_fine(self, segments, m: int, i_bias: float = 0.0,
                   dq_impulse: float = 0.0) -> np.ndarray:
        """One tstep driven by a piecewise-constant current, sampled m times.

        ``segments`` is a sequence of (amplitude [A], duration [s]) applied back
        to back from the start of the step; ``i_bias`` (leakage) flows for the
        whole step and ``dq_impulse`` (noise charge) lands at t=0.  Samples are
        taken at the END of each of the m equal sub-intervals, so the last one
        is the state the step leaves behind.

        Sampling inside the step is what makes the reference spur visible: the
        control node's ripple lives entirely within one reference period, so a
        record taken once per reference edge sees one point on it and reports no
        ripple at all.  The segments matter for the same reason -- see
        ChargePump.segments.

        Evaluated in closed form at all m sample times at once rather than by
        stepping.  The system is LTI and diagonal in the eigenbasis, so each
        segment's contribution at time t is a difference of two exponentials
        of *elapsed* time -- see _seg_integral.  Stepping made the cost O(m)
        Python iterations, which put this on the critical path of every spur
        run; m of a few hundred is routine because the sub-interval has to
        resolve t_reset (~200 ps) inside a reference period (~50 ns).
        """
        m = max(int(m), 1)
        # clip the drive to one step and build sub-interval boundaries
        segs, used = [], 0.0
        for amp, dur in segments:
            dur = min(max(dur, 0.0), self.tstep - used)
            if dur <= 0.0:
                break
            segs.append((amp + i_bias, dur))
            used += dur
        if used < self.tstep:
            segs.append((i_bias, self.tstep - used))

        # sample at the END of each sub-interval, so out[-1] is the state the
        # step leaves behind
        t = self.tstep * np.arange(1, m + 1) / m
        xe0 = self._vinv @ self.x + self._vinv_b * dq_impulse
        acc = np.zeros((m, self._w.size), dtype=complex)
        start = 0.0
        for amp, dur in segs:
            if amp != 0.0:
                acc += amp * self._seg_integral(t, start, start + dur)
            start += dur
        xe = np.exp(np.outer(t, self._w)) * xe0 + self._vinv_b * acc
        vctrl = np.real(xe @ self._v.T)[:, -1]
        self.x = np.real(self._v @ xe[-1])
        return vctrl

    def _seg_integral(self, t: np.ndarray, a: float, b: float) -> np.ndarray:
        """(e^{w(t-a)+} - e^{w(t-b)+}) / w for every t, per eigenvalue.

        The convolution of e^{At} with a unit current over [a, b], written so
        that both exponents are of *clipped elapsed* time and therefore never
        positive: the algebraically equivalent e^{wt}(e^{-wa} - e^{-wb})/w
        overflows for a fast pole, since e^{-w*tstep} is the reciprocal of a
        number the stable dynamics have already made tiny.  Clipping at zero
        also makes the term vanish identically before the segment starts.

        The type-II integrator sits exactly at w = 0, where the expression is
        0/0; that branch is the elapsed duration itself, plus one correction
        term for the case where |w*t| is merely small rather than zero.  One
        term is enough and the next would be unreachable: at the 1e-8 switch
        point the linear correction is already only ~6e-9 of the answer, so
        the quadratic one lands at ~1e-17 -- under the double-precision floor,
        where no test could tell it from nothing.
        """
        p = np.clip(t - a, 0.0, None)[:, None]
        q = np.clip(t - b, 0.0, None)[:, None]
        w = self._w[None, :]
        small = np.abs(w) * self.tstep < 1e-8
        # expm1 rather than exp: for a slow pole the two exponentials are both
        # near 1 and their difference is all cancellation
        big = (np.expm1(w * p) - np.expm1(w * q)) / np.where(small, 1.0, w)
        ser = (p - q) + 0.5 * w * (p * p - q * q)
        return np.where(small, ser, big)

    # ------------------------------------------------------------ freq domain
    def transimpedance(self, f: np.ndarray) -> np.ndarray:
        """Z(f) = C (jwI - A)^-1 B  [V/A], vectorized over the grid."""
        w = 2j * np.pi * np.asarray(f, dtype=float)
        n = self.a.shape[0]
        z = np.empty(w.shape, dtype=complex)
        eye = np.eye(n)
        for i, wi in enumerate(w):
            z[i] = self.c @ np.linalg.solve(wi * eye - self.a, self.b)
        return z

    def charge_tf_z(self, f: np.ndarray) -> np.ndarray:
        """Exact discrete charge -> vctrl transfer [V/C] at z = e^{j2πf·tstep}.

        Matches update_impulse exactly: x[n] = Ad (x[n-1] + b dq[n])
        => H(z) = C (I - Ad z^-1)^-1 Ad b.  Use this for loops with aggressive
        BW/fref ratios where the continuous 1/s approximation misses the
        sampled-loop rolloff.
        """
        zinv = np.exp(-2j * np.pi * np.asarray(f, dtype=float) * self.tstep)
        n = self.a.shape[0]
        adb = self.ad @ self.b
        eye = np.eye(n)
        out = np.empty(zinv.shape, dtype=complex)
        for i, zi in enumerate(zinv):
            out[i] = self.c @ np.linalg.solve(eye - self.ad * zi, adb)
        return out
