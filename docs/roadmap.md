# Roadmap — known gaps

**Generated** by `docs/gen_roadmap.py` against v0.9.3.
Every number here is measured at generation time, not remembered.

This is a register of what is known to be missing, not a schedule.  A
roadmap of intentions is the documentation most likely to go stale, and
this project has already spent two releases repairing stale docs — so
each entry says what is true today and what would close it.

## Type checking

2 paths are in the `mypy` gate (`pyproject.toml`).
Nothing in `src/pllsim` is outside it: `export/` and `webgui/`
were the last two out, fixed and gated together.  A future
exclusion goes in this generator's `TYPE_CANDIDATES` so its cost
is measured, not remembered.

## Coverage

The floor is 88% (`[tool.coverage.report]`).  Two places where the
number needs reading rather than raising:

- **`guiqt/page_analysis.py`, ~59%** — FitPage's file-dialog branches need a GUI file picker to reach.
- **`webgui/Home.py` and `webgui/_common.py`, 0%** — **Not** untested.  AppTest execs each page rather than importing it, so coverage attributes none of the 23 tests that drive them, and the pages under `webgui/pages/` do not appear in the report at all.  Do not 'fix' this with a test that merely imports them.

## Cross-domain model boundaries

Where the linear model and the time-domain engine legitimately
diverge.  Each boundary has a runtime warning note (all three GUIs
show it), a machine-readable predicate, and — where the divergence
is bounded — a tolerance allowance the sweep grants only while the
flag is active.  Source of truth: `pllsim.validation.BOUNDARIES`;
enforced by `tests/test_cross_domain_sweep.py` on every push.

| code | allowance | statement |
|---|---|---|
| `ct-approx` | +5.5 dB | CPPLL/SPLL analyze() is a continuous-time approximation; past UGB > fref/10 the sampled loop's peaking deviates from it, and the time domain is the reference in that region. |
| `jitter-band-clip` | — | simulate() integrates jitter only to 0.45*fref (a reference-edge record shows nothing above it); analyze() integrates the full int_band.  The two headline jitter numbers cover different bands whenever int_band reaches past 0.45*fref. |
| `flicker-floor` | — | Synthesized flicker is only faithful above max(fref/n_settled, fref/65536); a comparison band starting below that floor compares the model against noise the run never generated. |
| `tuning-swing` | — | The analog loops' control-voltage law is unbounded unless OscConfig sets v_min/v_max: fout is reached wherever it needs the varactor to go.  Flagged when fout needs more than +/-1.5 V of travel from f0 (no single band spans that; the coarse bank is the physical answer) or, with a range set, lies outside it (the loop rails and never reaches fout).  The two domains agree here -- both follow the same law -- so this is a modelling-range statement, not a comparison tolerance. |
| `conditional-stability` | — | The open loop crosses unity gain more than once; phase margin at one crossing does not describe the loop and the linear jitter integral spans a non-small-signal region. |
| `bbpd-linearization` | +1.5 dB | The BBPD linear gain is a describing-function approximation; when the loop is quantization-dominated it over-predicts in-band noise by 2-4 dB and the time domain is the reference. |
| `dsm-tonal` | +1.5 dB | The linear model budgets the DSM/DTC residual as white noise (ShapedQuantization); the actual residual is deterministic and tonal, concentrated at frac-related offsets.  For near-rational fractions most of that power sits in tones outside (or at the edge of) the comparison band, so the in-band PSDs legitimately differ -- the frac_spur table is the deterministic complement the white budget stands in for. |

## Cross-domain gaps — pinned here, re-measured on every push

Confirmed points where the deviation exceeds the flagged allowance.
Each is pinned at its measured worst-band value (120k cycles, seed
1); the sweep fails if a re-measurement drifts more than the slack
in either direction — getting better is also a failure, because it
means this register no longer describes the tool.

| point | family | pinned |
|---|---|---|
| `cppll-fref-x0.5` | `ct-peaking` | 3.87 dB |
| `cppll-ugb-x1.6` | `ct-knee` | 5.26 dB |
| `cppll-ugb-x1.9` | `ct-knee` | 6.54 dB |
| `cppll-pm45` | `ct-filter-shape` | 3.90 dB |
| `cppll-fine-m8` | `engine-pulse-shape` | 2.78 dB |
| `cppll_frac-fref-x0.5` | `dsm-tonal` | 3.90 dB |
| `sspll_frac-stock` | `dsm-tonal` | 6.84 dB |
| `sspll_frac-fref-x0.5` | `dsm-tonal` | 4.40 dB |
| `sspll_frac-fref-x2.0` | `dsm-tonal` | 9.32 dB |
| `sspll_frac-near-int` | `dsm-tonal` | 6.79 dB |
| `spll-fref-x0.5` | `ct-peaking` | 2.08 dB |
| `mdll-fref-x2.0` | `zoh-approx` | 3.45 dB |

## Limits that are scope, not backlog

### No silicon correlation

Every benchmark is a published paper, not a part we taped out.  Un-published circuit parameters are labelled technology-plausible assumptions, so what is verified is architectural consistency, not point agreement with any one chip.  One measured phase-noise curve from our own silicon moves the tool from *architecturally* consistent to *process* consistent -- it is the single highest-value thing on this page and the only one the codebase cannot do for itself.

### v0.9.1 has no tag and never will

It was bumped and merged without release notes, so auto-release had nothing to act on.  Backfilling is impossible: a ref whose `.github/workflows/ci.yml` differs from the current one is refused to `GITHUB_TOKEN` by `git push` and by the refs API alike.  Its code is on main and shipped inside v0.9.2; `docs/release-notes/v0.9.1.md` is the record.

### The deck is QA'd by measurement, not by rendering

LibreOffice cannot load a pptx in this container -- not even an empty one -- so `docs/reports/qa_deck.py` measures wrapped text against its own box with real CJK font metrics and draws an approximate raster.  The overflow numbers are trustworthy (same string, same size, same box); the raster is not PowerPoint's layout and must not be used to judge final appearance.

### Coverage counts lines that ran, not answers that were checked

The physics is pinned by cross-domain comparison -- settled time-domain periodogram against the linear model, 2-3 dB band-averaged -- not by the percentage.  Raising coverage is not the same as raising confidence, and the 88% floor exists to catch a module losing its tests, nothing more.
