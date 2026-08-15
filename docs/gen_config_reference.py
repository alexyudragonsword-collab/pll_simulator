"""Generate docs/config-reference.md from the configs themselves.

Every editable field of every architecture, with its unit and a representative
value.  Written rather than hand-maintained because it is derived: the fields
come from the config dataclasses, and the units and labels from
`guiutil.FIELD_INFO` -- the same table both GUIs build their forms from, so a
field documented here is a field the forms label properly, and neither can
drift from the other.

Deliberately not a docstring-scraping API reference.  Of 468 public names in
the package, the ones a user actually looks up are the config fields: what can
I set, in what unit, and what does a sane value look like.  A generated page
listing every function signature would answer a question nobody asks.

    python docs/gen_config_reference.py        # rewrites config-reference.md
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

OUT = Path(__file__).with_name("config-reference.md")

# one preset per architecture, chosen to have the most sub-configs populated
# (a fractional preset carries the DTC and delta-sigma fields an integer one
# does not, so it documents strictly more)
REPRESENTATIVE = [
    ("CPPLL", "cppll_frac_38p4m_6g", "charge-pump PLL, fractional-N with DTC"),
    ("SSPLL", "sspll_frac_19p2m_4p806g", "sub-sampling PLL with FLL"),
    ("SPLL", "spll_frac_52m_6p253g", "reference-sampling PLL"),
    ("ADPLL (TDC)", "adpll_100m_10g", "all-digital PLL, counter + TDC"),
    ("ADPLL (BBPD)", "adpll_bb_100m_10g", "all-digital PLL, DTC + bang-bang"),
    ("ILCM", "ilcm_250m_12g", "injection-locked clock multiplier with FTL"),
    ("MDLL", "mdll_150m_2p4g", "multiplying DLL"),
]

GROUPS = {
    "": "Top level",
    "osc": "osc — oscillator (`blocks.oscillator.OscConfig`)",
    "cp": "cp — charge pump / PFD (`blocks.chargepump.CPConfig`)",
    "filt": "filt — loop filter (`blocks.loopfilter.FilterDesign`)",
    "sampler": "sampler — sampling PD (`blocks.sampler.SamplerConfig`)",
    "tdc": "tdc — time-to-digital converter (`blocks.tdc.TDCConfig`)",
    "dlf": "dlf — digital loop filter (`arch.adpll.DLFConfig`)",
    "frac": "frac — fractional-N (`arch.cppll.FracConfig`)",
    "frac.dtc": "frac.dtc — digital-to-time converter (`blocks.dtc.DTCConfig`)",
    "frac.dtc_cal": "frac.dtc_cal — background DTC gain calibration",
    "lock_detect": "lock_detect — lock detector (`blocks.lockdetect`)",
}


def fmt(v) -> str:
    if v is None:
        return "_unset_"
    if isinstance(v, float):
        if v == 0:
            return "0"
        return f"{v:g}"
    if isinstance(v, tuple):
        return "()" if not v else "(" + ", ".join(f"{x:g}" if
                                                  isinstance(x, float)
                                                  else str(x) for x in v) + ")"
    return str(v)


def group_of(path: str) -> str:
    parts = path.split(".")
    for n in (2, 1):
        if len(parts) > n and ".".join(parts[:n]) in GROUPS:
            return ".".join(parts[:n])
    return parts[0] if len(parts) > 1 else ""


def main() -> int:
    from pllsim import presets
    from pllsim.guiutil import FIELD_INFO, enumerate_fields

    lines = [
        "# Configuration reference",
        "",
        "**Generated** by `docs/gen_config_reference.py` — edit the configs or",
        "`guiutil.FIELD_INFO`, not this file.  `tests/test_docs_consistency.py`",
        "fails when the two disagree.",
        "",
        "Every field below is editable from both GUIs (the forms are built from",
        "the same table) and settable in code:",
        "",
        "```python",
        "from pllsim import presets",
        "p = presets.cppll_frac_38p4m_6g()",
        "p.cfg.cp.mismatch_pct = 3.0          # a dotted path below is an attribute path",
        "p.cfg.frac.dtc.inl_sin = (50e-15, 1.0, 0.3)",
        "ar = p.analyze()",
        "```",
        "",
        "Values shown are that preset's, as a sense of scale — not defaults.",
        "`_unset_` means the field is `None`, which is a legal value the GUIs",
        "show as an empty box (an unlimited control-voltage range, a noise",
        "figure to be derived rather than declared).",
        "",
    ]

    for title, preset, blurb in REPRESENTATIVE:
        pll = presets.ALL_PRESETS[preset]()
        specs = enumerate_fields(pll.cfg)
        lines += [f"## {title}", "",
                  f"{blurb} — `presets.{preset}()`, {len(specs)} fields.", ""]
        by_group: dict[str, list] = {}
        for s in specs:
            by_group.setdefault(group_of(s.path), []).append(s)
        for g, items in by_group.items():
            lines += [f"### {GROUPS.get(g, g)}", "",
                      "| field | unit | value | meaning |",
                      "|---|---|---|---|"]
            for s in items:
                unit = s.unit or "—"
                lines.append(f"| `{s.path}` | {unit} | `{fmt(s.value)}` | "
                             f"{s.label_en} / {s.label_zh} |")
            lines.append("")

    undocumented = set()
    for _t, preset, _b in REPRESENTATIVE:
        for s in enumerate_fields(presets.ALL_PRESETS[preset]().cfg):
            if s.path.split(".")[-1] not in FIELD_INFO:
                undocumented.add(s.path)
    if undocumented:
        lines += ["## Fields with no entry in `FIELD_INFO`", "",
                  "These show their raw names in the GUI forms too — a box",
                  "labelled with a field name tells a user nothing about what",
                  "to type.  Add them to `guiutil.FIELD_INFO`.", ""]
        lines += [f"- `{p}`" for p in sorted(undocumented)] + [""]

    OUT.write_text("\n".join(lines))
    print(f"{OUT}: {len(lines)} lines, "
          f"{len(REPRESENTATIVE)} architectures, "
          f"{len(undocumented)} undocumented fields")
    return 0


if __name__ == "__main__":
    sys.exit(main())
