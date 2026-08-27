"""The cross-domain comparator and the boundary registry.

The five architecture tests exercise compare_domains end to end; these pin
the parts a passing architecture test cannot see -- that clipping is
recorded rather than silent, that thin bins surface in `skipped`, that the
registry's codes are unique and its predicates are real fields (the BBPD
predicate was first written against a config field that does not exist, and
only a flag assertion caught it -- hence test_every_boundary_code_can_fire).
"""
from __future__ import annotations

import math

import pytest

from pllsim import presets
from pllsim.core import boundaries
from pllsim.validation import (
    BOUNDARIES,
    BoundaryContext,
    compare_domains,
)


@pytest.fixture(scope="module")
def quick():
    """One short CPPLL run shared by every test here (RBW ~6.8 kHz)."""
    pll = presets.ALL_PRESETS["cppll_19p2m_4p8g"]()
    return pll


def test_low_band_edge_is_clipped_and_the_clip_is_recorded(quick):
    c = compare_domains(quick, n_cycles=30_000, seed=1, band=(1e3, 4.8e6))
    assert c.band_used[0] > 1e3
    assert any("resolution bin" in r for r in c.clip_reasons), c.clip_reasons


def test_high_band_edge_is_clipped_at_the_alias_guard(quick):
    c = compare_domains(quick, n_cycles=30_000, seed=1, band=(1e5, 20e6))
    assert c.band_used[1] == pytest.approx(0.45 * 19.2e6)
    assert any("record rate" in r for r in c.clip_reasons), c.clip_reasons


def test_the_default_band_needs_no_clipping_at_the_stock_point(quick):
    """The historical tolerances were set on the unclipped band; if the
    default band ever starts clipping at a stock point, every baseline is
    silently re-based -- that is a failure, not a convenience."""
    c = compare_domains(quick, n_cycles=200_000, seed=3)
    assert c.clip_reasons == []


def test_thin_bins_land_in_skipped_not_nowhere(quick):
    # 40 bins over a short record forces some bins under min_points
    c = compare_domains(quick, n_cycles=30_000, seed=1, n_bins=40)
    assert c.skipped, "expected at least one thin bin at this resolution"
    assert all(math.isnan(b.err_db) for b in c.skipped)
    # and they are excluded from the verdict rather than polluting it
    assert math.isfinite(c.worst_db)


def test_same_band_jitter_is_actually_the_same_band(quick):
    """The headline pair integrates different bands (int_band vs 0.45*fref);
    the comparator's pair must not repeat that."""
    c = compare_domains(quick, n_cycles=200_000, seed=3)
    assert 0.7 < c.jitter_sim_fs / c.jitter_model_fs < 1.4, (
        c.jitter_sim_fs, c.jitter_model_fs)


def test_an_empty_band_is_an_error_not_a_silent_pass(quick):
    """A band lying entirely above the alias guard clips to nothing; the
    honest response is an error naming the clip, not a comparison of zero
    bins that trivially passes."""
    with pytest.raises(ValueError, match="empty comparison band"):
        compare_domains(quick, n_cycles=30_000, seed=1, band=(8.7e6, 9.0e6))


def test_fine_source_is_chosen_when_the_band_needs_it():
    """MDLL's comparison reaches past 0.45*fref, which only the oversampled
    record can show; auto must switch instead of comparing against alias."""
    mdll = presets.ALL_PRESETS["mdll_150m_2p4g"]()
    c = compare_domains(mdll, n_cycles=40_000, seed=1, band=(3e5, 2.5e8),
                        sim_kwargs={"f_free_error": 2e6})
    assert c.psd_source == "fine"


def test_boundary_codes_are_unique():
    codes = [b.code for b in BOUNDARIES]
    assert len(codes) == len(set(codes)), codes


@pytest.mark.parametrize("code", [b.code for b in BOUNDARIES])
def test_every_boundary_code_can_fire(code, quick):
    """A predicate over a field that does not exist is decorative: it reads
    as a documented boundary and never fires.  The BBPD entry shipped that
    way for one commit (`mode == "bb"` vs the real `"dtc_bbpd"`).  Build one
    context per code that must trigger it.
    """
    ar = quick.analyze()

    class _Loop:
        f_ugb = ar.loop.f_ugb
        n_crossings = ar.loop.n_crossings

    def ctx(pll=quick, f_ugb=None, n_crossings=None, band=(1e5, 4.8e6),
            fs=None, int_band_hi=None, n_cycles=30_000):
        class _Ar:
            loop = _Loop()
            if f_ugb is not None:
                loop.f_ugb = f_ugb
            if n_crossings is not None:
                loop.n_crossings = n_crossings
        class _Sim:
            fs = quick.cfg.fref
        if fs is not None:
            _Sim.fs = fs
        p = pll
        if int_band_hi is not None:
            import copy
            p = copy.deepcopy(pll)
            p.cfg.int_band = (p.cfg.int_band[0], int_band_hi)
        return BoundaryContext(pll=p, ar=_Ar(), sim=_Sim(), band=band,
                               n_cycles=n_cycles)

    fref = quick.cfg.fref
    triggering = {
        "ct-approx": ctx(f_ugb=fref / 5),
        "jitter-band-clip": ctx(int_band_hi=100e6),
        "flicker-floor": ctx(band=(1.0, 4.8e6)),
        "conditional-stability": ctx(n_crossings=2),
        "bbpd-linearization": BoundaryContext(
            pll=presets.ALL_PRESETS["adpll_bb_100m_10g"](), ar=None, sim=None,
            band=(1e5, 1e6), n_cycles=1),
        "dsm-tonal": BoundaryContext(
            pll=presets.ALL_PRESETS["cppll_frac_38p4m_6g"](), ar=None,
            sim=None, band=(1e5, 1e6), n_cycles=1),
    }
    assert code in triggering, f"no trigger case written for {code}"
    entry = next(b for b in BOUNDARIES if b.code == code)
    assert entry.applies(triggering[code]), (
        f"{code}: the constructed trigger context does not fire it -- "
        "either the predicate reads a field that does not exist, or the "
        "trigger case is stale")


def test_flicker_floor_tracks_both_limits():
    fref = 19.2e6
    # short record: the record length is the binding limit
    assert boundaries.flicker_floor_hz(fref, 10_000) == pytest.approx(
        fref / 7_500)
    # long record: the synthesis chunk is
    assert boundaries.flicker_floor_hz(fref, 10_000_000) == pytest.approx(
        fref / boundaries.FLICKER_CHUNK)
