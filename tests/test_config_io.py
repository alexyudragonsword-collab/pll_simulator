"""Config save/load: a file is a preset plus its edited fields, exactly.

Until 2026-09 the three GUIs had no way to keep an edit: the form vanished
with the process.  The contract here is bit-exact round trip and loud
refusal of anything the code cannot rebuild.
"""
import json

import pytest

from pllsim import presets
from pllsim.guiutil import (
    CONFIG_FORMAT,
    config_from_dict,
    config_from_json,
    config_to_dict,
    config_to_json,
    enumerate_fields,
    make_pll,
)


def _fields(pll):
    return {s.path: s.value for s in enumerate_fields(pll.cfg)}


@pytest.mark.parametrize("name", list(presets.ALL_PRESETS))
def test_every_preset_round_trips_bit_exactly(name):
    pll = presets.ALL_PRESETS[name]()
    text = config_to_json(pll, name)
    back, back_name = config_from_json(text)
    assert back_name == name and type(back) is type(pll)
    assert _fields(back) == _fields(pll)          # exact, not approx


def test_an_edit_is_what_the_file_keeps():
    pll = make_pll("cppll_19p2m_4p8g", {"osc.pn_dbchz": "-118", "cp.icp": "1.2m"})
    d = config_to_dict(pll, "cppll_19p2m_4p8g")
    assert d["fields"]["osc.pn_dbchz"] == -118.0 and d["fields"]["cp.icp"] == 1.2e-3
    back, _ = config_from_dict(d)
    assert back.cfg.osc.pn_dbchz == -118.0 and back.cfg.cp.icp == 1.2e-3
    assert back.analyze().jitter_fs == pytest.approx(pll.analyze().jitter_fs)


def test_the_file_says_what_wrote_it():
    d = config_to_dict(presets.ALL_PRESETS["ilcm_250m_12g"](), "ilcm_250m_12g")
    assert d["format"] == CONFIG_FORMAT and d["arch"] == "ILCM" and d["pllsim"]
    assert isinstance(json.dumps(d), str)          # JSON-native throughout


def test_optional_and_tuple_fields_survive():
    pll = make_pll("cppll_19p2m_4p8g", {"osc.v_min": "0", "osc.v_max": "1.2",
                                        "int_band": "(10k, 40M)"})
    back, _ = config_from_json(config_to_json(pll, "cppll_19p2m_4p8g"))
    assert (back.cfg.osc.v_min, back.cfg.osc.v_max) == (0.0, 1.2)
    assert back.cfg.int_band == (1e4, 4e7)
    d = config_to_dict(presets.ALL_PRESETS["cppll_19p2m_4p8g"](), "cppll_19p2m_4p8g")
    assert d["fields"]["osc.v_min"] is None       # unset stays unset, not 0


def test_unknown_preset_and_unknown_field_are_refused_with_the_list():
    d = config_to_dict(presets.ALL_PRESETS["spll_100m_8g"](), "spll_100m_8g")
    d["preset"] = "spll_from_the_future"
    with pytest.raises(ValueError, match="unknown preset"):
        config_from_dict(d)
    d["preset"] = "spll_100m_8g"
    d["fields"]["osc.kvco_hz_v"] = 6e7              # a renamed field, say
    with pytest.raises(ValueError, match=r"osc\.kvco_hz_v"):
        config_from_dict(d)


def test_a_foreign_json_is_not_a_config():
    with pytest.raises(ValueError, match="not a pllsim config"):
        config_from_json('{"fref": 1e6}')


def test_a_file_that_breaks_the_frequency_plan_is_refused_on_load():
    """The same construction-time guard the forms have: fref alone on a
    fractional preset leaves the divider locking MHz away from fout."""
    d = config_to_dict(presets.ALL_PRESETS["cppll_frac_38p4m_6g"](), "cppll_frac_38p4m_6g")
    d["fields"]["fref"] = 2 * d["fields"]["fref"]
    back, _ = config_from_dict(d)             # frac is re-derived: it loads
    assert back.cfg.frac.frac == pytest.approx((back.cfg.fout / back.cfg.fref) % 1)
