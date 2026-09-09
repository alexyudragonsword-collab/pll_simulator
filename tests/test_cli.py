"""The ``pllsim`` command: the library behind argparse.

Each command is exercised through main(argv) with --json, because a table is
for eyes and JSON is what a script consumes; the numbers are checked against
the library the command wraps, so the CLI cannot drift from it.
"""
import json

import pytest

from pllsim import presets
from pllsim.cli import main
from pllsim.guiutil import make_pll


def _run(capsys, *argv):
    rc = main(list(argv))
    out = capsys.readouterr()
    return rc, out.out, out.err


def test_presets_lists_every_preset(capsys):
    rc, out, _ = _run(capsys, "presets", "--json")
    assert rc == 0
    rows = json.loads(out)
    assert [r["preset"] for r in rows] == list(presets.ALL_PRESETS)


def test_analyze_is_the_library_number_and_set_uses_the_forms_notation(capsys):
    rc, out, _ = _run(capsys, "analyze", "cppll_19p2m_4p8g", "--json",
                      "--set", "osc.pn_dbchz=-118", "--set", "cp.icp=1.2m")
    assert rc == 0
    d = json.loads(out)
    want = make_pll("cppll_19p2m_4p8g", {"osc.pn_dbchz": "-118", "cp.icp": "1.2e-3"}).analyze()
    assert d["jitter_fs"] == pytest.approx(want.jitter_fs)
    assert d["jitter_fs"] != pytest.approx(presets.cppll_19p2m_4p8g().analyze().jitter_fs)


def test_simulate_runs_and_writes_a_record(capsys, tmp_path):
    csv = tmp_path / "rec.csv"
    rc, out, _ = _run(capsys, "simulate", "sspll_19p2m_4p8g", "--cycles", "12000",
                      "--seed", "2", "--start-offset=-2M", "--json", "--csv", str(csv))
    assert rc == 0
    d = json.loads(out)
    assert d["jitter_fs"] > 0 and d["cycles"] == 12000
    lines = csv.read_text().splitlines()
    assert lines[0] == "t_s,freq_out_hz,phase_err_rad" and len(lines) == 12001


def test_sweep_is_one_row_per_value_and_a_refusal_is_a_row(capsys):
    rc, out, _ = _run(capsys, "sweep", "cppll_19p2m_4p8g", "--field", "osc.pn_dbchz",
                      "--values=-125,-115,abc", "--json")
    assert rc == 0
    d = json.loads(out)
    assert [r["value"] for r in d["rows"]] == ["-125", "-115", "abc"]
    assert d["rows"][0]["jitter_fs"] < d["rows"][1]["jitter_fs"]
    assert "error" in d["rows"][2] and "jitter_fs" not in d["rows"][2]


def test_corners_reports_every_standard_corner(capsys):
    from pllsim.corners import STANDARD_CORNERS
    rc, out, _ = _run(capsys, "corners", "spll_100m_8g", "--json")
    assert rc == 0
    d = json.loads(out)
    assert [r["corner"] for r in d["rows"]] == [c.name for c in STANDARD_CORNERS]
    assert d["worst"] in [c.name for c in STANDARD_CORNERS]


def test_config_round_trips_through_a_file_and_check_loads_it(capsys, tmp_path):
    f = tmp_path / "my.pllsim.json"
    rc, out, _ = _run(capsys, "config", "adpll_bb_100m_10g", "--set",
                      "bb_jitter_rms_s=150f", "--out", str(f))
    assert rc == 0 and f.exists()
    rc, out, _ = _run(capsys, "config", "--check", str(f), "--json")
    assert rc == 0 and json.loads(out)["preset"] == "adpll_bb_100m_10g"
    rc, out, _ = _run(capsys, "analyze", "--config", str(f), "--json")
    assert rc == 0
    d = json.loads(out)
    want = make_pll("adpll_bb_100m_10g", {"bb_jitter_rms_s": "150e-15"}).analyze()
    assert d["jitter_fs"] == pytest.approx(want.jitter_fs)
    # --set on top of --config edits the loaded file, not the stock preset
    rc, out, _ = _run(capsys, "analyze", "--config", str(f), "--set",
                      "osc.pn_dbchz=-108", "--json")
    assert json.loads(out)["jitter_fs"] > d["jitter_fs"]


def test_export_writes_the_tree(capsys, tmp_path):
    rc, out, _ = _run(capsys, "export", "mdll_150m_2p4g", "--out", str(tmp_path),
                      "--n-golden", "512", "--n-vectors", "256", "--json")
    assert rc == 0
    d = json.loads(out)
    assert (tmp_path / "mdll_150m_2p4g" / "README.md").exists()
    assert d["kind"] == "mdll" and "rtl" in d["files"]


def test_errors_are_one_line_on_stderr_with_a_nonzero_exit(capsys):
    rc, out, err = _run(capsys, "analyze", "cppll_19p2m_4p8g", "--set", "osc.nope=1")
    assert rc == 1 and out == "" and "unknown field osc.nope" in err
    with pytest.raises(SystemExit):
        _run(capsys, "analyze", "no_such_preset")
