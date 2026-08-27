"""The cross-domain sweep: the consistency contract over the parameter space.

The five per-architecture tests check one stock point each.  This matrix is
what answers "does the contract hold when the parameters move" -- the
question that motivated it, after bandwidth and frequency-plan changes were
found to open multi-dB gaps that no test saw.

Every point runs the same contract:

* its measured worst band deviation must stay under
  ``base_tol + sum(extra_db of the boundary flags that are BOTH expected and
  active)`` -- a flagged point gets its documented allowance, never a blank
  cheque;
* an out-of-tolerance point with **no** active flag is a model defect, and
  fails loudly -- that is the clause that keeps the boundary registry honest;
* every flag a point declares must actually fire, so a boundary that stops
  firing (a renamed config field, a changed threshold) is caught even when
  the numbers happen to pass.

Points where the tool itself refuses are asserted refusals, not skips: the
synthesizer's fref/8 cap and the ILCM/MDLL no-loop-filter refusal are
capability statements, and a statement that stops being enforced is a
regression.

Known gaps (``pllsim.validation.CROSS_DOMAIN_GAPS``) are pinned: the sweep
re-measures each and fails if it drifts more than its slack in either
direction.  Getting *better* is also a failure -- it means the pin is stale
and the register no longer describes the tool.

Marked ``sweep``: the main CI test job deselects it (`-m "not sweep"`) and a
dedicated parallel job runs only this file, so the matrix costs no wall-clock
on the main suite.  All numbers here were measured at 120k cycles, seed 1.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any, Callable

import pytest

from pllsim import presets
from pllsim.synth import retune_loop
from pllsim.validation import (
    BOUNDARIES,
    CROSS_DOMAIN_GAPS,
    compare_domains,
)

pytestmark = pytest.mark.sweep

N_CYCLES = 120_000
SEED = 1

_BOUND = {b.code: b for b in BOUNDARIES}
_GAPS = {g.point_id: g for g in CROSS_DOMAIN_GAPS}

#: Shipping per-architecture baselines -- the same numbers the five stock
#: tests assert, applied unchanged across the swept space.
BASE_TOL = {"CPPLL": 2.5, "SSPLL": 3.0, "SPLL": 2.0, "ADPLL": 3.0,
            "ILCM": 2.0, "MDLL": 3.5}


# ------------------------------------------------------------- grid builders

def _preset(name: str):
    return copy.deepcopy(presets.ALL_PRESETS[name]())


def _fref_scaled(name: str, fm: float):
    """Scale fref at fixed fout; N absorbs the change (integer-N intent)."""
    p = _preset(name)
    p.cfg.fref *= fm
    return p


def _fref_scaled_frac(name: str, fm: float):
    """Scale fref keeping the configured fraction; fout moves to stay
    consistent.  Scaling fref alone on a fractional preset silently changes
    the effective fraction away from cfg.frac.frac, and the loop then locks
    to the configured fraction -- megahertz away from cfg.fout.  The
    not-locked guard caught exactly that on the first full run."""
    p = _preset(name)
    frac = p.cfg.frac.frac
    p.cfg.fref *= fm
    n_int = round(p.cfg.fout / p.cfg.fref - frac)
    p.cfg.fout = (n_int + frac) * p.cfg.fref
    return p


def _retuned(name: str, m: float, pm: float | None = None):
    p = _preset(name)
    retune_loop(p, m * p.analyze().loop.f_ugb, pm_deg=pm)
    return p


def _near_integer(name: str):
    """Move the fraction to 0.004 -- consistently, in fout AND in the MASH
    config, or the loop locks half a reference period away from fout."""
    p = _preset(name)
    n = p.cfg.fout / p.cfg.fref
    p.cfg.fout = (round(n) + 0.004) * p.cfg.fref
    p.cfg.frac.frac = 0.004
    return p


@dataclass(frozen=True)
class Point:
    id: str
    build: Callable[[], Any]
    arch: str
    expected_flags: frozenset[str] = frozenset()
    kwargs: dict = field(default_factory=dict)

    @property
    def base_tol(self) -> float:
        return BASE_TOL[self.arch]


def P(id, build, arch, flags=(), **kwargs):  # noqa: N802 - grid shorthand
    return Point(id, build, arch, frozenset(flags), kwargs)


CLIP = "jitter-band-clip"
ILCM_KW = dict(band=(1e5, 60e6), psd_source="ref",
               sim_kwargs={"f_free_error": 3e6})
MDLL_KW = dict(band=(3e5, 2.5e8), psd_source="fine", n_bins=6,
               sim_kwargs={"f_free_error": 2e6})

GRID = [
    # ---------------------------------------------------------- CPPLL int-N
    P("cppll-stock", lambda: _preset("cppll_19p2m_4p8g"), "CPPLL", [CLIP]),
    P("cppll-ugb-x0.3", lambda: _retuned("cppll_19p2m_4p8g", 0.3), "CPPLL",
      [CLIP]),
    P("cppll-ugb-x1.6", lambda: _retuned("cppll_19p2m_4p8g", 1.6), "CPPLL",
      [CLIP]),
    P("cppll-ugb-x1.9", lambda: _retuned("cppll_19p2m_4p8g", 1.9), "CPPLL",
      [CLIP]),
    P("cppll-ugb-x2.1", lambda: _retuned("cppll_19p2m_4p8g", 2.1), "CPPLL",
      [CLIP, "ct-approx"]),
    P("cppll-fref-x0.5", lambda: _fref_scaled("cppll_19p2m_4p8g", 0.5),
      "CPPLL", [CLIP]),
    P("cppll-fref-x2.0", lambda: _fref_scaled("cppll_19p2m_4p8g", 2.0),
      "CPPLL", [CLIP]),
    P("cppll-pm45", lambda: _retuned("cppll_19p2m_4p8g", 1.0, pm=45),
      "CPPLL", [CLIP]),
    P("cppll-fine-m8", lambda: _preset("cppll_19p2m_4p8g"), "CPPLL", [CLIP],
      sim_kwargs={"fine_oversample": 8}),
    # ---------------------------------------------------------- SSPLL int-N
    P("sspll-stock", lambda: _preset("sspll_19p2m_4p8g"), "SSPLL", [CLIP]),
    P("sspll-ugb-x0.3", lambda: _retuned("sspll_19p2m_4p8g", 0.3), "SSPLL",
      [CLIP]),
    P("sspll-fref-x0.5", lambda: _fref_scaled("sspll_19p2m_4p8g", 0.5),
      "SSPLL", [CLIP]),
    P("sspll-fref-x2.0", lambda: _fref_scaled("sspll_19p2m_4p8g", 2.0),
      "SSPLL", [CLIP]),
    P("sspll-flicker-x10", lambda: _flicker_x10(), "SSPLL", [CLIP]),
    # ----------------------------------------------------------- SPLL int-N
    P("spll-stock", lambda: _preset("spll_100m_8g"), "SPLL", [CLIP]),
    P("spll-ugb-x0.3", lambda: _retuned("spll_100m_8g", 0.3), "SPLL", [CLIP]),
    P("spll-ugb-x3.0", lambda: _retuned("spll_100m_8g", 3.0), "SPLL", [CLIP]),
    P("spll-fref-x0.5", lambda: _fref_scaled("spll_100m_8g", 0.5), "SPLL",
      [CLIP]),
    P("spll-fref-x2.0", lambda: _fref_scaled("spll_100m_8g", 2.0), "SPLL",
      [CLIP]),
    # 7.33x stock UGB targets fref/9.5, the deepest loop the optimizer will
    # land (12.2M at PM 45 already fails synthesis).  The lock detector stays
    # silent but the loop converges -- the tail-frequency guard admits it
    P("spll-ugb-max-pm45", lambda: _retuned("spll_100m_8g", 7.33, pm=45),
      "SPLL", [CLIP, "ct-approx"]),
    # ------------------------------------------------------------ ADPLL tdc
    P("adpll-stock", lambda: _preset("adpll_100m_10g"), "ADPLL", [CLIP]),
    P("adpll-ugb-x0.3", lambda: _retuned("adpll_100m_10g", 0.3), "ADPLL",
      [CLIP]),
    P("adpll-ugb-x3.0", lambda: _retuned("adpll_100m_10g", 3.0), "ADPLL",
      [CLIP]),
    P("adpll-fref-x0.5", lambda: _fref_scaled("adpll_100m_10g", 0.5),
      "ADPLL", [CLIP]),
    P("adpll-fref-x2.0", lambda: _fref_scaled("adpll_100m_10g", 2.0),
      "ADPLL", [CLIP]),
    P("adpll-tdc-x4", lambda: _tdc_x4(), "ADPLL", [CLIP]),
    # --------------------------------------------------------- fractional-N
    P("cppll_frac-stock", lambda: _preset("cppll_frac_38p4m_6g"), "CPPLL",
      [CLIP, "dsm-tonal"]),
    P("cppll_frac-fref-x0.5",
      lambda: _fref_scaled_frac("cppll_frac_38p4m_6g", 0.5), "CPPLL",
      [CLIP, "dsm-tonal"]),
    P("cppll_frac-fref-x2.0",
      lambda: _fref_scaled_frac("cppll_frac_38p4m_6g", 2.0), "CPPLL",
      [CLIP, "dsm-tonal"]),
    P("cppll_frac-near-int", lambda: _near_integer("cppll_frac_38p4m_6g"),
      "CPPLL", [CLIP, "dsm-tonal"]),
    P("sspll_frac-stock", lambda: _preset("sspll_frac_19p2m_4p806g"),
      "SSPLL", [CLIP, "dsm-tonal"]),
    P("sspll_frac-fref-x0.5",
      lambda: _fref_scaled_frac("sspll_frac_19p2m_4p806g", 0.5), "SSPLL",
      [CLIP, "dsm-tonal"]),
    P("sspll_frac-fref-x2.0",
      lambda: _fref_scaled_frac("sspll_frac_19p2m_4p806g", 2.0), "SSPLL",
      [CLIP, "dsm-tonal"]),
    P("sspll_frac-near-int", lambda: _near_integer("sspll_frac_19p2m_4p806g"),
      "SSPLL", [CLIP, "dsm-tonal"]),
    P("spll_frac-stock", lambda: _preset("spll_frac_52m_6p253g"), "SPLL",
      [CLIP, "dsm-tonal"]),
    P("spll_frac-fref-x0.5",
      lambda: _fref_scaled_frac("spll_frac_52m_6p253g", 0.5), "SPLL",
      [CLIP, "dsm-tonal"]),
    P("spll_frac-fref-x2.0",
      lambda: _fref_scaled_frac("spll_frac_52m_6p253g", 2.0), "SPLL",
      [CLIP, "dsm-tonal"]),
    P("spll_frac-near-int", lambda: _near_integer("spll_frac_52m_6p253g"),
      "SPLL", [CLIP, "dsm-tonal"]),
    P("adpll_bb-stock", lambda: _preset("adpll_bb_100m_10g"), "ADPLL",
      [CLIP, "dsm-tonal", "bbpd-linearization"]),
    P("adpll_bb-fref-x0.5", lambda: _fref_scaled_frac("adpll_bb_100m_10g", 0.5),
      "ADPLL", [CLIP, "dsm-tonal", "bbpd-linearization"]),
    P("adpll_bb-fref-x2.0", lambda: _fref_scaled_frac("adpll_bb_100m_10g", 2.0),
      "ADPLL", [CLIP, "dsm-tonal", "bbpd-linearization"]),
    P("adpll_bb-near-int", lambda: _near_integer("adpll_bb_100m_10g"),
      "ADPLL", [CLIP, "dsm-tonal", "bbpd-linearization"]),
    # ------------------------------------------------------------ ILCM/MDLL
    P("ilcm-stock", lambda: _preset("ilcm_250m_12g"), "ILCM", [], **ILCM_KW),
    P("ilcm-fref-x0.5", lambda: _fref_scaled("ilcm_250m_12g", 0.5), "ILCM",
      [CLIP], band=(1e5, 30e6), psd_source="ref",
      sim_kwargs={"f_free_error": 3e6}),
    P("ilcm-fref-x2.0", lambda: _fref_scaled("ilcm_250m_12g", 2.0), "ILCM",
      [], band=(1e5, 120e6), psd_source="ref",
      sim_kwargs={"f_free_error": 3e6}),
    P("mdll-stock", lambda: _preset("mdll_150m_2p4g"), "MDLL", [CLIP],
      **MDLL_KW),
    P("mdll-fref-x0.5", lambda: _fref_scaled("mdll_150m_2p4g", 0.5), "MDLL",
      [CLIP], band=(3e5, 1.25e8), psd_source="fine", n_bins=6,
      sim_kwargs={"f_free_error": 2e6}),
    P("mdll-fref-x2.0", lambda: _fref_scaled("mdll_150m_2p4g", 2.0), "MDLL",
      [], band=(3e5, 5e8), psd_source="fine", n_bins=6,
      sim_kwargs={"f_free_error": 2e6}),
]


def _flicker_x10():
    p = _preset("sspll_19p2m_4p8g")
    p.cfg.osc.pn_f1f3 *= 10
    return p


def _tdc_x4():
    p = _preset("adpll_100m_10g")
    p.cfg.tdc.t_res *= 4
    return p


#: Points where the tool refuses, asserted as refusals.  The synthesizer's
#: fref/8 cap and the acquisition envelope are capability statements; a
#: statement that stops being enforced is a regression.
REFUSED_SYNTH = [
    ("cppll-ugb-x3.0", lambda: _retuned("cppll_19p2m_4p8g", 3.0)),
    ("sspll-ugb-x3.0", lambda: _retuned("sspll_19p2m_4p8g", 3.0)),
]
# There is no REFUSED_LOCK list.  The first draft had seven entries; every
# one turned out to be this harness scaling fref without keeping
# cfg.frac.frac consistent, so the loop locked to the configured fraction
# megahertz away from cfg.fout and the guard (rightly) refused.  With
# consistent configs all seven lock and compare.  The NotLockedError guard
# itself is exercised in tests/test_boundaries.py against a deliberately
# inconsistent config -- which is exactly the user error it exists to catch.
REFUSED_RETUNE = [
    ("ilcm-retune", lambda: _retuned("ilcm_250m_12g", 1.5)),
    ("mdll-retune", lambda: _retuned("mdll_150m_2p4g", 1.5)),
]


# ------------------------------------------------------------------ contract

@pytest.mark.parametrize("point", GRID, ids=lambda p: p.id)
def test_point(point):
    c = compare_domains(point.build(), n_cycles=N_CYCLES, seed=SEED,
                        **point.kwargs)

    missing = point.expected_flags - c.flags
    assert not missing, (
        f"{point.id}: declared boundary flags {sorted(missing)} did not "
        "fire -- either the predicate broke or the declaration is stale")

    allowed = point.base_tol + sum(
        _BOUND[f].extra_db for f in (c.flags & point.expected_flags))
    detail = [f"{b.f_lo:.3g}-{b.f_hi:.3g}: {b.err_db:+.2f}" for b in c.bands]

    gap = _GAPS.get(point.id)
    if gap is not None:
        # a pinned gap must stay where it was measured -- in BOTH directions:
        # drifting worse is a regression, drifting better means the pin (and
        # the roadmap entry rendered from it) no longer describes the tool
        assert abs(c.worst_db - gap.pinned_db) < gap.slack_db, (
            f"{point.id}: pinned {gap.pinned_db:.2f} dB, measured "
            f"{c.worst_db:.2f} -- re-measure and update the register: "
            f"{detail}")
        return

    if c.worst_db > point.base_tol:
        assert c.flags, (
            f"{point.id}: {c.worst_db:.2f} dB over the {point.base_tol} dB "
            f"base with NO boundary flag active -- a model defect, not a "
            f"boundary: {detail}")
    assert c.worst_db < allowed, (
        f"{point.id}: {c.worst_db:.2f} dB > allowed {allowed:.2f} "
        f"(base {point.base_tol} + flags {sorted(c.flags)}): {detail}")


@pytest.mark.parametrize("pid,build", REFUSED_SYNTH, ids=lambda x: x
                         if isinstance(x, str) else "")
def test_synthesis_refuses(pid, build):
    with pytest.raises(ValueError, match="fref/8"):
        build()


@pytest.mark.parametrize("pid,build", REFUSED_RETUNE, ids=lambda x: x
                         if isinstance(x, str) else "")
def test_edge_realigned_archs_refuse_retuning(pid, build):
    with pytest.raises(TypeError, match="no loop filter"):
        build()


# ---------------------------------------------------------------- register

def test_every_pinned_gap_is_a_grid_point():
    """A gap entry nothing re-measures is a number that can rot -- the exact
    failure the register exists to prevent."""
    ids = {p.id for p in GRID}
    orphans = [g.point_id for g in CROSS_DOMAIN_GAPS if g.point_id not in ids]
    assert not orphans, f"gap entries with no grid point: {orphans}"


def test_every_boundary_is_exercised_by_the_grid():
    """A boundary no grid point expects is documentation the sweep never
    checks.  flicker-floor is exempt with its reason: the 3x-RBW clip always
    sits above the flicker floor until a record exceeds ~1.6M cycles (24/n
    vs 1/65536), so no CI-budget point can fire it -- it is kept for the
    long GUI runs where it does."""
    expected = set().union(*(p.expected_flags for p in GRID))
    missing = {b.code for b in BOUNDARIES} - expected - {
        "flicker-floor", "conditional-stability"}
    assert not missing, f"boundaries no grid point exercises: {missing}"


def test_conditional_stability_has_no_stock_representative():
    """No stock or swept preset is conditionally stable (measured after the
    image-counting fix); the predicate is exercised synthetically in
    test_validation.  If a grid point ever starts flagging it, promote it to
    an expected flag instead of relying on this exemption."""
    for point in GRID:
        assert "conditional-stability" not in point.expected_flags
