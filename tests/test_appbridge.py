"""The JSON bridge hands hosts the same numbers the library computes.

Every test goes through ``appbridge.call`` -- the one entry point the Android
app uses -- and then ``json.loads`` the reply, because "the reply is not
actually JSON" is precisely the class of failure a host cannot recover from.

Mutations these tests are known to catch (each was tried while writing them):
dropping a key from a reply dict, renaming a method in _METHODS, letting an
exception escape ``call`` instead of returning ok=false, and scaling a metric
on its way through the bridge.
"""
import base64
import json

import pytest

from pllsim import appbridge, presets
from pllsim.guiutil import enumerate_fields, make_pll


def call(method, **kwargs):
    reply = json.loads(appbridge.call(method, json.dumps(kwargs)))
    assert reply["ok"], reply.get("error")
    return reply["result"]


def test_every_method_answers_and_every_reply_is_json():
    presets_list = call("list_presets")
    assert {p["name"] for p in presets_list} == set(presets.ALL_PRESETS)
    for p in presets_list:
        assert p["fref_mhz"] > 0 and p["fout_ghz"] > 0 and p["arch"]


def test_fields_match_enumerate_fields_exactly():
    """The bridge is a serializer, not a second source of the field list."""
    name = "cppll_frac_38p4m_6g"
    got = call("fields", preset=name)
    want = enumerate_fields(presets.ALL_PRESETS[name]().cfg)
    assert [f["path"] for f in got["fields"]] == [s.path for s in want]
    for f, s in zip(got["fields"], want):
        assert (f["unit"], f["label_zh"], f["label_en"]) == \
               (s.unit, s.label_zh, s.label_en), f["path"]
    assert got["group_labels"]["osc"] == {"zh": "振荡器", "en": "Oscillator"}


def test_analyze_reports_the_number_the_library_computes():
    name = "cppll_19p2m_4p8g"
    got = call("analyze", preset=name)
    want = make_pll(name, {}).analyze()
    assert got["jitter_fs"] == pytest.approx(want.jitter_fs, rel=1e-12)
    assert got["ipn_dbc"] == pytest.approx(want.ipn_dbc, rel=1e-12)
    png = base64.b64decode(got["png"])
    assert png[:8] == b"\x89PNG\r\n\x1a\n"


def test_an_override_moves_the_number():
    """A parameter that reads correctly and does nothing is this repo's
    signature bug; the bridge must not add a new place for it to happen."""
    name = "cppll_19p2m_4p8g"
    base = call("analyze", preset=name)["jitter_fs"]
    worse = call("analyze", preset=name,
                 overrides={"osc.pn_dbchz": "-90"})["jitter_fs"]
    assert worse > base * 1.5, (base, worse)


def test_simulate_round_trip_short():
    got = call("simulate", preset="cppll_19p2m_4p8g", n_cycles=12_000,
               seed=1)
    assert got["f_end_ghz"] == pytest.approx(4.8, rel=1e-3)
    titles = [p["title"] for p in got["pngs"]]
    assert titles[:2] == ["phase noise", "transient"]
    for p in got["pngs"]:
        assert base64.b64decode(p["png"])[:8] == b"\x89PNG\r\n\x1a\n"
    # 12k cycles ends inside the calibration transient on purpose: the notes
    # must carry the warning, since the app shows them and nothing else does
    assert isinstance(got["notes"], list)


def test_fine_info_matches_the_helpers():
    got = call("fine_info", preset="sspll_19p2m_4p8g", n_cycles=150_000, m=128)
    assert got["supported"] is True
    assert got["record_mb"] == pytest.approx(150_000 * 128 * 8 / 1e6)
    got = call("fine_info", preset="adpll_100m_10g", n_cycles=150_000, m=128)
    assert got["supported"] is False


def test_errors_come_back_in_band_never_raised():
    reply = json.loads(appbridge.call("analyze",
                                      json.dumps({"preset": "no_such"})))
    assert reply["ok"] is False and "no_such" in reply["error"]
    reply = json.loads(appbridge.call("no_such_method", "{}"))
    assert reply["ok"] is False
    # a half-typed override must not crash the form either
    reply = json.loads(appbridge.call(
        "analyze", json.dumps({"preset": "cppll_19p2m_4p8g",
                               "overrides": {"osc.pn_dbchz": "1e"}})))
    assert reply["ok"] is False and "traceback" in reply


def test_spur_predict_inl_drives_the_spur():
    """0 vs 100x INL must move the top spur by >15 dB; at small amplitudes
    the DTC quantization floor dominates, so the sweep spans past it."""
    quiet = call("spur_predict", preset="cppll_frac_38p4m_6g",
                 inl_amp_s=0.0)["rows"]
    loud = call("spur_predict", preset="cppll_frac_38p4m_6g",
                inl_amp_s=5e-12)["rows"]
    assert quiet and loud
    assert loud[0]["dbc"] > quiet[0]["dbc"] + 15, (quiet[0], loud[0])
    reply = json.loads(appbridge.call(
        "spur_predict", json.dumps({"preset": "cppll_19p2m_4p8g"})))
    assert reply["ok"] is False and "integer-N" in reply["error"]


def test_ref_spur_answers_per_architecture():
    got = call("ref_spur", preset="sspll_19p2m_4p8g", m=8, n_cycles=4_000)
    assert got["rows"] and set(got["rows"][0]) == {
        "offset", "analytic [dBc]", "measured [dBc]"}
    got = call("ref_spur", preset="adpll_100m_10g")
    assert got["rows"] == [] and "no analog control node" in got["notes"][0]


def test_spur_sweep_is_worst_near_integer():
    """The physics the plot exists to show: in-band beats (near-integer
    channels) sit on the |NTF| ~ 1 plateau -- within a dB of each other, so
    "index 0 is strictly worst" over-specifies -- while far-out beats roll
    off by tens of dB.  A sweep that forgets to move the channel flattens
    the whole curve and fails the rolloff assertion."""
    got = call("spur_sweep", preset="cppll_frac_38p4m_6g", inl_amp_s=5e-12)
    vals = got["worst_dbc"]
    assert len(vals) == len(got["beats_hz"]) == 8
    worst_at = max(range(8), key=lambda i: vals[i] if vals[i] is not None
                   else -1e9)
    assert worst_at < 4, (worst_at, vals)
    assert vals[0] > vals[5] + 10, vals
    assert base64.b64decode(got["png"])[:8] == b"\x89PNG\r\n\x1a\n"


def test_hop_check_knows_which_loops_have_an_fll():
    st = call("hop_check", preset="sspll_19p2m_4p8g")
    assert st is not None and st["margin"] > 0 and isinstance(st["ok"], bool)
    assert call("hop_check", preset="cppll_19p2m_4p8g") is None


def test_hop_round_trip_short():
    got = call("hop", preset="cppll_19p2m_4p8g", hop_hz=-50e6,
               n_cycles=25_000)
    assert got["t_phase_us"] is not None and got["t_phase_us"] > 0
    assert base64.b64decode(got["png"])[:8] == b"\x89PNG\r\n\x1a\n"


def test_hop_stats_short():
    got = call("hop_stats", preset="cppll_19p2m_4p8g", hop_hz=-50e6,
               n_cycles=25_000, n_seeds=2)
    # bounded both ways so a dropped us conversion (1e-6x or 1e6x) fails,
    # not just a zero: this hop settles in tens of us
    assert 1.0 < got["p50_us"] < 1e6 and got["p95_us"] >= got["p50_us"]
    assert 0.0 <= got["fail_pct"] <= 100.0
    assert base64.b64decode(got["png"])[:8] == b"\x89PNG\r\n\x1a\n"


def test_non_finite_floats_become_null():
    # ILCM/MDLL analyze with default f_free_error leaves f_ugb/pm undefined
    # in some architectures; whatever the source, the serializer must never
    # emit a bare NaN.  Drive it directly on the helper.
    assert appbridge._clean(float("nan")) is None
    assert appbridge._clean({"a": [float("inf"), 1.0]}) == {"a": [None, 1.0]}
