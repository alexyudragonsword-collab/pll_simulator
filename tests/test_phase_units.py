"""The degree / jitter / dBc converter.

Three properties are worth testing and one of them is the whole point:

* every entry point lands on the same five numbers (round trips),
* the two dBc conventions differ by exactly 3.0103 dB, never by accident,
* and the SSB figure agrees with what `analyze()` reports for a real preset
  -- which is what makes the converter usable *beside* the bench pages
  rather than a second opinion that quietly disagrees with them.
"""
from __future__ import annotations

import math

import pytest

from pllsim import presets
from pllsim.core.jitter import (
    HALF_POWER_DB,
    SMALL_ANGLE_RAD,
    convert_phase_noise,
)

F0 = 10e9


def test_the_worked_example_by_hand():
    """One case computed independently, so the round trips below cannot all
    be consistently wrong together."""
    u = convert_phase_noise(F0, deg=0.810)
    rad = 0.810 * math.pi / 180.0                    # 0.014137 rad
    assert u.rad == pytest.approx(rad, rel=1e-12)
    assert u.jitter_s == pytest.approx(rad / (2 * math.pi * F0), rel=1e-12)
    assert u.jitter_fs == pytest.approx(225.0, abs=0.5)
    assert u.ipn_dbc_dsb == pytest.approx(-36.99, abs=0.01)
    assert u.ipn_dbc_ssb == pytest.approx(-40.00, abs=0.01)


@pytest.mark.parametrize("field", ["rad", "deg", "jitter_s", "jitter_fs",
                                   "ipn_dbc_dsb", "ipn_dbc_ssb"])
def test_every_entry_point_reproduces_the_same_state(field):
    ref = convert_phase_noise(F0, deg=0.427271)
    value = getattr(ref, field)
    again = convert_phase_noise(F0, **{field: value})
    for k in ("rad", "deg", "jitter_s", "ipn_dbc_dsb", "ipn_dbc_ssb"):
        assert getattr(again, k) == pytest.approx(getattr(ref, k), rel=1e-9), k


def test_the_two_conventions_differ_by_exactly_half_the_power():
    u = convert_phase_noise(F0, deg=1.0)
    assert u.ipn_dbc_dsb - u.ipn_dbc_ssb == pytest.approx(HALF_POWER_DB, rel=1e-12)
    assert HALF_POWER_DB == pytest.approx(3.0103, abs=1e-4)


def test_reading_a_dbc_figure_under_the_wrong_convention_costs_sqrt_two():
    """The error this converter exists to prevent, pinned as a number."""
    right = convert_phase_noise(F0, ipn_dbc_ssb=-45.5587)
    wrong = convert_phase_noise(F0, ipn_dbc_dsb=-45.5587)
    assert wrong.jitter_s / right.jitter_s == pytest.approx(1 / math.sqrt(2), rel=1e-9)


def test_jitter_scales_with_the_carrier_but_degrees_and_dbc_do_not():
    a = convert_phase_noise(1e9, deg=0.5)
    b = convert_phase_noise(10e9, deg=0.5)
    assert b.jitter_s == pytest.approx(a.jitter_s / 10.0, rel=1e-12)
    assert b.ipn_dbc_dsb == pytest.approx(a.ipn_dbc_dsb, rel=1e-12)
    assert b.deg == pytest.approx(a.deg, rel=1e-12)


def test_six_db_halves_the_phase():
    a = convert_phase_noise(F0, ipn_dbc_dsb=-40.0)
    b = convert_phase_noise(F0, ipn_dbc_dsb=-40.0 - 20.0 * math.log10(2.0))
    assert b.deg == pytest.approx(a.deg / 2.0, rel=1e-9)


def test_the_small_angle_flag_marks_where_dbc_stops_meaning_this():
    assert convert_phase_noise(F0, rad=SMALL_ANGLE_RAD * 0.99).small_angle
    assert not convert_phase_noise(F0, rad=SMALL_ANGLE_RAD * 1.01).small_angle
    # 30 degrees is far outside it, and a form that says nothing there is
    # reporting a number it cannot support
    assert not convert_phase_noise(F0, deg=30.0).small_angle


@pytest.mark.parametrize("kwargs, why", [
    ({}, "none"),
    ({"deg": 1.0, "jitter_fs": 100.0}, "two"),
    ({"deg": 0.0}, "zero maps to -inf dBc"),
    ({"deg": -1.0}, "negative"),
    ({"deg": float("nan")}, "not finite"),
])
def test_ambiguous_or_degenerate_input_is_refused(kwargs, why):
    with pytest.raises(ValueError):
        convert_phase_noise(F0, **kwargs)


@pytest.mark.parametrize("f0", [0.0, -1e9, float("inf"), float("nan")])
def test_a_carrier_that_is_not_a_frequency_is_refused(f0):
    with pytest.raises(ValueError):
        convert_phase_noise(f0, deg=1.0)


@pytest.mark.parametrize("name", sorted(presets.ALL_PRESETS))
def test_the_converter_agrees_with_analyze_on_every_preset(name):
    """The cross-check that matters.

    `AnalysisResult.ipn_dbc` is the SSB figure and `jitter_fs` comes from the
    same integral, so feeding one back through the converter at that preset's
    carrier must reproduce the other.  If these ever disagree, one of the two
    paths has picked up a stray factor of two -- and this is the test that
    says which.
    """
    ar = presets.ALL_PRESETS[name]().analyze()
    u = convert_phase_noise(ar.f0, ipn_dbc_ssb=ar.ipn_dbc)
    assert u.jitter_fs == pytest.approx(ar.jitter_fs, rel=1e-9)
