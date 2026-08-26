"""Figures of merit: PLL jitter FoM and VCO FoM.

Both normalize a noise number against the power it cost, so that designs at
different frequencies and power budgets can be compared at all.  Neither is
computed from a `Config` anywhere in this package, and that is not an
oversight: **pllsim does not model power.**  There is no current or supply
field in any architecture, so `power_mw` is always something the caller
supplies from a datasheet, a paper or a spice run.  A FoM this package
derived end-to-end would be a number with a fabricated factor in it.

Conventions, stated because both have a second version in the literature
-------------------------------------------------------------------------
* ``fom_n_db`` uses **FoM - 10*log10(N)**, which rewards a higher
  multiplication ratio.  That is the physically motivated direction -- a
  larger N multiplies reference phase noise by N^2 and adds divider noise,
  so reaching the same jitter through a larger N is harder.  Papers that
  write it as an addition exist; the GUIs print the formula next to the
  number so a reader never has to guess which one they are looking at.
* The VCO FoM takes **L(f)** in dBc/Hz -- single sideband, by definition.
  This package stores double-sideband ``S_phi`` internally, and the two are
  3.0103 dB apart, so :func:`vco_fom` accepts either and converts, rather
  than trusting a caller to have divided by two.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from .jitter import ldbc_from_sphi


@dataclass(frozen=True)
class PllFom:
    """Jitter FoM of a whole PLL.  More negative is better."""

    jitter_s: float
    power_mw: float
    fom_db: float

    n: float | None = None
    fom_n_db: float | None = None
    """FoM - 10*log10(N).  None unless a multiplication ratio was given."""

    @property
    def jitter_fs(self) -> float:
        return 1e15 * self.jitter_s


@dataclass(frozen=True)
class VcoFom:
    """Oscillator FoM in dBc/Hz.  More negative is better."""

    f0: float
    offset_hz: float
    l_dbc_hz: float
    power_mw: float
    fom_dbc_hz: float

    ftr_pct: float | None = None
    fom_t_dbc_hz: float | None = None
    """FoM normalized to a 10% tuning range.  None unless FTR was given."""


def _positive(name: str, value: float) -> float:
    value = float(value)
    if not math.isfinite(value) or value <= 0.0:
        raise ValueError(f"{name} must be a positive finite number, "
                         f"got {value!r}")
    return value


def pll_jitter_fom(jitter_s: float, power_mw: float,
                   n: float | None = None) -> PllFom:
    """FoM = 10*log10[ (sigma_t/1s)^2 * (P/1mW) ].

    The square on the jitter is the whole content of this figure: halving
    jitter at constant power gains 6 dB, halving power at constant jitter
    gains 3 dB.  That 2:1 weighting is what stops "spend more current" from
    looking like a design improvement.
    """
    jitter_s = _positive("jitter_s", jitter_s)
    power_mw = _positive("power_mw", power_mw)
    fom = 10.0 * math.log10((jitter_s ** 2) * power_mw)
    fom_n = None
    if n is not None:
        n = _positive("n", n)
        fom_n = fom - 10.0 * math.log10(n)
    return PllFom(jitter_s=jitter_s, power_mw=power_mw, fom_db=fom,
                  n=n, fom_n_db=fom_n)


def vco_fom(f0: float, offset_hz: float, power_mw: float, *,
            l_dbc_hz: float | None = None,
            sphi_rad2_hz: float | None = None,
            ftr_pct: float | None = None) -> VcoFom:
    """FoM = L(df) - 20*log10(f0/df) + 10*log10(P/1mW).

    Give the phase noise as either ``l_dbc_hz`` (single sideband, the
    convention the formula is written in) or ``sphi_rad2_hz`` (this
    package's double-sideband PSD, converted here).  Passing the wrong one
    silently is a 3.0103 dB error, which is why there is no single unnamed
    argument to get wrong.

    Note what the ``-20*log10(f0/df)`` term assumes: that the phase noise
    falls at 20 dB/decade at this offset.  Inside the 1/f^3 corner it does
    not, and the FoM then depends on where it was measured -- so two papers
    quoting it at different offsets are not comparable.  The caller has to
    know that; nothing in the numbers reveals it.
    """
    f0 = _positive("f0", f0)
    offset_hz = _positive("offset_hz", offset_hz)
    power_mw = _positive("power_mw", power_mw)

    if l_dbc_hz is not None and sphi_rad2_hz is not None:
        raise ValueError("give exactly one of l_dbc_hz or sphi_rad2_hz, "
                         "got both")
    # branch rather than reassign: the two arguments are different physical
    # quantities 3.0103 dB apart, and folding them into one name is how that
    # gap goes unnoticed -- in the type checker as well as in a reader's head
    if sphi_rad2_hz is not None:
        l_dbc = float(ldbc_from_sphi(_positive("sphi_rad2_hz", sphi_rad2_hz)))
    elif l_dbc_hz is not None:
        l_dbc = float(l_dbc_hz)
    else:
        raise ValueError("give exactly one of l_dbc_hz or sphi_rad2_hz, "
                         "got neither")
    if not math.isfinite(l_dbc):
        raise ValueError(f"l_dbc_hz must be finite, got {l_dbc!r}")

    carrier_term = 20.0 * math.log10(f0 / offset_hz)
    power_term = 10.0 * math.log10(power_mw)
    fom = l_dbc - carrier_term + power_term

    fom_t = None
    if ftr_pct is not None:
        ftr_pct = _positive("ftr_pct", ftr_pct)
        # the /10 makes FoM_T equal FoM at a 10% tuning range, which is the
        # whole reason the constant is there rather than 1 or 100
        fom_t = (l_dbc
                 - 20.0 * math.log10((f0 / offset_hz) * (ftr_pct / 10.0))
                 + power_term)
    return VcoFom(f0=f0, offset_hz=offset_hz, l_dbc_hz=l_dbc,
                  power_mw=power_mw, fom_dbc_hz=fom,
                  ftr_pct=ftr_pct, fom_t_dbc_hz=fom_t)
