"""Clock phase-noise profile: the one file between pllsim and a SerDes link.

A link simulator does not want a PLL object; it wants the clock the PLL makes.
This module writes that clock as a small YAML file -- the carrier, a
log-uniform offset grid from 100 Hz to f0/2, the total L(f) on it, the
analytic spur table and a free-text provenance line -- which the consumer
(Halo_Serdes, ``ClockConfig(kind="profile")``) turns into per-edge timing.
The format is the consumer's; this is the producer side, so it obeys it
rather than extends it::

    f0_hz: 6253000000.0
    f_hz: [100.0, 103.9, ...]            # log-uniform, 100 Hz .. f0/2
    l_dbc_hz: [-92.6, -92.7, ...]        # total L(f), same length as f_hz
    spurs:
      - {f_hz: 62400.0, dbc: -65.6}
    source: "pllsim preset ..., pllsim 0.9.6, commit ..."

Two conventions that the consumer relies on and that are easy to lose:

* ``l_dbc_hz`` is **L(f) = S_phi/2** in dBc/Hz (single sideband), not the
  double-sideband S_phi this package carries internally.  The 3 dB between
  them is a sqrt(2) on every jitter the consumer computes.
* Timing is phase divided by **2 pi f0_hz** -- the carrier the profile is
  for.  A half-rate clock at f_baud/2 with the same dBc/Hz carries twice the
  seconds, which is why the file states f0 and the consumer must not derive
  it from the baud rate.

The profile carries the model's grid verbatim when the model was analysed on
``profile_grid(f0)``; a foreign grid is resampled by interpolating dB in
log-f, and a grid that does not reach f0/2 is refused rather than
extrapolated (see ``profile_curve`` for the measured reason).

Deliberately numpy-only.  The consumer's phone build carries numpy and scipy
and nothing else, and the functions that read this file next to it are
vendored from this package -- a writer that imported matplotlib would set the
wrong example.
"""
from __future__ import annotations

import math
import re
import subprocess
from pathlib import Path

import numpy as np

from ..core.jitter import ldbc_from_sphi
from ..core.results import AnalysisResult

#: The consumer's lower edge.  Below it a link run of N UI cannot resolve
#: the offset anyway; the number is the format's, not a physics claim.
F_LO_HZ = 100.0

#: Same density as ``core.freqresp.default_grid``: the model's own grid is
#: then a profile grid, and the file carries it with no resampling at all.
POINTS_PER_DECADE = 60

_SPUR_AT = re.compile(r"^.+_spur@(?P<f>[0-9.eE+-]+)Hz$")
_KEYS = ("f0_hz", "f_hz", "l_dbc_hz", "spurs", "source")


# ------------------------------------------------------------------ grid
def profile_grid(f0: float, *, f_lo: float = F_LO_HZ,
                 points_per_decade: int = POINTS_PER_DECADE) -> np.ndarray:
    """The log-uniform offset grid [f_lo, f0/2] the format asks for.

    Analyse on this grid (``pll.analyze(f=profile_grid(pll.cfg.fout))``)
    and the profile is the model's curve point for point.
    """
    f_hi = 0.5 * float(f0)
    if not (f_hi > f_lo):
        raise ValueError(f"f0/2 = {f_hi:g} Hz is not above f_lo = {f_lo:g} Hz")
    n = int(round(points_per_decade * math.log10(f_hi / f_lo))) + 1
    return np.geomspace(f_lo, f_hi, n)


def _is_log_uniform(f: np.ndarray) -> bool:
    if f.size < 3 or np.any(f <= 0.0):
        return False
    steps = np.diff(np.log10(f))
    return bool(np.all(steps > 0.0) and np.ptp(steps) <= 1e-9 * steps[0])


def profile_curve(ar: AnalysisResult) -> tuple[np.ndarray, np.ndarray]:
    """``(f_hz, l_dbc_hz)`` of the total on a profile grid.

    The model's grid is used as it is when it is log-uniform and spans
    exactly [100 Hz, f0/2].  Otherwise L(f) is interpolated linearly in
    (log f, dB) onto ``profile_grid(f0)`` -- the curve is smooth there, and
    at 60 points per decade the error against the model's own points is a
    few thousandths of a dB (measured 0.0027 dB on the MDLL's default grid,
    which runs past f0/2 and is clipped).

    A grid that stops short of f0/2 raises instead of being extended.  The
    tempting fix is to hold the last value flat, and it is wrong by a lot:
    on the Dartizio ADPLL the model's own 100 Hz..f0/2 jitter is 179 fs,
    while the default 100 Hz..1 GHz grid held flat to 4.6 GHz integrates to
    747 fs, because that grid's last point sits on a z-domain lobe at
    exactly 2 fref.  The consumer integrates the whole profile, so the
    producer has to supply the real curve, which is one keyword away.
    """
    f = np.asarray(ar.f, dtype=float)
    l_dbc = ldbc_from_sphi(ar.pn_breakdown["total"])
    grid = profile_grid(ar.f0)
    f_lo, f_hi = grid[0], grid[-1]
    tol = 1e-9
    ends_match = (abs(f[0] - f_lo) <= tol * f_lo
                  and abs(f[-1] - f_hi) <= tol * f_hi)
    if ends_match and _is_log_uniform(f):
        return f, np.asarray(l_dbc, dtype=float)
    if f[0] > f_lo * (1.0 + tol) or f[-1] < f_hi * (1.0 - tol):
        raise ValueError(
            f"the analysis grid spans {f[0]:.4g}..{f[-1]:.4g} Hz but the "
            f"profile needs {f_lo:.4g}..{f_hi:.4g} Hz; the exporter does not "
            "extrapolate -- analyse on it: "
            "pll.analyze(f=pllsim.export.clock_profile.profile_grid(f0))")
    return grid, np.interp(np.log10(grid), np.log10(f), l_dbc)


# ----------------------------------------------------------------- spurs
def spur_entries(ar: AnalysisResult,
                 fref: float | None = None) -> list[tuple[float, float]]:
    """``[(offset_hz, dbc), ...]`` from ``spurs_analytic``, offset ascending.

    The offset is in the key for fractional spurs (``frac_spur@9696000Hz``);
    ``ref_spur`` sits at fref, which the result does not carry, hence the
    keyword.  Keys that are not spurs (``frac_offset_hz`` is a frequency
    annotation beside the spur it describes) are left out, and so is a
    non-finite level, which the format cannot hold.
    """
    rows: list[tuple[float, float]] = []
    for key, level in ar.spurs_analytic.items():
        if "_spur" not in key:
            continue
        dbc = float(level)
        if not math.isfinite(dbc):
            continue
        m = _SPUR_AT.match(key)
        if m:
            f = float(m.group("f"))
        elif key == "ref_spur":
            if fref is None:
                raise ValueError(
                    "spurs_analytic has a ref_spur, whose offset is fref; "
                    "pass fref=pll.cfg.fref")
            f = float(fref)
        else:
            raise ValueError(f"spur {key!r}: no offset in the key and no rule for it")
        rows.append((f, dbc))
    return sorted(rows)


# ---------------------------------------------------------------- source
def _git_commit() -> str | None:
    """Short commit of the checkout this module runs from, or None."""
    try:
        r = subprocess.run(
            ["git", "-C", str(Path(__file__).resolve().parent), "rev-parse",
             "--short=12", "HEAD"],
            capture_output=True, text=True, timeout=5, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    sha = r.stdout.strip()
    return sha if r.returncode == 0 and sha else None


def default_source(preset: str) -> str:
    """English provenance line: preset, model, package version, commit."""
    from .. import __version__
    s = f"pllsim preset {preset}, linear model (analyze), pllsim {__version__}"
    sha = _git_commit()
    if sha:
        s += f", commit {sha}"
    return s


# ------------------------------------------------------------------ YAML
def yaml_float(x: float) -> str:
    """A float literal every YAML 1.1 reader parses as a float.

    Python's shortest repr is exact but writes ``1e-05`` and ``1e+16``;
    PyYAML's resolver requires a dot in the mantissa and a signed exponent,
    and returns a *string* otherwise.  Repaired here rather than formatted
    with a fixed precision, so the value round-trips bit-exactly.
    """
    x = float(x)
    if not math.isfinite(x):
        raise ValueError(f"the profile cannot hold {x!r}")
    s = repr(x)
    if "e" in s:
        mant, exp = s.split("e")
        if "." not in mant:
            mant += ".0"
        if exp[0] not in "+-":
            exp = "+" + exp
        return f"{mant}e{exp}"
    if "." not in s:
        s += ".0"
    return s


def _flow_list(values: list[float], indent: int = 2, width: int = 78) -> str:
    """``[a, b, ...]`` wrapped at ``width``; a flow sequence may span lines."""
    items = [yaml_float(v) for v in values]
    if not items:
        return "[]"
    lines, cur = [], "["
    for i, it in enumerate(items):
        piece = it + ("," if i < len(items) - 1 else "]")
        if len(cur) + len(piece) + 1 > width and cur != "[":
            lines.append(cur)
            cur = " " * indent + piece
        else:
            cur += piece if cur == "[" else " " + piece
    lines.append(cur)
    return "\n".join(lines)


def _quoted(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def write_clock_profile(ar: AnalysisResult, path, *, source: str,
                        fref: float | None = None) -> Path:
    """Write ``ar`` as a clock phase-noise profile; returns the path.

    ``source`` is the free-text provenance the consumer shows (English; see
    ``default_source``).  ``fref`` is needed only when ``spurs_analytic``
    holds a ``ref_spur``, whose offset the result does not carry.  The
    values written are Python floats and lists: nothing of numpy's reaches
    the file.
    """
    f, l_dbc = profile_curve(ar)
    spurs = spur_entries(ar, fref)
    f0 = float(ar.f0)
    lines = [
        "# pllsim clock phase-noise profile",
        "# l_dbc_hz is the total L(f) = S_phi/2 of the linear model in dBc/Hz;",
        "# timing is phase / (2 pi f0_hz).  Offsets are log-uniform, 100 Hz..f0/2.",
        f"f0_hz: {yaml_float(f0)}",
        "f_hz: " + _flow_list([float(v) for v in f.tolist()]),
        "l_dbc_hz: " + _flow_list([float(v) for v in l_dbc.tolist()]),
    ]
    if spurs:
        lines.append("spurs:")
        lines += [f"  - {{f_hz: {yaml_float(fs)}, dbc: {yaml_float(d)}}}"
                  for fs, d in spurs]
    else:
        lines.append("spurs: []")
    lines.append(f"source: {_quoted(str(source))}")
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out


_KEY_LINE = re.compile(r"^([a-z0-9_]+):\s*(.*)$")
_SPUR_ROW = re.compile(
    r"^-\s*\{\s*f_hz:\s*(?P<f>[^,\s]+)\s*,\s*dbc:\s*(?P<d>[^}\s]+)\s*\}$")


def _unquote(s: str) -> str:
    s = s.strip()
    if len(s) >= 2 and s[0] == '"' and s[-1] == '"':
        return s[1:-1].replace('\\"', '"').replace("\\\\", "\\")
    return s


def read_clock_profile(path) -> dict:
    """Read a profile this module wrote; plain floats, lists and dicts.

    Parses only the subset ``write_clock_profile`` emits (and that the
    consumer's YAML loader sees), so the base install needs no YAML
    library; the test suite checks it against PyYAML on every benchmark.
    """
    raw: dict[str, list[str]] = {}
    key = None
    for ln in Path(path).read_text(encoding="utf-8").splitlines():
        if not ln.strip() or ln.lstrip().startswith("#"):
            continue
        m = _KEY_LINE.match(ln)
        if m and not ln[0].isspace():
            key = m.group(1)
            if key not in _KEYS:
                raise ValueError(f"{path}: unknown key {key!r}")
            raw[key] = [m.group(2)]
        elif key is not None:
            raw[key].append(ln.strip())
        else:
            raise ValueError(f"{path}: text before the first key: {ln!r}")
    missing = [k for k in _KEYS if k not in raw]
    if missing:
        raise ValueError(f"{path}: missing {missing}")

    def floats(chunks: list[str]) -> list[float]:
        body = " ".join(chunks).strip()
        if not (body.startswith("[") and body.endswith("]")):
            raise ValueError(f"{path}: expected a flow list, got {body[:40]!r}")
        inner = body[1:-1].strip()
        return [float(t) for t in inner.split(",")] if inner else []

    spurs: list[dict[str, float]] = []
    head = raw["spurs"][0].strip()
    if head and head != "[]":
        raise ValueError(f"{path}: spurs must be a block list or []")
    for row in raw["spurs"][1:]:
        m = _SPUR_ROW.match(row)
        if not m:
            raise ValueError(f"{path}: bad spur row {row!r}")
        spurs.append({"f_hz": float(m.group("f")), "dbc": float(m.group("d"))})
    return {
        "f0_hz": float(" ".join(raw["f0_hz"])),
        "f_hz": floats(raw["f_hz"]),
        "l_dbc_hz": floats(raw["l_dbc_hz"]),
        "spurs": spurs,
        "source": _unquote(" ".join(raw["source"])),
    }
