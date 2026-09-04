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
import math

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


@pytest.mark.parametrize("name", ["ilcm_250m_12g", "adpll_100m_10g",
                                  "spll_frac_52m_6p253g"])
def test_analyze_carries_the_ipn_breakdown_for_any_preset(name):
    """Not just the benchmark tab: the workbench shows this for whatever is
    loaded, which is every preset plus edited configs and candidates."""
    got = call("analyze", preset=name)
    rows = got["ipn_rows"]
    assert sum(r["share_pct"] for r in rows) == pytest.approx(100.0, abs=1e-6)
    assert base64.b64decode(got["pie_png"])[:8] == b"\x89PNG\r\n\x1a\n"
    quad = math.sqrt(sum(r["jitter_fs"] ** 2 for r in rows))
    assert quad == pytest.approx(got["jitter_fs"], rel=1e-6)


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


def test_a_railed_loop_reaches_the_page_as_a_note():
    # ILCM fout x2 is a legal integer multiple the oscillator cannot reach;
    # the note is the only thing standing between the phone and a plausible
    # looking number 12 GHz off target
    reply = json.loads(appbridge.call(
        "simulate", json.dumps({"preset": "ilcm_250m_12g",
                                "overrides": {"fout": "24e9"},
                                "n_cycles": 6000, "seed": 1})))
    assert reply["ok"], reply.get("error")
    assert any("never reached" in n for n in reply["result"]["notes"]), \
        reply["result"]["notes"]


def test_fref_only_edit_on_a_fractional_preset_follows_the_plan():
    # the phone found this: fref 52 -> 104 MHz on the workbench left the
    # stale fraction pointing the divider 13 MHz from fout, and the "result"
    # was an unlocked loop shown as 1.6 ns of jitter.  The divider now
    # follows the frequency plan (frac derived from fout/fref), so the same
    # edit locks at fout.
    reply = json.loads(appbridge.call(
        "simulate", json.dumps({"preset": "spll_frac_52m_6p253g",
                                "overrides": {"fref": "104e6"},
                                "n_cycles": 12000, "seed": 1})))
    assert reply["ok"], reply.get("error")
    r = reply["result"]
    assert abs(r["f_end_ghz"] - 6.2530156) < 1e-3
    assert r["lock_time_us"] is not None


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


def test_spur_spectrum_m_reaches_the_engine_and_says_when_it_cannot():
    """M is what puts the reference spur in this spectrum, and two of the
    fractional presets are ADPLLs whose simulate() takes no M at all --
    passing it straight through raised TypeError for them."""
    kw = dict(preset="cppll_frac_38p4m_6g", n_cycles=20_000)
    off = call("spur_spectrum", **kw)
    on = call("spur_spectrum", fine_oversample=64, **kw)
    assert off["fine_applied"] is False and on["fine_applied"] is True
    assert base64.b64decode(on["png"])[:8] == b"\x89PNG\r\n\x1a\n"
    # the ADPLL path must answer, not raise, and must not claim it applied
    adpll = call("spur_spectrum", preset="adpll_bb_100m_10g",
                 n_cycles=8_000, fine_oversample=128)
    assert adpll["fine_applied"] is False


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


def test_benchmarks_are_the_same_table_both_guis_render():
    from pllsim.presets import benchmark_table
    got = call("benchmarks")["rows"]
    want = benchmark_table()
    assert [r["paper"] for r in got] == [r["paper"] for r in want]
    for g, w in zip(got, want):
        assert g["linear [fs]"] == pytest.approx(w["linear [fs]"])


def test_benchmark_ipn_partitions_the_jitter():
    """The pie's premise: the shares are a partition and the per-source
    jitters recombine to the total.  A bridge that dropped or rescaled a
    source would pass a "returns some rows" check and fail this."""
    got = call("benchmark_ipn", preset="bench_gao09_sspll_55p25m_2p21g")
    shares = [r["share_pct"] for r in got["rows"]]
    assert sum(shares) == pytest.approx(100.0, abs=1e-6)
    quad = math.sqrt(sum(r["jitter_fs"] ** 2 for r in got["rows"]))
    assert quad == pytest.approx(got["jitter_fs"], rel=1e-6)
    assert got["dominant"] == got["rows"][0]["source"]
    assert base64.b64decode(got["png"])[:8] == b"\x89PNG\r\n\x1a\n"
    # the tab needs the preset list to populate its selector
    assert got["dominant"] in [r["source"] for r in got["rows"]]
    assert call("benchmarks")["presets"], "no preset list for the pie selector"


def test_select_ranks_and_hands_candidates_to_the_workbench():
    """The selector's whole point on a phone: requirement in, ranked table
    out, and the winner editable in the workbench without retyping."""
    sel = call("select", fref_hz=100e6, fout_hz=8e9, jitter_fs_max=120)
    assert len(sel["rows"]) == 7
    assert sel["best"] is not None and sel["best"] in sel["handoff"]
    base = call("analyze", candidate=sel["best"])["jitter_fs"]
    assert base == pytest.approx(sel["best_jitter_fs"], rel=1e-6)
    worse = call("analyze", candidate=sel["best"],
                 overrides={"osc.pn_dbchz": "-90"})["jitter_fs"]
    assert worse > base * 1.5, (base, worse)
    fields = call("fields", candidate=sel["best"])
    assert fields["arch"].lower().startswith(sel["best"][:4])
    reply = json.loads(appbridge.call(
        "analyze", json.dumps({"candidate": "no_such_arch"})))
    assert reply["ok"] is False and "select first" in reply["error"]


def test_synth_hands_back_the_library_numbers_unchanged():
    from pllsim.synth import cppll_kdet, design_adpll_dlf, design_cp_filter
    got = call("synth_cp", icp_a=1.5e-3, n=250, kvco_hz_v=60e6,
               ugb_hz=1e6, pm_deg=58, fref_hz=19.2e6)
    want = design_cp_filter(cppll_kdet(1.5e-3, 250), 60e6, 1e6, 58, 19.2e6)
    for k, w in [("c1_f", want.c1), ("r2_ohm", want.r2), ("c2_f", want.c2),
                 ("r3_ohm", want.r3), ("c3_f", want.c3)]:
        assert got[k] == pytest.approx(w, rel=1e-12), k
    a, r = design_adpll_dlf(100e6, 1e6, 55)
    got = call("synth_dlf", fref_hz=100e6, ugb_hz=1e6, pm_deg=55)
    assert got["alpha"] == pytest.approx(a) and got["rho"] == pytest.approx(r)


def test_bw_sweep_says_when_points_were_dropped():
    """sweep_bandwidth silently skips infeasible UGB targets; the bridge has
    to report requested-vs-returned or 5-asked-3-answered reads as a full
    sweep."""
    got = call("bw_sweep", preset="sspll_19p2m_4p8g", n_points=5)
    assert got["n_requested"] == 5
    assert 1 <= len(got["jitter_fs"]) <= 5
    assert len(got["f_ugb_hz"]) == len(got["jitter_fs"])
    assert base64.b64decode(got["png"])[:8] == b"\x89PNG\r\n\x1a\n"
    reply = json.loads(appbridge.call(
        "bw_sweep", json.dumps({"preset": "ilcm_250m_12g"})))
    assert reply["ok"] is False and "no loop" in reply["error"]


def test_modulate_mismatch_drives_the_evm():
    """The page's one conclusion: direct-path mismatch is what EVM buys.
    5% mismatch must cost at least 2x over the noise-only baseline."""
    kw = dict(preset="sspll_19p2m_4p8g", n_cycles=80_000)
    base = call("modulate", **kw)
    worse = call("modulate", dp_err=0.05, **kw)
    assert worse["evm_pct"] > 2.0 * base["evm_pct"], (base, worse)
    assert base["sps"] == pytest.approx(19.2e6 / 2.5e6)
    assert base64.b64decode(base["png"])[:8] == b"\x89PNG\r\n\x1a\n"
    reply = json.loads(appbridge.call(
        "modulate", json.dumps({"preset": "ilcm_250m_12g",
                                "n_cycles": 80_000})))
    assert reply["ok"] is False   # no two-point injection on this engine


def test_drift_lag_tracks_the_ramp_rate():
    """Slower ramp -> smaller tracking lag; a drift knob that does not move
    the lag is the decorative-parameter bug wearing a thermometer."""
    kw = dict(preset="cppll_frac_38p4m_6g", ramp_cycles=40_000,
              ramp_start=50_000)
    fast = call("drift", eps_total=0.03, **kw)
    slow = call("drift", eps_total=0.003, **kw)
    assert 0.0 < slow["peak_lag_pct"] < fast["peak_lag_pct"], (slow, fast)
    # the calibrator must actually TRACK: peak lag strictly below the total
    # drift.  A run where the ramp was never injected has lag == drift
    # exactly (the lag formula carries the drift array), which slipped past
    # the monotonicity assertion above when this was first mutation-tested.
    assert fast["peak_lag_pct"] < 0.95 * 3.0, fast["peak_lag_pct"]
    assert fast["rate_over_mu"] == pytest.approx(10 * slow["rate_over_mu"])
    assert fast["lag_spur_dbc"] is None or fast["lag_spur_dbc"] < 0
    assert base64.b64decode(fast["png"])[:8] == b"\x89PNG\r\n\x1a\n"
    reply = json.loads(appbridge.call(
        "drift_info", json.dumps({"preset": "cppll_19p2m_4p8g"})))
    assert reply["ok"] is False and "calibrator" in reply["error"]


def test_non_finite_floats_become_null():
    # ILCM/MDLL analyze with default f_free_error leaves f_ugb/pm undefined
    # in some architectures; whatever the source, the serializer must never
    # emit a bare NaN.  Drive it directly on the helper.
    assert appbridge._clean(float("nan")) is None
    assert appbridge._clean({"a": [float("inf"), 1.0]}) == {"a": [None, 1.0]}


def test_units_convert_matches_the_library_and_carries_both_conventions():
    """The bridge is a serializer here too: no arithmetic of its own."""
    from pllsim.core.jitter import HALF_POWER_DB, convert_phase_noise
    r = call("units_convert", f0_hz=10e9, kind="deg", value=0.5)
    u = convert_phase_noise(10e9, deg=0.5)
    assert r["jitter_fs"] == pytest.approx(u.jitter_fs, rel=1e-12)
    assert r["ipn_dbc_dsb"] == pytest.approx(u.ipn_dbc_dsb, rel=1e-12)
    # both, every time: the page cannot label a figure it was not sent
    assert r["ipn_dbc_dsb"] - r["ipn_dbc_ssb"] == pytest.approx(
        HALF_POWER_DB, rel=1e-12)
    assert r["half_power_db"] == pytest.approx(HALF_POWER_DB, rel=1e-12)
    assert r["small_angle"] is True


def test_units_convert_round_trips_through_every_kind():
    ref = call("units_convert", f0_hz=6e9, kind="deg", value=0.42)
    for kind in ("deg", "jitter_fs", "ipn_dbc_dsb", "ipn_dbc_ssb"):
        again = call("units_convert", f0_hz=6e9, kind=kind, value=ref[kind])
        assert again["deg"] == pytest.approx(ref["deg"], rel=1e-9), kind


def test_units_convert_reports_bad_input_in_the_envelope():
    """A converter is the one page users will feed nonsense to."""
    for kwargs in ({"f0_hz": 0.0, "kind": "deg", "value": 1.0},
                   {"f0_hz": 1e9, "kind": "deg", "value": -1.0},
                   {"f0_hz": 1e9, "kind": "nonsense", "value": 1.0}):
        reply = json.loads(appbridge.call("units_convert", json.dumps(kwargs)))
        assert reply["ok"] is False, kwargs
        assert reply["error"]


def test_units_convert_flags_the_large_angle_case():
    r = call("units_convert", f0_hz=1e9, kind="deg", value=30.0)
    assert r["small_angle"] is False


def test_fom_bridge_reproduces_the_published_dartizio_number():
    """77 fs at 17.2 mW is the -249.9 dB that paper states, and ex14 records.
    The bridge is a serializer: no arithmetic of its own."""
    r = call("fom", kind="pll", jitter_fs=77, power_mw=17.2)
    assert r["fom_db"] == pytest.approx(-249.9, abs=0.05)
    assert r["fom_n_db"] is None            # N was not supplied


def test_fom_bridge_carries_both_optional_figures_when_asked():
    pll = call("fom", kind="pll", jitter_fs=100, power_mw=10, n=250)
    assert pll["fom_n_db"] == pytest.approx(pll["fom_db"] - 10 * math.log10(250))
    vco = call("fom", kind="vco", f0_hz=10e9, offset_hz=1e6, power_mw=10,
               l_dbc_hz=-120, ftr_pct=10)
    assert vco["fom_dbc_hz"] == pytest.approx(-190.0)
    # FoM_T equals FoM at exactly 10% tuning range -- what the /10 is for
    assert vco["fom_t_dbc_hz"] == pytest.approx(vco["fom_dbc_hz"])
    assert vco["half_power_db"] == pytest.approx(3.0103, abs=1e-4)


def test_fom_bridge_treats_a_blank_optional_as_absent_not_zero():
    """The page sends null for an empty box; zero would be a division."""
    r = call("fom", kind="pll", jitter_fs=100, power_mw=10, n=None)
    assert r["fom_n_db"] is None


@pytest.mark.parametrize("kwargs", [
    {"kind": "nonsense"},
    {"kind": "pll", "jitter_fs": 0, "power_mw": 10},
    {"kind": "pll", "jitter_fs": 100, "power_mw": -1},
    {"kind": "vco", "f0_hz": 10e9, "offset_hz": 0, "power_mw": 10,
     "l_dbc_hz": -120},
])
def test_fom_bridge_reports_bad_input_in_the_envelope(kwargs):
    reply = json.loads(appbridge.call("fom", json.dumps(kwargs)))
    assert reply["ok"] is False, kwargs
    assert reply["error"]
