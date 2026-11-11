"""A clock profile after an integer frequency multiplier (issue #71).

mmw60_trx builds its 60 GHz LO as a sub-7 GHz PLL followed by a x N
multiplier, and reads only the profile file.  The contract agreed on the
issue, and checked here:

* N is an integer >= 2.  The request that started this moved a 6.253 GHz
  profile to 60.48 GHz by 20*log10(9.672); no multiplier does that, so a
  non-integer N is refused rather than rounded.
* Up to f_in/2 the output is N^2 * L_in plus an additive white floor, both
  in linear power.  Above f_in/2 the PLL's profile says nothing, so the
  output there is the floor and only the floor: no extrapolation, as for
  the unmultiplied file.
* The floor and the harmonic-leakage rejection have no defaults.  This
  library has no multiplier measurement to take one from.
* Spurs grow by 20*log10(N) (narrow-band PM), and the N-1 / N+1 harmonics
  leaking through the selection filter appear as one entry at offset f_in.
  One entry, not two: the format's spur is a PM pair, one sideband of
  `dbc` on each side, which is exactly what the leakage looks like under
  the PM approximation the issue accepted.
* `multiply_by`, `f_in_hz`, `floor_dbchz` and `spur_rejection_db` are their
  own keys, so a consumer can find the f_in/2 boundary without parsing
  `source`.  They appear only in a multiplied file: an unmultiplied file is
  byte-for-byte what it was, so a reader that rejects unknown keys (this
  library's own did) is not broken by the change.
"""
from __future__ import annotations

import json
import math

import numpy as np
import pytest

from pllsim.cli import main
from pllsim.core.jitter import integrate_pn, ldbc_from_sphi
from pllsim.export.clock_profile import (
    profile_grid,
    read_clock_profile,
    spur_entries,
    write_clock_profile,
)
from pllsim.guiutil import make_pll
from tests._require import require_module

yaml = require_module("yaml", "pip install pyyaml (the [test] extra)")

# The profile mmw60_trx asked for on the issue: topology B, LO at
# 60.48 GHz, N = 10, so the PLL sits at 6.048 GHz.  The Wu'19 anchor is
# designed at 6.253 GHz with its VCO centred at 6.2 GHz; 6.048 GHz needs
# -2.53 V of tuning from there and trips the tuning-swing boundary, so the
# VCO is recentred too.  Measured 2026-11-11: 82.16 fs either way.
WU19_6P048 = {"fout": "6.048G", "osc.f0": "6.048G"}
N = 10
FLOOR = -150.0       # test value, not a claim about any multiplier
REJ = 30.0           # test value, likewise


@pytest.fixture(scope="module")
def pll_in():
    return make_pll("bench_wu19_spll_frac_52m_6p253g", WU19_6P048)


@pytest.fixture(scope="module")
def ar_in(pll_in):
    return pll_in.analyze(f=profile_grid(pll_in.cfg.fout))


@pytest.fixture(scope="module")
def multiplied(ar_in, pll_in, tmp_path_factory):
    p = tmp_path_factory.mktemp("mult") / "x10.yaml"
    write_clock_profile(ar_in, p, source="test", fref=pll_in.cfg.fref,
                        multiply_by=N, floor_dbchz=FLOOR,
                        spur_rejection_db=REJ)
    return read_clock_profile(p), p


# ----------------------------------------------------------- refusals
@pytest.mark.parametrize("bad", [9.672, 1, 0, -3, True, 10.0000001])
def test_only_an_integer_multiplier_of_two_or_more_is_accepted(ar_in, pll_in, tmp_path, bad):
    with pytest.raises((ValueError, TypeError), match="multiply_by"):
        write_clock_profile(ar_in, tmp_path / "x.yaml", source="t",
                            fref=pll_in.cfg.fref, multiply_by=bad,
                            floor_dbchz=FLOOR, spur_rejection_db=REJ)


def test_an_integral_float_is_an_integer(ar_in, pll_in, tmp_path):
    p = write_clock_profile(ar_in, tmp_path / "x.yaml", source="t",
                            fref=pll_in.cfg.fref, multiply_by=10.0,
                            floor_dbchz=FLOOR, spur_rejection_db=REJ)
    assert read_clock_profile(p)["multiply_by"] == 10


@pytest.mark.parametrize("missing", ["floor_dbchz", "spur_rejection_db"])
def test_the_floor_and_the_rejection_have_no_default(ar_in, pll_in, tmp_path, missing):
    kw = {"floor_dbchz": FLOOR, "spur_rejection_db": REJ}
    del kw[missing]
    with pytest.raises(ValueError, match=missing):
        write_clock_profile(ar_in, tmp_path / "x.yaml", source="t",
                            fref=pll_in.cfg.fref, multiply_by=N, **kw)


@pytest.mark.parametrize("kw, word", [
    ({"floor_dbchz": FLOOR, "spur_rejection_db": 0.0}, "positive"),
    ({"floor_dbchz": FLOOR, "spur_rejection_db": -20.0}, "positive"),
    ({"floor_dbchz": float("nan"), "spur_rejection_db": REJ}, "finite"),
    ({"floor_dbchz": float("-inf"), "spur_rejection_db": REJ}, "finite"),
])
def test_a_rejection_must_reject_and_the_floor_must_be_a_number(ar_in, pll_in, tmp_path, kw, word):
    """A rejection of -20 dB would put the leakage 20 dB ABOVE the carrier;
    -inf dBc/Hz is "no floor", which the caller should say with a very low
    finite number so the file can hold it."""
    with pytest.raises(ValueError, match=word):
        write_clock_profile(ar_in, tmp_path / "x.yaml", source="t",
                            fref=pll_in.cfg.fref, multiply_by=N, **kw)


@pytest.mark.parametrize("kw", [{"floor_dbchz": FLOOR}, {"spur_rejection_db": REJ}])
def test_multiplier_parameters_without_a_multiplier_are_refused(ar_in, pll_in, tmp_path, kw):
    """Silently ignoring them would write an unmultiplied file that the
    caller believes has a floor in it."""
    with pytest.raises(ValueError, match="multiply_by"):
        write_clock_profile(ar_in, tmp_path / "x.yaml", source="t",
                            fref=pll_in.cfg.fref, **kw)


# ---------------------------------------------------------- the curve
def test_the_carrier_and_the_grid_are_the_multiplied_ones(multiplied, ar_in):
    d, _ = multiplied
    f = np.asarray(d["f_hz"])
    assert d["f0_hz"] == N * ar_in.f0
    assert d["f_in_hz"] == ar_in.f0 and d["multiply_by"] == N
    assert f[0] == pytest.approx(100.0, rel=1e-12)
    assert f[-1] == pytest.approx(0.5 * N * ar_in.f0, rel=1e-12)
    steps = np.diff(np.log10(f))
    assert np.ptp(steps) < 1e-9 * steps[0]
    assert len(d["l_dbc_hz"]) == f.size


def test_below_half_the_input_carrier_it_is_n_squared_plus_the_floor(multiplied, ar_in):
    """Compared with the model analysed on the output grid's own points,
    so the check measures the exporter and not an interpolation of it.
    The profile does interpolate the input curve (the two log grids
    cannot share points): measured 2026-11-11, worst 0.00007 dB at 26 MHz.
    0.005 dB is ~70x that; using N instead of N^2 would be off by 10 dB."""
    d, _ = multiplied
    f = np.asarray(d["f_hz"])
    lo = f < 0.5 * ar_in.f0
    pll = make_pll("bench_wu19_spll_frac_52m_6p253g", WU19_6P048)
    exact = pll.analyze(f=f[lo])
    l_in = ldbc_from_sphi(exact.pn_breakdown["total"])
    want = 10 * np.log10(N**2 * 10 ** (l_in / 10) + 10 ** (FLOOR / 10))
    err = np.abs(np.asarray(d["l_dbc_hz"])[lo] - want)
    assert err.max() <= 0.005, f"{err.max():.4f} dB at {f[lo][err.argmax()]:.4g} Hz"


def test_above_half_the_input_carrier_it_is_the_floor_alone(multiplied, ar_in):
    d, _ = multiplied
    f = np.asarray(d["f_hz"])
    hi = f > 0.5 * ar_in.f0
    assert hi.sum() > 50, "the floor-only stretch should be most of a decade here"
    assert np.all(np.asarray(d["l_dbc_hz"])[hi] == FLOOR)


def test_with_no_floor_to_speak_of_the_inband_jitter_scales_by_n(ar_in, pll_in, tmp_path):
    """The algebra the whole request rests on: phase multiplies by N, so
    jitter in seconds is unchanged and phase power grows by N^2.  A floor
    of -400 dBc/Hz contributes 1e-40 rad^2/Hz, nothing.  1e-4 is the
    interpolation of the input curve onto the output grid: measured
    2026-11-11 at -4.1e-6, so ~25x."""
    p = write_clock_profile(ar_in, tmp_path / "x.yaml", source="t",
                            fref=pll_in.cfg.fref, multiply_by=N,
                            floor_dbchz=-400.0, spur_rejection_db=REJ)
    d = read_clock_profile(p)
    f = np.asarray(d["f_hz"])
    s = 2 * 10 ** (np.asarray(d["l_dbc_hz"]) / 10)
    lo, hi = ar_in.int_band
    p_out = integrate_pn(f, s, lo, hi)
    p_in = integrate_pn(ar_in.f, ar_in.pn_breakdown["total"], lo, hi)
    assert p_out == pytest.approx(N**2 * p_in, rel=1e-4)
    # and the same thing said in seconds: the jitter does not move
    j_out = 1e15 * math.sqrt(p_out) / (2 * math.pi * d["f0_hz"])
    assert j_out == pytest.approx(ar_in.jitter_fs, rel=1e-4)


def test_the_floor_adds_its_own_band_power(multiplied, ar_in):
    """Over a stretch above f_in/2 the file is flat at the floor, and its
    phase power is 2 * 10^(floor/10) * bandwidth to round-off."""
    d, _ = multiplied
    f = np.asarray(d["f_hz"])
    s = 2 * 10 ** (np.asarray(d["l_dbc_hz"]) / 10)
    f1, f2 = 0.6 * ar_in.f0, 2.0 * ar_in.f0
    assert integrate_pn(f, s, f1, f2) == pytest.approx(
        2 * 10 ** (FLOOR / 10) * (f2 - f1), rel=1e-9)


# --------------------------------------------------------------- spurs
def test_spurs_grow_by_twenty_log_n_and_the_leakage_sits_at_f_in(multiplied, ar_in, pll_in):
    d, _ = multiplied
    want = [(f, dbc + 20 * math.log10(N)) for f, dbc in spur_entries(ar_in, pll_in.cfg.fref)]
    want.append((ar_in.f0, -REJ))
    got = [(r["f_hz"], r["dbc"]) for r in d["spurs"]]
    assert len(got) == len(want)
    for (fg, dg), (fw, dw) in zip(got, sorted(want), strict=True):
        assert fg == pytest.approx(fw, rel=1e-12) and dg == pytest.approx(dw, abs=1e-9)


def test_the_four_mhz_fractional_tone_is_where_the_issue_was_told_it_is(multiplied):
    """60.48 GHz / 52 MHz = 15120/13, so every integer N lands the divider
    on a k/13 fraction and the first-order tone at fref/13 = 4 MHz.  The
    model's level there is -63.7 dBc at 6.048 GHz; x10 makes it -43.7.
    Pinned because the reply on the issue quotes it."""
    d, _ = multiplied
    tone = [r for r in d["spurs"] if r["f_hz"] == pytest.approx(4e6)]
    assert len(tone) == 1
    assert tone[0]["dbc"] == pytest.approx(-43.7, abs=0.05)


# ---------------------------------------------------------- the file
def test_the_multiplier_fields_are_their_own_keys(multiplied):
    d, p = multiplied
    assert list(d) == ["f0_hz", "f_hz", "l_dbc_hz", "spurs", "multiply_by",
                       "f_in_hz", "floor_dbchz", "spur_rejection_db", "source"]
    assert type(d["multiply_by"]) is int
    assert all(type(d[k]) is float for k in ("f_in_hz", "floor_dbchz", "spur_rejection_db"))
    assert yaml.safe_load(p.read_text(encoding="utf-8")) == d
    json.dumps(d)


def test_an_unmultiplied_file_has_no_new_keys(ar_in, pll_in, tmp_path):
    p = write_clock_profile(ar_in, tmp_path / "x.yaml", source="t",
                            fref=pll_in.cfg.fref)
    text = p.read_text(encoding="utf-8")
    for k in ("multiply_by", "f_in_hz", "floor_dbchz", "spur_rejection_db"):
        assert f"{k}:" not in text
    assert list(read_clock_profile(p)) == ["f0_hz", "f_hz", "l_dbc_hz", "spurs", "source"]


def test_the_reader_refuses_half_a_multiplier(multiplied, tmp_path):
    """Three of the four fields means a file someone edited by hand; the
    f_in/2 boundary it implies cannot be trusted."""
    _, p = multiplied
    text = p.read_text(encoding="utf-8")
    bad = tmp_path / "half.yaml"
    bad.write_text("\n".join(ln for ln in text.splitlines()
                             if not ln.startswith("floor_dbchz:")) + "\n",
                   encoding="utf-8")
    with pytest.raises(ValueError, match="floor_dbchz"):
        read_clock_profile(bad)


# ----------------------------------------------------------------- CLI
def test_the_cli_writes_the_multiplied_profile(capsys, tmp_path, multiplied):
    out = tmp_path / "x10.yaml"
    rc = main(["export", "bench_wu19_spll_frac_52m_6p253g",
               "--set", "fout=6.048G", "--set", "osc.f0=6.048G",
               "--clock-profile", str(out), "--multiply-by", "10",
               "--floor-dbchz=-150", "--spur-rejection-db", "30", "--json"])
    assert rc == 0
    js = json.loads(capsys.readouterr().out)["clock_profile"]
    assert js["multiply_by"] == 10 and js["f0_hz"] == pytest.approx(60.48e9)
    got = read_clock_profile(out)
    want, _ = multiplied
    assert got["l_dbc_hz"] == want["l_dbc_hz"] and got["spurs"] == want["spurs"]


def test_the_cli_refuses_a_multiplier_without_its_parameters(capsys, tmp_path):
    rc = main(["export", "bench_wu19_spll_frac_52m_6p253g",
               "--clock-profile", str(tmp_path / "x.yaml"), "--multiply-by", "10"])
    assert rc == 1 and "floor_dbchz" in capsys.readouterr().err
