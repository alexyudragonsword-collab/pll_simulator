"""GUI-support logic: field enumeration, overrides, calibrator rebuild."""
import inspect

import pytest

from pllsim import presets
from pllsim.guiutil import (
    apply_overrides,
    enumerate_fields,
    fine_oversample_note,
    fine_record_mb,
    fmt_value,
    make_pll,
    osc_bank_report,
    parse_value,
    ref_spur_comparison,
    simulate_kwargs,
    supports_fine,
)


def test_every_preset_enumerates():
    for nm in presets.ALL_PRESETS:
        pll = presets.ALL_PRESETS[nm]()
        specs = enumerate_fields(pll.cfg)
        paths = [s.path for s in specs]
        assert "fref" in paths and "fout" in paths
        assert len(paths) == len(set(paths))          # no duplicates
        assert len(specs) > 10


def test_override_roundtrip_changes_analyze():
    pll = make_pll("spll_frac_52m_6p253g")
    j0 = pll.analyze().jitter_fs
    pll2 = make_pll("spll_frac_52m_6p253g",
                    {"osc.pn_dbchz": "-112", "int_band": "(10e3, 10e6)"})
    assert pll2.cfg.osc.pn_dbchz == -112.0
    assert pll2.cfg.int_band == (10e3, 10e6)
    assert pll2.analyze().jitter_fs > j0              # worse VCO -> more jitter


def test_calibrator_rebuilt_fresh():
    pll = make_pll("spll_frac_52m_6p253g", {"frac.dtc_cal.mu": "1e-5"})
    cal = pll.cfg.frac.dtc_cal
    assert cal.mu == 1e-5
    assert cal.n == 0 and cal.value == 1.0            # fresh state
    # runs end-to-end after the rebuild
    sim = pll.simulate(4_000, seed=1)
    assert sim.freq_out[-1] > 0


def test_parse_and_format():
    assert parse_value("1e-12", "float") == 1e-12
    assert parse_value("64", "int") == 64
    assert parse_value("(1e3, 4e7)", "tuple") == (1e3, 4e7)
    assert fmt_value(19.2e6) == "19.2M"          # engineering notation since 2026-09
    assert parse_value(fmt_value((1e3, 4e7)), "tuple") == (1e3, 4e7)


def test_optional_fields_are_editable_and_blank_means_none():
    """v_min/v_max are None in every preset — the forms must still show them."""
    pll = presets.ALL_PRESETS["cppll_19p2m_4p8g"]()
    specs = {s.path: s for s in enumerate_fields(pll.cfg)}
    for p in ("osc.v_min", "osc.v_max", "cp.noise_a2hz"):
        assert p in specs, f"{p} invisible to the form"
        assert specs[p].value is None and specs[p].optional
        assert specs[p].kind == "float"
        assert fmt_value(specs[p].value) == ""     # blank box, not "None"
    # a sub-config cannot be typed into a text box, so it stays out
    assert "frac" not in specs and "tdc" not in specs
    assert parse_value("", "float") is None
    # blanking a required field is an error, not a silent None
    with pytest.raises(ValueError):
        apply_overrides(pll.cfg, {"fref": " "})


def test_control_voltage_range_reaches_the_model():
    """The GUI path must actually clamp: a railed band cannot reach fout."""
    pll = make_pll("cppll_19p2m_4p8g",
                   {"osc.v_min": "0", "osc.v_max": "0.5"})
    assert pll.cfg.osc.v_max == 0.5
    assert pll.cfg.osc.freq_law(5.0) == pll.cfg.osc.freq_law(0.5)  # clamped
    rows = osc_bank_report(pll.cfg)
    assert rows and any("reachable" in name for name, _zh, _v in rows)
    # unlimited by default -> nothing to report
    assert osc_bank_report(presets.ALL_PRESETS["cppll_19p2m_4p8g"]().cfg) == []


def test_band_bank_gap_is_reported():
    pll = make_pll("cppll_19p2m_4p8g",
                   {"osc.v_min": "0", "osc.v_max": "1", "osc.n_bands": "8",
                    "osc.band_step_hz": "300e6"})
    assert not pll.cfg.osc.band_bank_is_continuous()
    rows = dict((name, val) for name, _zh, val in osc_bank_report(pll.cfg))
    assert "GAP" in rows["band overlap"]


def test_simulate_kwargs_bind_to_every_engine():
    """The GUI's Run simulate must not hand an engine a keyword it lacks."""
    for nm in presets.ALL_PRESETS:
        pll = presets.ALL_PRESETS[nm]()
        kw = simulate_kwargs(pll, seed=1, f_start_offset=1e6,
                             dtc_gain_init_error=0.02)
        # raises TypeError on any stray keyword, without running the sim
        inspect.signature(type(pll).simulate).bind(pll, 1000, **kw)


def test_fine_oversample_is_only_offered_where_it_exists():
    """ADPLL has no analog control node to sample inside the period."""
    assert supports_fine(presets.cppll_19p2m_4p8g())
    assert supports_fine(presets.mdll_150m_2p4g())
    assert not supports_fine(presets.adpll_100m_10g())
    kw = simulate_kwargs(presets.adpll_100m_10g(), fine_oversample=64)
    assert "fine_oversample" not in kw


def test_zero_leaves_the_engine_default_alone():
    """0 is not 1: ILCM/MDLL define their jitter figure inside the period.

    Passing 1 would quietly change what those two report, so the GUI's
    "unset" has to mean unset rather than "the lowest value on the spinbox".
    """
    assert "fine_oversample" not in simulate_kwargs(presets.mdll_150m_2p4g())
    kw = simulate_kwargs(presets.mdll_150m_2p4g(), fine_oversample=1)
    assert kw["fine_oversample"] == 1


def test_the_gui_warns_when_m_cannot_resolve_the_reset_pulse():
    """Under-resolving reads low, and reading low is the dangerous direction."""
    pll = presets.cppll_19p2m_4p8g()
    t_reset = pll.cfg.cp.t_reset
    coarse = int(0.2 / (pll.cfg.fref * t_reset))     # sub-interval >> t_reset
    fine = int(4.0 / (pll.cfg.fref * t_reset))
    assert "under-resolved" in fine_oversample_note(pll, coarse)
    assert fine_oversample_note(pll, fine) == ""
    assert fine_oversample_note(pll, 1) == ""        # M=1 records nothing fine


def test_ref_spur_comparison_matches_the_analytic_model():
    """The comparison both spur pages now offer, checked at the library level.

    A charge pump with mismatch has a real ripple, and the intra-period record
    has to find it where analyze() predicts it -- otherwise the page shows two
    numbers that disagree and the user cannot tell which to believe.
    """
    pll = presets.cppll_frac_38p4m_6g()
    pll.cfg.cp.mismatch_pct = 3.0
    rows, _ = ref_spur_comparison(pll, m=256, n_cycles=20_000)
    fund = rows[0]
    assert fund["offset"].startswith("38.4")
    got, want = float(fund["measured [dBc]"]), float(fund["analytic [dBc]"])
    assert got == pytest.approx(want, abs=1.0), rows


def test_a_sub_sampling_loop_reports_no_ripple_and_says_why():
    """Not a missing number: the gm converts the held voltage over the same
    window the loop cancels it in, so in lock it delivers no charge."""
    rows, notes = ref_spur_comparison(presets.sspll_frac_19p2m_4p806g(),
                                      m=64, n_cycles=8_000)
    assert rows and all(r["analytic [dBc]"] == "-" for r in rows)
    assert any("no analytic" in n for n in notes), notes


def test_a_digital_loop_says_it_has_no_intra_period_record():
    rows, notes = ref_spur_comparison(presets.adpll_bb_100m_10g())
    assert rows == []
    assert any("no analog control node" in n for n in notes), notes


def test_record_size_is_reported_before_it_is_allocated():
    assert fine_record_mb(150_000, 512) == pytest.approx(614.4)


def test_free_running_archs_get_their_own_start_offset_name():
    """ILCM/MDLL name it f_free_error -- the FTL corrects a free-run error."""
    for nm in ("ilcm_250m_12g", "mdll_150m_2p4g"):
        pll = presets.ALL_PRESETS[nm]()
        kw = simulate_kwargs(pll, seed=1, f_start_offset=2e6)
        assert kw["f_free_error"] == 2e6 and "f_start_offset" not in kw
        assert "dtc_gain_init_error" not in kw       # no DTC on these engines
        sim = pll.simulate(4_000, **kw)              # and it actually runs
        assert sim.freq_out[-1] > 0


def test_unknown_field_rejected():
    pll = presets.ALL_PRESETS["cppll_19p2m_4p8g"]()
    with pytest.raises(KeyError):
        apply_overrides(pll.cfg, {"osc.nonexistent": "1"})


# The divider follows the frequency plan: frac is derived from fout/fref on
# every edit, never typed.  Editing fref alone used to leave the stale
# fraction pointing the divider 13 MHz away from fout, and the unlocked loop
# read as hundreds of ps of "jitter" -- found on a phone, from the workbench,
# by doing exactly this.
@pytest.mark.parametrize("name", [
    "cppll_frac_38p4m_6g",
    "sspll_frac_19p2m_4p806g",
    "spll_frac_52m_6p253g",
    "adpll_bb_100m_10g",
])
def test_fref_edit_rederives_the_fraction(name):
    cfg0 = presets.ALL_PRESETS[name]().cfg
    new_fref = cfg0.fref * 2
    # precondition: the edit really does move the fractional part
    assert abs((cfg0.fout / new_fref) % 1.0 - cfg0.frac.frac) > 1e-6
    pll = make_pll(name, {"fref": fmt_value(new_fref)})
    assert pll.cfg.frac.frac == pytest.approx((pll.cfg.fout / new_fref) % 1.0)
    assert pll.analyze().jitter_fs > 0


def test_the_phone_scenario_locks_end_to_end():
    # fref 52 -> 104 MHz with fout held: the derived frac is 0.12515 and the
    # loop must actually lock at fout, not wander between two targets
    import numpy as np
    pll = make_pll("spll_frac_52m_6p253g", {"fref": "104e6"})
    sim = pll.simulate(20_000, seed=1)
    tail = float(np.mean(sim.freq_out[-4000:]))
    assert sim.lock_time_s is not None
    assert abs(tail - pll.cfg.fout) < pll.cfg.fref / 1000


def test_the_derived_fraction_is_not_offered_as_an_input():
    pll = presets.ALL_PRESETS["spll_frac_52m_6p253g"]()
    paths = [s.path for s in enumerate_fields(pll.cfg)]
    assert "frac.frac" not in paths
    assert "frac.dtc.t_res" in paths            # the rest of frac still edits
    with pytest.raises(KeyError):
        apply_overrides(pll.cfg, {"frac.frac": "0.3"})


def test_hand_built_mismatch_is_still_refused():
    # the config-level backstop for code that bypasses the GUI layer
    import dataclasses
    cfg = presets.ALL_PRESETS["spll_frac_52m_6p253g"]().cfg
    with pytest.raises(ValueError, match="fractional part"):
        dataclasses.replace(cfg, fref=cfg.fref * 2)


# --- bool fields --------------------------------------------------------------
# enumerate_fields skipped bools, so divider_retimed (a few-dB effect) and the
# ILCM's FTL switch were unsettable from every form: the "reads correctly and
# does nothing" class, at the form layer.

def test_bool_fields_are_offered_and_round_trip():
    specs = {s.path: s for s in enumerate_fields(
        presets.ALL_PRESETS["cppll_19p2m_4p8g"]().cfg)}
    assert specs["divider_retimed"].kind == "bool"
    assert specs["divider_retimed"].value is False
    assert fmt_value(False) == "false" and fmt_value(True) == "true"
    for txt, want in (("true", True), ("False", False), ("1", True), ("off", False)):
        assert parse_value(txt, "bool") is want
    with pytest.raises(ValueError):
        parse_value("maybe", "bool")
    assert fmt_value(0) == "0"                   # an int is not a bool


def test_a_bool_override_reaches_the_model():
    base = make_pll("cppll_19p2m_4p8g").analyze()
    pll = make_pll("cppll_19p2m_4p8g", {"divider_retimed": "true"})
    ar = pll.analyze()
    assert pll.cfg.divider_retimed is True
    assert any("retimed" in n for n in ar.notes), ar.notes
    assert ar.jitter_fs != base.jitter_fs          # the divider path is gone
    ilcm = make_pll("ilcm_250m_12g", {"ftl": "false"})
    assert ilcm.cfg.ftl is False


# --------------------------------------------------- engineering notation

def test_si_prefixes_parse_to_the_same_float_as_scientific():
    from pllsim.guiutil import parse_number
    assert parse_number("19.2M") == 19.2e6 == parse_number("1.92e7")
    assert parse_number("680p") == 6.8e-10
    assert parse_number("680pF") == 6.8e-10          # unit dropped
    assert parse_number("2ms") == 2e-3
    assert parse_number("3MHz") == 3e6 == parse_number("3 M")
    assert parse_number("100k") == 1e5 == parse_number("100K")
    assert parse_number("5u") == 5e-6 == parse_number("5µ")
    assert parse_number("-50M") == -50e6
    assert parse_number("1.5G") == 1.5e9
    assert parse_number("15.625m") == 0.015625         # exact, not 0.015625000000000001
    assert parse_number("1e-12") == 1e-12 and parse_number("2") == 2.0
    with pytest.raises(ValueError):
        parse_number("3Q")
    with pytest.raises(ValueError):
        parse_number("abc")


def test_parse_value_kinds_accept_prefixes():
    from pllsim.guiutil import parse_value
    assert parse_value("100k", "int") == 100_000
    assert parse_value("(10k, 100M)", "tuple") == (1e4, 1e8)
    assert parse_value("19.2M", "float") == 19.2e6


def test_fmt_value_is_engineering_and_round_trips():
    from pllsim.guiutil import fmt_value, parse_number
    assert fmt_value(19.2e6) == "19.2M"
    assert fmt_value(6.8e-10) == "680p"
    assert fmt_value(1e-9) == "1n"
    assert fmt_value(100e3) == "100k"
    assert fmt_value(0.15) == "0.15"                 # ratios stay plain
    assert fmt_value(2.0) == "2" and fmt_value(0.015625) == "0.015625"
    assert fmt_value(0.0) == "0" and fmt_value(-50e6) == "-50M"
    assert fmt_value((1e4, 1e8)) == "10k, 100M"
    assert fmt_value(()) == "()" and parse_value("()", "tuple") == ()   # not None
    assert fmt_value(1e-27) == "1e-27"              # below yocto: exponent form
    for v in (19.2e6, 6.8e-10, 4.8e9, 0.503, 2**-6, 1e-22, 999.9996e3, 123456.7):
        assert parse_number(fmt_value(v)) == pytest.approx(v, rel=1e-5), v


@pytest.mark.parametrize("name", list(presets.ALL_PRESETS))
def test_every_preset_field_survives_the_form_text(name):
    """What the form shows must parse back to what the config holds, to
    six significant digits -- the same contract as before, in new clothes."""
    from pllsim.guiutil import parse_value
    for s in enumerate_fields(presets.ALL_PRESETS[name]().cfg):
        if s.value is None or s.kind in ("str", "bool"):
            continue
        back = parse_value(fmt_value(s.value), s.kind)
        if s.kind == "tuple":
            assert back == pytest.approx(s.value, rel=1e-5), s.path
        else:
            assert back == pytest.approx(s.value, rel=1e-5), s.path
