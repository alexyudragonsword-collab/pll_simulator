# Roadmap — known gaps

**Generated** by `docs/gen_roadmap.py` against v0.9.2.
Every number here is measured at generation time, not remembered.

This is a register of what is known to be missing, not a schedule.  A
roadmap of intentions is the documentation most likely to go stale, and
this project has already spent two releases repairing stale docs — so
each entry says what is true today and what would close it.

## Type checking

15 paths are in the `mypy` gate (`pyproject.toml`).  What is
still outside, and what including it would cost:

| package | errors today | what it is |
|---|---|---|
| `src/pllsim/export` | 24 | the RTL/RNM/VAMS emitters — `rnm_golden.py` carries most of it: it builds heterogeneous row dicts for the golden CSV, so the types are genuinely loose rather than merely unannotated. |
| `src/pllsim/webgui` | 15 | the Streamlit pages — Mostly `st.number_input` returning a union that then indexes an array. Shallow, but touching every page for it is a wide diff for little. |

Shrinking that table is welcome.  Silencing it with `ignore_errors` is
not: an exclusion list that says what is missing is honest, where a
blanket ignore would read as "type-checked".

## Coverage

The floor is 88% (`[tool.coverage.report]`).  Two places where the
number needs reading rather than raising:

- **`guiqt/page_analysis.py`, ~59%** — FitPage's file-dialog branches need a GUI file picker to reach.
- **`webgui/Home.py` and `webgui/_common.py`, 0%** — **Not** untested.  AppTest execs each page rather than importing it, so coverage attributes none of the 23 tests that drive them, and the pages under `webgui/pages/` do not appear in the report at all.  Do not 'fix' this with a test that merely imports them.

## Limits that are scope, not backlog

### No silicon correlation

Every benchmark is a published paper, not a part we taped out.  Un-published circuit parameters are labelled technology-plausible assumptions, so what is verified is architectural consistency, not point agreement with any one chip.  One measured phase-noise curve from our own silicon moves the tool from *architecturally* consistent to *process* consistent -- it is the single highest-value thing on this page and the only one the codebase cannot do for itself.

### v0.9.1 has no tag and never will

It was bumped and merged without release notes, so auto-release had nothing to act on.  Backfilling is impossible: a ref whose `.github/workflows/ci.yml` differs from the current one is refused to `GITHUB_TOKEN` by `git push` and by the refs API alike.  Its code is on main and shipped inside v0.9.2; `docs/release-notes/v0.9.1.md` is the record.

### The deck is QA'd by measurement, not by rendering

LibreOffice cannot load a pptx in this container -- not even an empty one -- so `docs/reports/qa_deck.py` measures wrapped text against its own box with real CJK font metrics and draws an approximate raster.  The overflow numbers are trustworthy (same string, same size, same box); the raster is not PowerPoint's layout and must not be used to judge final appearance.

### Coverage counts lines that ran, not answers that were checked

The physics is pinned by cross-domain comparison -- settled time-domain periodogram against the linear model, 2-3 dB band-averaged -- not by the percentage.  Raising coverage is not the same as raising confidence, and the 88% floor exists to catch a module losing its tests, nothing more.
