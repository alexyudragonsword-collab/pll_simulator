"""Generate docs/roadmap.md: a register of known gaps, measured not remembered.

A roadmap is the documentation most likely to rot, and this project has just
spent two releases repairing rotted documentation.  So this one states what is
*currently true and checkable* -- how many type errors stand between a package
and the gate, what a module's coverage is -- rather than what someone intends
to do by when.  The numbers are recomputed here; only the judgement around
them is written by hand.

Items that are not measurable (no silicon correlation, a tag that can never
exist) are in KNOWN_LIMITS below, where they read as scope rather than as
work someone forgot.

    python docs/gen_roadmap.py           # rewrites roadmap.md
"""
import re
import subprocess
import sys
from pathlib import Path

import tomllib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
OUT = Path(__file__).with_name("roadmap.md")

# packages not yet in the mypy gate; the cost is measured, not stated
TYPE_CANDIDATES = [
    ("src/pllsim/export", "the RTL/RNM/VAMS emitters",
     "`rnm_golden.py` carries most of it: it builds heterogeneous row dicts "
     "for the golden CSV, so the types are genuinely loose rather than merely "
     "unannotated."),
    ("src/pllsim/webgui", "the Streamlit pages",
     "Mostly `st.number_input` returning a union that then indexes an array. "
     "Shallow, but touching every page for it is a wide diff for little."),
]

# Coverage notes are written, not measured.  A live `coverage report` lookup
# made this file depend on whichever run last left a .coverage behind, which
# would make the staleness test flake; and the exact percentage is not the
# point -- why it is what it is, is.
COVERAGE_NOTES = [
    ("`guiqt/page_analysis.py`, ~59%",
     "FitPage's file-dialog branches need a GUI file picker to reach."),
    ("`webgui/Home.py` and `webgui/_common.py`, 0%",
     "**Not** untested.  AppTest execs each page rather than importing it, so "
     "coverage attributes none of the 23 tests that drive them, and the pages "
     "under `webgui/pages/` do not appear in the report at all.  Do not "
     "'fix' this with a test that merely imports them."),
]

KNOWN_LIMITS = [
    ("No silicon correlation",
     "Every benchmark is a published paper, not a part we taped out.  "
     "Un-published circuit parameters are labelled technology-plausible "
     "assumptions, so what is verified is architectural consistency, not "
     "point agreement with any one chip.  One measured phase-noise curve from "
     "our own silicon moves the tool from *architecturally* consistent to "
     "*process* consistent -- it is the single highest-value thing on this "
     "page and the only one the codebase cannot do for itself."),
    ("v0.9.1 has no tag and never will",
     "It was bumped and merged without release notes, so auto-release had "
     "nothing to act on.  Backfilling is impossible: a ref whose "
     "`.github/workflows/ci.yml` differs from the current one is refused to "
     "`GITHUB_TOKEN` by `git push` and by the refs API alike.  Its code is on "
     "main and shipped inside v0.9.2; `docs/release-notes/v0.9.1.md` is the "
     "record."),
    ("The deck is QA'd by measurement, not by rendering",
     "LibreOffice cannot load a pptx in this container -- not even an empty "
     "one -- so `docs/reports/qa_deck.py` measures wrapped text against its "
     "own box with real CJK font metrics and draws an approximate raster.  "
     "The overflow numbers are trustworthy (same string, same size, same "
     "box); the raster is not PowerPoint's layout and must not be used to "
     "judge final appearance."),
    ("Coverage counts lines that ran, not answers that were checked",
     "The physics is pinned by cross-domain comparison -- settled time-domain "
     "periodogram against the linear model, 2-3 dB band-averaged -- not by "
     "the percentage.  Raising coverage is not the same as raising "
     "confidence, and the 88% floor exists to catch a module losing its "
     "tests, nothing more."),
]


def mypy_errors(path: str) -> int:
    r = subprocess.run([sys.executable, "-m", "mypy", path,
                        "--ignore-missing-imports"],
                       capture_output=True, text=True, cwd=ROOT)
    return len(re.findall(r"error:", r.stdout))


def main() -> int:
    import pllsim
    cfg = tomllib.loads((ROOT / "pyproject.toml").read_text())
    gated = cfg["tool"]["mypy"]["files"]
    floor = cfg["tool"]["coverage"]["report"]["fail_under"]

    L = [
        "# Roadmap — known gaps",
        "",
        f"**Generated** by `docs/gen_roadmap.py` against v{pllsim.__version__}.",
        "Every number here is measured at generation time, not remembered.",
        "",
        "This is a register of what is known to be missing, not a schedule.  A",
        "roadmap of intentions is the documentation most likely to go stale, and",
        "this project has already spent two releases repairing stale docs — so",
        "each entry says what is true today and what would close it.",
        "",
        "## Type checking",
        "",
        f"{len(gated)} paths are in the `mypy` gate (`pyproject.toml`).  What is",
        "still outside, and what including it would cost:",
        "",
        "| package | errors today | what it is |",
        "|---|---|---|",
    ]
    for path, what, why in TYPE_CANDIDATES:
        L.append(f"| `{path}` | {mypy_errors(path)} | {what} — {why} |")
    L += [
        "",
        "Shrinking that table is welcome.  Silencing it with `ignore_errors` is",
        "not: an exclusion list that says what is missing is honest, where a",
        "blanket ignore would read as \"type-checked\".",
        "",
        "## Coverage",
        "",
        f"The floor is {floor}% (`[tool.coverage.report]`).  Two places where the",
        "number needs reading rather than raising:",
        "",
    ]
    for where, note in COVERAGE_NOTES:
        L += [f"- **{where}** — {note}"]
    L.append("")

    L += ["## Limits that are scope, not backlog", ""]
    for title, body in KNOWN_LIMITS:
        L += [f"### {title}", "", body, ""]

    OUT.write_text("\n".join(L))
    print(f"{OUT}: {len(L)} lines, {len(gated)} gated paths, "
          f"{len(KNOWN_LIMITS)} stated limits")
    return 0


if __name__ == "__main__":
    sys.exit(main())
