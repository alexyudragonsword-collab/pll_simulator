"""PLL jitter FoM and VCO FoM.

The strongest available anchor is a published triple: Dartizio'23 reports
77 fs, 17.2 mW **and** FoM -249.9 dB, all three already recorded in
`examples/ex14_benchmarks_jssc.py`.  Reproducing the third from the first two
tests the formula against the literature rather than against my arithmetic.

For the VCO FoM there is no such triple in this repository, so it is pinned
by a structural property instead: inside a 1/f^2 region the FoM must not
depend on which offset it was evaluated at.  That is the entire reason the
figure exists, and it fails for any wrong exponent on the carrier term.
"""
from __future__ import annotations

import math
import re
from pathlib import Path

import pytest

from pllsim.core.fom import pll_jitter_fom, vco_fom
from pllsim.core.jitter import HALF_POWER_DB, sphi_from_ldbc

EX14 = Path(__file__).resolve().parents[1] / "examples/ex14_benchmarks_jssc.py"


def test_the_published_dartizio_fom_comes_back_out():
    """77 fs at 17.2 mW must give the -249.9 dB the paper states."""
    got = pll_jitter_fom(77e-15, 17.2).fom_db
    assert got == pytest.approx(-249.9, abs=0.05), got


def test_that_anchor_is_the_one_the_repo_records():
    """Guard against the anchor above quietly drifting from its source.

    A test whose reference number lives only in the test is a test that
    agrees with itself.  These three come from ex14's docstring.
    """
    text = EX14.read_text()
    assert "17.2 mW, FoM -249.9 dB" in text, (
        "ex14 no longer states the power and FoM this test is pinned to")
    assert re.search(r"\(-71\.9 dBc\), 17\.2 mW", text)


@pytest.mark.parametrize("jitter_fs, fom_db", [(176, -246.6), (75, -249.7)])
def test_the_other_published_foms_imply_plausible_power(jitter_fs, fom_db):
    """Inverting the formula on Markulic'16 and Wu'19 must land on a power a
    published PLL could actually have burned -- single-digit to tens of mW.
    Their power is not recorded here, so this is a sanity bound, not a
    match, and it is labelled as one."""
    implied_mw = 10.0 ** (fom_db / 10.0) / (jitter_fs * 1e-15) ** 2
    assert 1.0 < implied_mw < 100.0, implied_mw
    # and the formula round-trips through that implied power
    assert pll_jitter_fom(jitter_fs * 1e-15, implied_mw).fom_db == \
        pytest.approx(fom_db, abs=1e-9)


def test_halving_jitter_gains_six_db_and_halving_power_gains_three():
    """The 2:1 weighting is the content of the figure: without it, spending
    current to buy jitter would look like a free improvement."""
    base = pll_jitter_fom(100e-15, 10.0).fom_db
    assert pll_jitter_fom(50e-15, 10.0).fom_db == pytest.approx(
        base - 20 * math.log10(2), abs=1e-9)
    assert pll_jitter_fom(100e-15, 5.0).fom_db == pytest.approx(
        base - 10 * math.log10(2), abs=1e-9)


def test_fom_n_rewards_a_higher_multiplication_ratio():
    """The convention this package uses, pinned so it cannot drift: reaching
    the same jitter through a larger N is harder, so it scores better."""
    a = pll_jitter_fom(100e-15, 10.0, n=50)
    b = pll_jitter_fom(100e-15, 10.0, n=200)
    assert b.fom_n_db < a.fom_n_db
    assert a.fom_n_db == pytest.approx(a.fom_db - 10 * math.log10(50))
    assert pll_jitter_fom(100e-15, 10.0).fom_n_db is None


# ------------------------------------------------------------------ VCO

def test_vco_fom_does_not_depend_on_the_offset_inside_one_over_f_squared():
    """The property the figure exists for.  L falls 20 dB/decade here, so
    evaluating at 1 MHz and at 10 MHz must agree."""
    f0, p = 10e9, 12.0
    l_1m = -110.0
    l_10m = l_1m - 20.0                       # exactly 20 dB/decade
    a = vco_fom(f0, 1e6, p, l_dbc_hz=l_1m).fom_dbc_hz
    b = vco_fom(f0, 10e6, p, l_dbc_hz=l_10m).fom_dbc_hz
    assert a == pytest.approx(b, abs=1e-9), (a, b)


def test_vco_fom_matches_a_hand_computed_case():
    got = vco_fom(10e9, 1e6, 10.0, l_dbc_hz=-120.0).fom_dbc_hz
    # -120 - 20*log10(10000) + 10*log10(10) = -120 - 80 + 10
    assert got == pytest.approx(-190.0, abs=1e-9)


def test_the_two_phase_noise_conventions_are_both_accepted_and_differ_by_3dB():
    """Passing S_phi where L was meant is the silent 3 dB this package has
    been bitten by before; here it cannot happen unnamed."""
    l_dbc = -120.0
    s_phi = float(sphi_from_ldbc(l_dbc))
    by_l = vco_fom(10e9, 1e6, 10.0, l_dbc_hz=l_dbc).fom_dbc_hz
    by_s = vco_fom(10e9, 1e6, 10.0, sphi_rad2_hz=s_phi).fom_dbc_hz
    assert by_s == pytest.approx(by_l, abs=1e-9)
    # and had the caller handed the raw S_phi in as if it were L:
    wrong = vco_fom(10e9, 1e6, 10.0, l_dbc_hz=10 * math.log10(s_phi)).fom_dbc_hz
    assert wrong - by_l == pytest.approx(HALF_POWER_DB, abs=1e-9)


def test_fom_t_equals_fom_at_a_ten_percent_tuning_range():
    """What the /10 in the definition is for."""
    r = vco_fom(10e9, 1e6, 10.0, l_dbc_hz=-120.0, ftr_pct=10.0)
    assert r.fom_t_dbc_hz == pytest.approx(r.fom_dbc_hz, abs=1e-9)
    wider = vco_fom(10e9, 1e6, 10.0, l_dbc_hz=-120.0, ftr_pct=20.0)
    assert wider.fom_t_dbc_hz == pytest.approx(
        r.fom_dbc_hz - 20 * math.log10(2), abs=1e-9)
    assert vco_fom(10e9, 1e6, 10.0, l_dbc_hz=-120.0).fom_t_dbc_hz is None


@pytest.mark.parametrize("kwargs", [
    {"jitter_s": 0.0, "power_mw": 10.0},
    {"jitter_s": -1e-15, "power_mw": 10.0},
    {"jitter_s": 1e-13, "power_mw": 0.0},
    {"jitter_s": 1e-13, "power_mw": float("nan")},
    {"jitter_s": 1e-13, "power_mw": 10.0, "n": 0},
])
def test_pll_fom_refuses_impossible_input(kwargs):
    with pytest.raises(ValueError):
        pll_jitter_fom(**kwargs)


@pytest.mark.parametrize("kwargs", [
    {"f0": 0.0, "offset_hz": 1e6, "power_mw": 10.0, "l_dbc_hz": -120.0},
    {"f0": 1e9, "offset_hz": 0.0, "power_mw": 10.0, "l_dbc_hz": -120.0},
    {"f0": 1e9, "offset_hz": 1e6, "power_mw": -1.0, "l_dbc_hz": -120.0},
    {"f0": 1e9, "offset_hz": 1e6, "power_mw": 10.0},                  # neither
    {"f0": 1e9, "offset_hz": 1e6, "power_mw": 10.0,
     "l_dbc_hz": -120.0, "sphi_rad2_hz": 1e-12},                      # both
    {"f0": 1e9, "offset_hz": 1e6, "power_mw": 10.0,
     "l_dbc_hz": float("inf")},
    {"f0": 1e9, "offset_hz": 1e6, "power_mw": 10.0, "l_dbc_hz": -120.0,
     "ftr_pct": 0.0},
])
def test_vco_fom_refuses_impossible_input(kwargs):
    with pytest.raises(ValueError):
        vco_fom(**kwargs)
