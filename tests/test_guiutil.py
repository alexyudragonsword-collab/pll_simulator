"""GUI-support logic: field enumeration, overrides, calibrator rebuild."""
import pytest

from pllsim import presets
from pllsim.guiutil import (apply_overrides, enumerate_fields, fmt_value,
                            make_pll, parse_value)


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


def test_unknown_field_rejected():
    pll = presets.ALL_PRESETS["cppll_19p2m_4p8g"]()
    with pytest.raises(KeyError):
        apply_overrides(pll.cfg, {"osc.nonexistent": "1"})
