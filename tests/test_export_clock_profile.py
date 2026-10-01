"""The clock phase-noise profile: the one file between pllsim and a SerDes.

A link simulator (Halo_Serdes) reads ``f0_hz``, a log-uniform ``f_hz`` grid
from 100 Hz to f0/2, the total ``l_dbc_hz`` on it, a spur table and a
``source`` string, and synthesises per-edge timing from them.  Nothing on
that side knows what a pllsim preset is, so the only things that can go
wrong are the ones checked here: a number that changed on the way out (the
3 dB between S_phi and L(f) is the classic), a grid that is not what the
format promises, a spur that was dropped or mislabelled, a float PyYAML
reads back as a string, and a module that quietly drags matplotlib into a
consumer that cannot have it.
"""
from __future__ import annotations

import ast
import json
import math
from pathlib import Path

import numpy as np
import pytest

from pllsim import presets
from pllsim.cli import main
from pllsim.core.jitter import integrate_pn, ldbc_from_sphi
from pllsim.export import clock_profile as cp
from pllsim.export.clock_profile import (
    default_source,
    profile_grid,
    read_clock_profile,
    spur_entries,
    write_clock_profile,
    yaml_float,
)
from tests._require import require_module

# The reference parser.  The reader under test is hand-rolled so the base
# install needs no YAML library; PyYAML is the independent witness that what
# the writer emits is YAML and what the reader returns is what YAML means.
yaml = require_module("yaml", "pip install pyyaml (the [test] extra)")

# The seven JSSC anchors of ex14, which are also the seven files the
# consumer ships in its data/clock_profiles/.
BENCH = [
    "bench_dartizio23_adpllbb_500m_9p2515g",
    "bench_markulic16_sspll_40m_10p24g",
    "bench_markulic16_sspll_frac_40m_10p25g",
    "bench_wu19_spll_frac_52m_6p253g",
    "bench_dadalt03_cppll_311m_2p488g",
    "bench_helal09_ilcm_50m_3p2g",
    "bench_elshazly13_mdll_375m_1p5g",
]


def _analyzed(name):
    """(pll, ar) with ar on the profile grid, as the example and the CLI do."""
    pll = getattr(presets, name)()
    return pll, pll.analyze(f=profile_grid(pll.cfg.fout))


@pytest.fixture(scope="module")
def written(tmp_path_factory):
    out = tmp_path_factory.mktemp("clock_profiles")
    rows = {}
    for name in BENCH:
        pll, ar = _analyzed(name)
        p = write_clock_profile(ar, out / f"{name}.yaml",
                                source=default_source(name), fref=pll.cfg.fref)
        rows[name] = (pll, ar, p)
    return rows


# ------------------------------------------------------------ round trip
@pytest.mark.parametrize("name", BENCH)
def test_the_profile_integrates_back_to_the_jitter_the_model_reported(written, name):
    """Write, read back, integrate over the model's own band: same number.

    1e-6 is algebra, not a budget: the profile carries the model's grid
    verbatim, so the only difference is the dB -> rad^2/Hz round trip.
    The mutation that this catches is the 3 dB one -- write S_phi where
    L(f) belongs and every jitter comes back sqrt(2) high.
    """
    pll, ar, p = written[name]
    d = read_clock_profile(p)
    f = np.asarray(d["f_hz"])
    s_phi = 2.0 * 10.0 ** (np.asarray(d["l_dbc_hz"]) / 10.0)
    lo, hi = ar.int_band
    jitter_fs = 1e15 * math.sqrt(integrate_pn(f, s_phi, lo, hi)) / (2 * math.pi * d["f0_hz"])
    assert jitter_fs == pytest.approx(ar.jitter_fs, rel=1e-6), name
    assert d["f0_hz"] == ar.f0


@pytest.mark.parametrize("name", BENCH)
def test_the_grid_is_log_uniform_from_100_hz_to_half_the_carrier(written, name):
    _pll, ar, p = written[name]
    d = read_clock_profile(p)
    f = np.asarray(d["f_hz"])
    assert f[0] == pytest.approx(100.0, rel=1e-12)
    assert f[-1] == pytest.approx(0.5 * ar.f0, rel=1e-12)
    steps = np.diff(np.log10(f))
    assert np.ptp(steps) < 1e-9 * steps[0], "the grid is not log-uniform"
    assert len(d["l_dbc_hz"]) == len(f)
    # and dense enough that the consumer's interpolation is not the limit:
    # 60 per decade is the model's own density
    assert steps[0] == pytest.approx(1 / 60, rel=0.02)


@pytest.mark.parametrize("name", BENCH)
def test_the_hand_rolled_reader_agrees_with_pyyaml(written, name):
    """read_clock_profile exists so the base install needs no YAML library;
    PyYAML decides what the file means."""
    _pll, _ar, p = written[name]
    ours = read_clock_profile(p)
    ref = yaml.safe_load(p.read_text(encoding="utf-8"))
    assert ours == ref
    assert list(ours) == ["f0_hz", "f_hz", "l_dbc_hz", "spurs", "source"]


# ---------------------------------------------------------- resampling
def _resample_error_db(pll, grid):
    """|profile interpolated back onto the model's points - model| in dB,
    over the overlap, for a model analysed on ``grid``."""
    ar = pll.analyze(f=grid)
    f_p, l_p = cp.profile_curve(ar)
    assert f_p[0] == pytest.approx(100.0) and f_p[-1] == pytest.approx(0.5 * ar.f0)
    l_native = ldbc_from_sphi(ar.pn_breakdown["total"])
    inside = (ar.f >= f_p[0]) & (ar.f <= f_p[-1])
    back = np.interp(np.log10(ar.f[inside]), np.log10(f_p), l_p)
    return np.abs(back - l_native[inside]), ar.f[inside]


def test_resampling_a_smooth_curve_from_a_foreign_grid_is_within_0p05_db():
    """A caller who analysed on some other grid gets the profile grid back.

    37 points per decade from 50 Hz to f0: no profile point coincides with a
    model point, so the whole curve goes through the interpolation.  The
    sampling PLL's L(f) is an s-domain curve, smooth on that scale, and the
    error measured by interpolating the profile back onto the model's own
    points is 0.0039 dB at the loop corner (27 MHz); 0.05 dB is the
    acceptance budget, ~13x that.
    """
    pll = presets.bench_wu19_spll_frac_52m_6p253g()
    f0 = pll.cfg.fout
    err, f = _resample_error_db(pll, np.geomspace(50.0, f0, int(37 * np.log10(f0 / 50)) + 1))
    assert err.max() <= 0.05, f"{err.max():.4f} dB at {f[err.argmax()]:.4g} Hz"


def test_clipping_the_mdll_default_grid_to_half_the_carrier():
    """The model's default grid runs *past* f0/2 for the 1.5 GHz MDLL
    (1 GHz against 750 MHz), so this is the clip path, and the only one of
    the seven benchmarks that is not written verbatim when analysed with the
    default grid.

    The 1-ZOH edge-replacement NTF has a null near fref/2 = 187.5 MHz that
    is sharper than either grid's step, and there the two samplings of the
    same curve differ by 0.366 dB (measured at 185 MHz); everywhere else
    they agree to 0.0015 dB (99th percentile).  The null is a resolution
    limit of a 60-per-decade grid, the model's own included, not a
    resampling defect, so the gate is the percentile and the maximum is
    pinned where it was seen rather than widened into a budget.
    """
    pll = presets.bench_elshazly13_mdll_375m_1p5g()
    err, f = _resample_error_db(pll, None)
    assert np.percentile(err, 99) <= 0.05
    worst = f[err.argmax()]
    assert err.max() <= 0.5 and 1.5e8 < worst < 2.2e8, \
        f"{err.max():.4f} dB at {worst:.4g} Hz -- the null moved, or something else did"


def test_a_model_grid_that_stops_short_of_half_the_carrier_is_refused():
    """No extrapolation.  Holding the last model value flat from 1 GHz to
    f0/2 would be the obvious thing and it is wrong by a lot: measured on
    the Dartizio ADPLL, the model's own 100 Hz..f0/2 jitter is 179 fs, the
    flat-held default grid integrates to 747 fs, because the default grid's
    last point sits on a z-domain lobe at exactly 2 fref.  The consumer
    integrates the whole profile, so the exporter asks for the real curve
    instead of inventing one.
    """
    ar = presets.bench_dartizio23_adpllbb_500m_9p2515g().analyze()   # 100 Hz..1 GHz
    assert ar.f[-1] < 0.5 * ar.f0
    with pytest.raises(ValueError, match="profile_grid"):
        cp.profile_curve(ar)


# --------------------------------------------------------------- spurs
@pytest.mark.parametrize("name", list(presets.ALL_PRESETS))
def test_every_analytic_spur_is_in_the_table_at_its_offset(name, tmp_path):
    """Count and dBc match spurs_analytic; the offset comes from the key.

    `frac_spur@9696000Hz` carries its own offset; `ref_spur` sits at fref,
    which AnalysisResult does not hold, so the writer takes it as a keyword.
    `frac_offset_hz` is an annotation in the same dict (a frequency, not a
    level) and must not become a spur at 9.7 MHz of -0 dBc.
    """
    pll = presets.ALL_PRESETS[name]()
    ar = pll.analyze(f=profile_grid(pll.cfg.fout))
    p = write_clock_profile(ar, tmp_path / f"{name}.yaml", source="t",
                            fref=pll.cfg.fref)
    got = read_clock_profile(p)["spurs"]
    want = {k: float(v) for k, v in ar.spurs_analytic.items()
            if ("_spur" in k) and math.isfinite(float(v))}
    assert len(got) == len(want), (name, got, ar.spurs_analytic)
    by_f = {}
    for k, v in want.items():
        f = pll.cfg.fref if k == "ref_spur" else float(k.split("@")[1][:-2])
        by_f[f] = v
    for row in got:
        assert set(row) == {"f_hz", "dbc"}
        assert row["dbc"] == pytest.approx(by_f[row["f_hz"]], abs=1e-9)
    assert [r["f_hz"] for r in got] == sorted(r["f_hz"] for r in got)


def test_a_reference_spur_needs_fref_and_says_so():
    pll = presets.cppll_19p2m_4p8g()
    ar = pll.analyze(f=profile_grid(pll.cfg.fout))
    assert "ref_spur" in ar.spurs_analytic
    with pytest.raises(ValueError, match="fref"):
        spur_entries(ar)
    assert spur_entries(ar, fref=pll.cfg.fref) == \
        [(pll.cfg.fref, float(ar.spurs_analytic["ref_spur"]))]


# ------------------------------------------------------- the YAML itself
@pytest.mark.parametrize("x", [100.0, 1e-05, 1e16, -92.83339849442595,
                               4625750000.0, 0.1 + 0.2, 1.0, 123456789.0,
                               1e-300, -1e+300, 5.125e9 / 3])
def test_every_float_is_written_so_that_pyyaml_reads_it_as_a_float(x):
    """PyYAML's YAML 1.1 resolver wants a dot in the mantissa and a sign on
    the exponent: `1e-05` and `1.0e5` both come back as *strings*, and a
    profile whose f_hz is a list of strings fails in the consumer, not here.
    Python's repr produces exactly those forms, so the writer repairs them.
    """
    s = yaml_float(x)
    got = yaml.safe_load(f"v: {s}")["v"]
    assert isinstance(got, float) and got == x, (s, got)


def test_the_file_holds_plain_floats_and_lists_only(written):
    _pll, _ar, p = written["bench_markulic16_sspll_frac_40m_10p25g"]
    text = p.read_text(encoding="utf-8")
    assert "np." not in text and "float64" not in text and "array" not in text
    d = yaml.safe_load(text)
    assert type(d["f0_hz"]) is float
    assert all(type(v) is float for v in d["f_hz"])
    assert all(type(v) is float for v in d["l_dbc_hz"])
    assert all(type(r["f_hz"]) is float and type(r["dbc"]) is float
               for r in d["spurs"])
    assert isinstance(d["source"], str) and d["source"]
    # pure Python all the way down, so json can carry it too
    json.dumps(d)


def test_source_names_the_preset_and_the_version():
    import pllsim
    s = default_source("bench_wu19_spll_frac_52m_6p253g")
    assert "bench_wu19_spll_frac_52m_6p253g" in s and pllsim.__version__ in s
    assert s.isascii(), "the consumer's convention is English free text"


def test_the_exporter_does_not_import_matplotlib():
    """The consumer carries numpy and scipy only; a profile writer that
    imported matplotlib would be unusable where it is wanted."""
    src = Path(cp.__file__).read_text(encoding="utf-8")
    names = set()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Import):
            names |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module.split(".")[0])
    assert "matplotlib" not in names, names
    assert "pyplot" not in src and "plotting" not in src


# ----------------------------------------------------------------- CLI
def test_the_cli_writes_a_profile_without_a_vams_tree(capsys, tmp_path):
    out = tmp_path / "wu19.yaml"
    rc = main(["export", "bench_wu19_spll_frac_52m_6p253g",
               "--clock-profile", str(out), "--json"])
    text = capsys.readouterr().out
    assert rc == 0 and out.exists()
    d = json.loads(text)
    assert d["clock_profile"]["path"] == str(out)
    assert d["clock_profile"]["n_spurs"] == 4
    assert not list(tmp_path.glob("*/README.md")), "no --out, no VAMS export"
    prof = read_clock_profile(out)
    _pll, ar = _analyzed("bench_wu19_spll_frac_52m_6p253g")
    assert prof["f0_hz"] == ar.f0 and len(prof["f_hz"]) == len(ar.f)
    assert d["clock_profile"]["jitter_fs"] == pytest.approx(ar.jitter_fs)


def test_the_cli_still_needs_a_destination(capsys):
    with pytest.raises(SystemExit):
        main(["export", "bench_wu19_spll_frac_52m_6p253g"])


def test_the_cli_can_do_both_in_one_call(capsys, tmp_path):
    out = tmp_path / "both.yaml"
    rc = main(["export", "mdll_150m_2p4g", "--out", str(tmp_path),
               "--n-golden", "512", "--n-vectors", "256",
               "--clock-profile", str(out), "--json"])
    assert rc == 0
    d = json.loads(capsys.readouterr().out)
    assert (tmp_path / "mdll_150m_2p4g" / "README.md").exists()
    assert out.exists() and d["clock_profile"]["path"] == str(out)
