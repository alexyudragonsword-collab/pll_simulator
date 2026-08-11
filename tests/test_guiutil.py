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
    assert fmt_value(19.2e6) == "1.92e+07"
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
