"""GUI-support logic: field enumeration, overrides, calibrator rebuild."""
import pytest

from pllsim import presets
from pllsim.guiutil import (apply_overrides, enumerate_fields, fmt_value,
                            make_pll, osc_bank_report, parse_value)


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


def test_unknown_field_rejected():
    pll = presets.ALL_PRESETS["cppll_19p2m_4p8g"]()
    with pytest.raises(KeyError):
        apply_overrides(pll.cfg, {"osc.nonexistent": "1"})
