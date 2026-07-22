"""Per-instance README generation: run lines, tolerances, noise policy."""
from __future__ import annotations

from dataclasses import replace


def flicker_delta_fs(pll) -> float | None:
    """How many fs of integrated jitter the RNM export ignores (no 1/f^3)."""
    try:
        ar_full = pll.analyze()
        osc0 = replace(pll.cfg.osc, pn_f1f3=0.0)
        pll2 = type(pll)(replace(pll.cfg, osc=osc0))
        ar_no = pll2.analyze()
        return ar_full.jitter_fs - ar_no.jitter_fs
    except Exception:
        return None


def emit_readme(name: str, kind: str, files: dict[str, list[str]],
                golden: dict[str, float], warnings: list[str],
                flicker_fs: float | None) -> str:
    rtl_files = files.get("rtl", [])
    rnm_files = files.get("rnm", [])
    ams_files = files.get("ams", [])
    lines = [f"# {name} — pllsim Verilog-AMS export", ""]
    lines += [f"architecture kind: `{kind}` — generated from the Python "
              "config; regenerate with pllsim.export, do not hand-edit.", ""]
    lines += ["## Golden scalars (from the Python engine)", ""]
    for k, v in golden.items():
        lines.append(f"* `{k}` = {v:.10g}")
    lines += ["", "## How to run", ""]
    if rtl_files:
        tbs = [f for f in rtl_files if f.startswith("tb/")]
        lines += ["### RTL (bit-true digital blocks — verified with iverilog "
                  "at export time)", "", "```sh", "cd rtl"]
        for t in tbs:
            blk = t.replace("tb/tb_", "pllsim_").replace(".v", ".v")
            lines.append(f"iverilog -g2005 -o sim {t} {blk} && vvp sim")
        lines += ["# or: xrun -sv " + " ".join(rtl_files), "```", ""]
    if rnm_files:
        lines += ["### RNM / wreal (digital-top regressions)", "", "```sh",
                  "cd rnm",
                  f"xrun -ams {name}_top_rnm.vams tb_{name}_rnm.vams",
                  "```", "",
                  "The tb replays `golden_rnm.csv` (noise-free) and compares "
                  "every cycle: integer paths exact, real paths rtol 1e-6, "
                  "absolute floor 1e-9.  Set `EN_NOISE=1` on the top for "
                  "jitter runs (goldens then do not apply).", ""]
    if ams_files:
        blocks = [f for f in ams_files if not f.startswith(("tb_", name))]
        lines += ["### Electrical AMS (block-level verification)", "",
                  "```sh", "cd ams",
                  "xrun -ams " + " ".join(blocks +
                                          [f"{name}_top_ams.vams",
                                           f"tb_{name}_ams.vams"]),
                  "```", "",
                  "Scalar checks only (lock frequency by edge counting, "
                  "vctrl bound): the continuous-time dynamics legitimately "
                  "differ from the impulse-discretized Python engine.",
                  "GHz cross events dominate wall time — the tb settle time "
                  "is sized from the Python lock estimate.", ""]
    lines += ["## Noise policy", "",
              "| flavor | supported | notes |",
              "|---|---|---|",
              "| RTL | none | deterministic digital logic |",
              "| RNM | white FM + white PM via $rdist_normal (EN_NOISE=1); "
              "DTC/BBPD/kT/C white jitter | 1/f and 1/f^3 flicker NOT "
              "representable event-driven |",
              "| AMS | transient deterministic; white_noise() only in "
              "small-signal .noise | use the RNM flavor for jitter |", ""]
    if flicker_fs is not None:
        lines += [f"Flicker the RNM export ignores: ~{flicker_fs:.1f} fs of "
                  "integrated jitter (Python analyze(): full Leeson profile "
                  "vs f_1f3 = 0).", ""]
    lines += ["## RNM vs Python engine — known deltas", "",
              "* the RNM loop filter always uses the impulse update; the "
              "Python engine switches to a pulse-width-aware update during "
              "acquisition (goldens are generated with impulse semantics "
              "and pytest-locked to agree with simulate() in lock)",
              "* band-select / supply-ripple / doubler side features are "
              "not in the RNM top", ""]
    if warnings:
        lines += ["## Export warnings", ""]
        lines += [f"* {w}" for w in warnings]
        lines.append("")
    return "\n".join(lines)
