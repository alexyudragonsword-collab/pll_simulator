"""``pllsim`` -- the library from a shell, for scripts and batch runs.

The GUIs are the same library behind a form; this is the same library behind
argparse, so a sweep of forty points or a nightly corner report does not
need a browser.  Every command takes a preset (or a config file written by a
GUI or ``pllsim config``) plus ``--set path=value`` edits in the forms'
notation (``19.2M``, ``680p``), and prints a table or, with ``--json``, the
same numbers as JSON on stdout.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from . import presets
from .guiutil import (
    apply_overrides,
    arch_kind,
    config_from_json,
    config_to_json,
    enumerate_fields,
    fmt_value,
    make_pll,
    parse_number,
    simulate_kwargs,
)


def _sets(pairs: list[str] | None) -> dict[str, str]:
    out: dict[str, str] = {}
    for p in pairs or []:
        if "=" not in p:
            raise SystemExit(f"--set expects path=value, got {p!r}")
        k, v = p.split("=", 1)
        out[k.strip()] = v.strip()
    return out


def _load(args) -> tuple[Any, str]:
    """(pll, preset name) from --config and/or the preset argument + --set."""
    sets = _sets(getattr(args, "set", None))
    if getattr(args, "config", None):
        pll, name = config_from_json(Path(args.config).read_text(encoding="utf-8"))
        if sets:
            apply_overrides(pll.cfg, sets)
        return pll, name
    name = getattr(args, "preset", None)
    if not name:
        raise SystemExit("a preset name or --config FILE is required")
    if name not in presets.ALL_PRESETS:
        raise SystemExit(f"unknown preset {name!r}; `pllsim presets` lists them")
    return make_pll(name, sets), name


def _emit(args, payload: Any, text: str) -> None:
    if getattr(args, "json", False):
        print(json.dumps(payload, indent=2, default=_jsonable))
    else:
        print(text)


def _jsonable(o):
    import numpy as np
    if isinstance(o, (np.floating, np.integer)):
        return o.item()
    if isinstance(o, np.ndarray):
        return o.tolist()
    if isinstance(o, tuple):
        return list(o)
    return str(o)


def _finite(x) -> float | None:
    import math
    x = float(x)
    return x if math.isfinite(x) else None


def _analysis_dict(ar) -> dict:
    return {"jitter_fs": _finite(ar.jitter_fs), "ipn_dbc": _finite(ar.ipn_dbc),
            "f_ugb_hz": _finite(ar.loop.f_ugb), "pm_deg": _finite(ar.loop.pm_deg),
            "peaking_db": _finite(ar.loop.peaking_db),
            "spurs_analytic": {k: _finite(v) for k, v in ar.spurs_analytic.items()},
            "notes": list(ar.notes)}


def _sim_dict(sim) -> dict:
    return {"jitter_fs": _finite(sim.jitter_fs),
            "lock_time_s": None if sim.lock_time_s is None else float(sim.lock_time_s),
            "spurs_fft": {k: _finite(v) for k, v in sim.spurs_fft.items()},
            "notes": list(sim.notes)}


# ------------------------------------------------------------- commands

def cmd_presets(args) -> int:
    rows = []
    for name, mk in presets.ALL_PRESETS.items():
        pll = mk()
        rows.append({"preset": name, "arch": arch_kind(pll),
                     "fref_hz": pll.cfg.fref, "fout_hz": pll.cfg.fout})
    text = "\n".join(f"{r['preset']:42s} {r['arch']:6s} "
                     f"{fmt_value(float(r['fref_hz'])):>8s} -> {fmt_value(float(r['fout_hz']))}"
                     for r in rows)
    _emit(args, rows, text)
    return 0


def cmd_fields(args) -> int:
    pll, name = _load(args)
    rows = [{"path": s.path, "value": s.value if not isinstance(s.value, tuple)
             else list(s.value), "kind": s.kind, "unit": s.unit,
             "label": s.label_en} for s in enumerate_fields(pll.cfg)]
    text = "\n".join(f"{r['path']:34s} {fmt_value(tuple(r['value']) if isinstance(r['value'], list) else r['value']):>14s}  "
                     f"{r['unit']:8s} {r['label']}" for r in rows)
    _emit(args, {"preset": name, "fields": rows}, text)
    return 0


def cmd_analyze(args) -> int:
    pll, name = _load(args)
    ar = pll.analyze()
    d = {"preset": name, "arch": arch_kind(pll), **_analysis_dict(ar)}
    text = (f"{name} [{d['arch']}]: jitter {d['jitter_fs']:.1f} fs, "
            f"IPN {d['ipn_dbc']:.1f} dBc, UGB {(d['f_ugb_hz'] or 0) / 1e3:.0f} kHz, "
            f"PM {d['pm_deg'] if d['pm_deg'] is None else round(d['pm_deg'], 1)} deg")
    if d["spurs_analytic"]:
        text += "\nspurs [dBc]: " + ", ".join(f"{k}={v:.1f}" for k, v in d["spurs_analytic"].items() if v is not None)
    text += "".join(f"\nnote: {n}" for n in d["notes"])
    _emit(args, d, text)
    return 0


def _simulate(pll, args):
    kw = simulate_kwargs(pll, noise=not args.no_noise, calibration=not args.no_cal,
                         seed=args.seed, f_start_offset=parse_number(args.start_offset))
    return pll.simulate(args.cycles, **kw)


def cmd_simulate(args) -> int:
    pll, name = _load(args)
    sim = _simulate(pll, args)
    d = {"preset": name, "arch": arch_kind(pll), "cycles": args.cycles,
         "seed": args.seed, **_sim_dict(sim)}
    if args.csv:
        import numpy as np
        np.savetxt(args.csv, np.column_stack([sim.t, sim.freq_out, sim.phase_err_out]),
                   delimiter=",", header="t_s,freq_out_hz,phase_err_rad", comments="")
        d["csv"] = args.csv
    lock = "-" if d["lock_time_s"] is None else f"{d['lock_time_s'] * 1e6:.1f} us"
    text = (f"{name} [{d['arch']}] {args.cycles} cycles seed {args.seed}: "
            f"jitter {d['jitter_fs']:.1f} fs, lock {lock}")
    if d["spurs_fft"]:
        text += "\nspurs [dBc]: " + ", ".join(f"{k}={v:.1f}" for k, v in d["spurs_fft"].items() if v is not None)
    text += "".join(f"\nnote: {n}" for n in d["notes"])
    if args.csv:
        text += f"\nrecord written to {args.csv}"
    _emit(args, d, text)
    return 0


def cmd_sweep(args) -> int:
    """One field over a list of values; analyze() by default, simulate()
    with --simulate.  The batch loop the GUIs' single-run pages lack."""
    values = [v.strip() for v in args.values.split(",") if v.strip()]
    rows = []
    for v in values:
        row: dict[str, Any] = {"value": v}
        try:
            ns = argparse.Namespace(**{**vars(args), "set": list(args.set or []) + [f"{args.field}={v}"]})
            pll, name = _load(ns)
            if args.simulate:
                row.update(_sim_dict(_simulate(pll, args)))
            else:
                row.update(_analysis_dict(pll.analyze()))
        except Exception as e:                            # noqa: BLE001
            row["error"] = f"{type(e).__name__}: {e}"    # a refusal is a row
        rows.append(row)
    lines = [f"{args.field:30s} {'jitter [fs]':>12s}  notes"]
    for r in rows:
        if "error" in r:
            lines.append(f"{r['value']:30s} {'ERROR':>12s}  {r['error']}")
        else:
            j = r["jitter_fs"]
            js = "-" if j is None else f"{j:.1f}"
            lines.append(f"{r['value']:30s} {js:>12s}  {len(r['notes'])}")
    _emit(args, {"field": args.field, "rows": rows}, "\n".join(lines))
    return 0


def cmd_corners(args) -> int:
    from .corners import STANDARD_CORNERS, corner_report, corner_table, worst_case
    pll, name = _load(args)
    rows = corner_report(pll, STANDARD_CORNERS)
    worst = worst_case(rows)
    d = {"preset": name, "rows": [{"corner": r.corner, "jitter_fs": _finite(r.jitter_fs),
                                    "f_ugb_hz": _finite(r.f_ugb_hz), "pm_deg": _finite(r.pm_deg),
                                    "peaking_db": _finite(r.peaking_db), "notes": r.notes,
                                    "error": r.error} for r in rows],
         "worst": None if worst is None else worst.corner}
    text = corner_table(rows) + ("" if worst is None else f"\nworst: {worst.corner}")
    _emit(args, d, text)
    return 0


def cmd_export(args) -> int:
    from .export import export
    pll, name = _load(args)
    flavors = tuple(f.strip() for f in args.flavors.split(",") if f.strip())
    rep = export(pll, args.out, name=name, flavors=flavors,
                 n_golden=args.n_golden, n_vectors=args.n_vectors)
    d = {"preset": name, "kind": rep.kind, "outdir": str(rep.outdir),
         "files": rep.files, "warnings": rep.warnings}
    text = rep.summary() + "".join(f"\nwarning: {w}" for w in rep.warnings)
    _emit(args, d, text)
    return 0


def cmd_config(args) -> int:
    """Write a config file (preset + edits), or check one loads."""
    if args.check:
        pll, name = config_from_json(Path(args.check).read_text(encoding="utf-8"))
        _emit(args, {"preset": name, "arch": arch_kind(pll), "ok": True},
              f"{args.check}: {name} [{arch_kind(pll)}] loads")
        return 0
    pll, name = _load(args)
    text = config_to_json(pll, name)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        _emit(args, {"preset": name, "out": args.out}, f"written {args.out}")
    else:
        sys.stdout.write(text)
    return 0


# --------------------------------------------------------------- parser

def _common(p: argparse.ArgumentParser, preset: bool = True) -> None:
    if preset:
        p.add_argument("preset", nargs="?", help="preset name (see `pllsim presets`)")
    p.add_argument("--config", metavar="FILE", help="config file written by a GUI or `pllsim config`")
    p.add_argument("--set", action="append", metavar="PATH=VALUE",
                   help="edit a field, forms' notation: osc.pn_dbchz=-118, cp.icp=1.2m")
    p.add_argument("--json", action="store_true", help="JSON on stdout instead of a table")


def _sim_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--cycles", type=int, default=100_000)
    p.add_argument("--seed", type=int, default=1)
    p.add_argument("--start-offset", default="0",
                   help="initial frequency error [Hz]; negative values need the = form: --start-offset=-5M")
    p.add_argument("--no-noise", action="store_true")
    p.add_argument("--no-cal", action="store_true")


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="pllsim", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("presets", help="list the presets")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_presets)

    p = sub.add_parser("fields", help="list a preset's editable fields")
    _common(p)
    p.set_defaults(fn=cmd_fields)

    p = sub.add_parser("analyze", help="linear model")
    _common(p)
    p.set_defaults(fn=cmd_analyze)

    p = sub.add_parser("simulate", help="time-domain run")
    _common(p)
    _sim_args(p)
    p.add_argument("--csv", metavar="FILE", help="write t, freq_out, phase_err as CSV")
    p.set_defaults(fn=cmd_simulate)

    p = sub.add_parser("sweep", help="one field over a list of values")
    _common(p)
    p.add_argument("--field", required=True, metavar="PATH")
    p.add_argument("--values", required=True, metavar="V1,V2,...")
    p.add_argument("--simulate", action="store_true", help="simulate() instead of analyze()")
    _sim_args(p)
    p.set_defaults(fn=cmd_sweep)

    p = sub.add_parser("corners", help="PVT corner report (pllsim.corners)")
    _common(p)
    p.set_defaults(fn=cmd_corners)

    p = sub.add_parser("export", help="Verilog-AMS / RNM / RTL export")
    _common(p)
    p.add_argument("--out", required=True, metavar="DIR")
    p.add_argument("--flavors", default="rtl,rnm,ams")
    p.add_argument("--n-golden", type=int, default=16384)
    p.add_argument("--n-vectors", type=int, default=4096)
    p.set_defaults(fn=cmd_export)

    p = sub.add_parser("config", help="write a config file, or --check one")
    _common(p)
    p.add_argument("--out", metavar="FILE")
    p.add_argument("--check", metavar="FILE")
    p.set_defaults(fn=cmd_config)
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.fn(args))
    except SystemExit:
        raise
    except (ValueError, KeyError, TypeError, FileNotFoundError) as e:
        print(f"pllsim: {type(e).__name__}: {e}", file=sys.stderr)
        return 1
    except BrokenPipeError:                  # `pllsim ... | head`
        return 0


if __name__ == "__main__":            # pragma: no cover
    sys.exit(main())
