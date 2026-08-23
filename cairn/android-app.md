---
type: project_topic
status: active
summary: "How pllsim runs on Android: the Chaquopy constraints that shaped the build, the bridge architecture, and the traps already hit."
tags: [android, chaquopy, packaging, gui]
contains: [pitfall, decision, correction]
created: "2026-08-18"
updated: "2026-08-22"
related: []
authoring_mode: ai_generated
---
# Android app (Chaquopy)

## Formation Context

The desktop stacks cannot ship to a phone: PySide6 has no practical Android
deployment and Streamlit is a server process. Chaquopy is the only Android
path with prebuilt numpy/scipy/matplotlib wheels (MIT, free), so the app is
a single-Activity WebView over `src/pllsim/appbridge.py`, with the form
generated from `guiutil.FIELD_INFO` — the same source as the Streamlit form,
the Qt form and the config reference. v1 shipped the workbench; v2 added
Spurs (analytic prediction, measured spectrum, reference-spur comparison,
worst-channel sweep) and Hop settling (FLL bound banner, hop anatomy, seed
statistics); v3 added Selector (requirement → 7 ranked architectures →
**candidate handoff into the workbench**, carried through module-level
bridge state that every consumer deep-copies), Synthesis (four filter
designers + jitter-vs-UGB sweep with a dropped-points caption) and
Benchmarks; v4 added Modulation (two-point GMSK + EVM, with the
samples-per-symbol caveat computed client-side from `list_presets` frefs)
and Drift (ramp tracking with the rate-vs-mu precheck as a live caption).
Still not in the app: Fit, MonteCarlo and Export — 8 of the Qt GUI's 11
pages have app equivalents. What each would actually cost is measured under
"Parity with the desktop GUIs" below, which corrects the first guess.

## Current Conclusions

- **Python is pinned to 3.10 and the pin is load-bearing.** Chaquopy's repo
  has no scipy wheel past 3.10 (chaquo/chaquopy#1237, still open). Bumping
  `version` in `android/app/build.gradle.kts` trades scipy away. Verified
  compatible by running the full suite on 3.10 + numpy 1.24.4 + scipy 1.8.1:
  305 passed, 0 failed. That run is also why the pyproject floors moved to
  `numpy>=1.24` (true only after the `np.trapezoid` fix) and `scipy>=1.8`.
- **The bridge is in the package, not the app** (`pllsim/appbridge.py`),
  so plain pytest drives it — the GUI-drift lesson applied in advance.
  str→str JSON only; errors in-band (`{"ok": false}`); NaN/Inf → `null`;
  plots as base64 Agg PNGs.
- **All Python runs on one background thread** in the app (single-lane
  executor): the engines have no locking, and the first call pays several
  seconds of numpy/scipy/matplotlib import — the page shows a boot state.
- **`MPLCONFIGDIR` must be set before `Python.start()`** (Kotlin `Os.setenv`
  to a writable app dir): matplotlib writes a font cache on first import and
  dies on a read-only default.
- The WebView page can be driven end-to-end without Android:
  `python tests/android_page_harness.py` stands up an HTTP shim for
  `window.host` and drives every tab in real Chromium against the real
  bridge. It moves a form field and watches analyze jitter go 258.3 → 2955.2
  fs, so a decorative control cannot pass. Not in CI (needs Playwright and
  several minutes); `AGENTS.md` names it as the required manual check.

## Lessons

- **`hidden` loses to any author `display`.** The busy overlay had
  `display:flex`; with the `hidden` attribute set it still intercepted every
  tap, invisibly. Found only because Chromium actually clicked the page;
  fixed with an explicit `#busy[hidden] { display: none }`.
- **`np.trapezoid` is numpy≥2-only** (renamed `trapz`). One call in
  `core/jitter.py` made the declared `numpy>=1.24` floor false for everyone,
  not just Android — 36 test failures from one root cause on numpy 1.24.
- A browser test that waits for a selector the *previous* run already
  satisfied reads stale DOM and passes on nothing — clear the output region
  (or wait on a state that cannot pre-exist) before clicking run.
- **Never `pip install` the repo root from a Gradle project that lives
  inside it.** `install("../..")` made the whole repository an input of
  Chaquopy's pip task; every AGP task's outputs then sat inside that input,
  and Gradle 8's validation failed the first CI run with five "uses this
  output without declaring a dependency" errors. The app embeds an sdist
  instead (`python -m build --sdist --outdir android/app/pysrc .`), which
  the fresh-venv check also proved installable with the old stack.

## Parity with the desktop GUIs (audited 2026-08-22, all five closed)

8 of the Qt GUI's 11 pages have app equivalents. The audit found five gaps
inside those 8 — all fixed the same day, each verified in a real browser:

| gap | where | how it was closed |
|---|---|---|
| `bank` bridge method was never called | app workbench | the table now renders above the analyze metrics. **Correction:** the audit said Qt "shows" it — in fact `osc_bank_report` returns nothing until the varactor has a control-voltage range, which no stock preset sets, so all three GUIs were empty by default. The gap was real, its user-visible consequence was not |
| measured spectrum ignored `fine_oversample` | app + **web** Spurs | both gained an M box. Measured: at M=0 nothing appears at fref; at M=64 the reference spur reads −111.9 dBc |
| no `fine_oversample_note` on the Spurs tab | app Spurs | live caption under both M boxes, carrying the under-resolved warning — the silent-low-reading class |
| selector table dropped the PM column | app Selector | rendered from the `pm_deg` the reply already carried |
| FLL banner went blank for non-FLL architectures | app Hop | says "no FLL in this architecture", as Qt does |

**A Qt bug the audit surfaced:** its Spurs page passed M straight into
`simulate()`, and two of the seven fractional presets in its own dropdown
are ADPLLs whose engines take no `fine_oversample` — so "Simulate + plot
spectrum" raised `TypeError` on either of them. All three surfaces now go
through `guiutil.simulate_kwargs`, which filters by the engine signature.
Regression test: `test_spurs_measured_spectrum_survives_an_adpll_preset`.

**Drift guards now in place:** `tests/test_android_parity.py` fails when a
bridge method has no caller (both directions) or an id `app.js` drives
disappears from `index.html`, at no browser cost; and
`tests/android_page_harness.py` is the committed Chromium harness the
AGENTS.md rule names. `guiqt/widgets.py` no longer keeps its own group
labels — it derives the English half from `guiutil.GROUP_LABELS`.

Deliberate, not gaps: workbench cycle default (50k app vs 150k Qt — phone),
start offset in MHz (app follows the web GUI; Qt uses Hz), analytic spurs as
JSON rather than a table, and no "re-run live" button on Benchmarks (Qt's is
redundant — `benchmark_table()` already computes its linear column live).

### Correction to the earlier "not portable" judgment

The first assessment (2026-08-22, earlier the same day) said Fit needs
Kotlin file-picker plumbing and MonteCarlo is too heavy for a phone. Both
were measured afterwards and both were too pessimistic:

- **Fit is mostly portable with no Kotlin at all.** Qt's "Load synthetic
  demo" path builds its curve from a preset plus 0.5 dB noise — no file I/O
  — and all three fit modes run in **under 0.03 s** (measured: Leeson,
  closed-loop, budget attribution on 248 points). Only the "Open CSV" half
  needs the file picker.
- **MonteCarlo is viable serially.** `monte_carlo(..., n_jobs=1)` needs no
  `ProcessPoolExecutor` (which is what would fail under Chaquopy, not the
  arithmetic): measured 2.49 s/chip at 150k cycles and 0.88 s/chip at 50k on
  this container, so ~20 chips at 50k is a phone-minute, not an hour.
- Export remains the genuinely poor fit: its product is a file tree for EDA
  tools, and the phone has no consumer for one.

## Open Questions

1. ~~Which numpy/scipy/matplotlib versions Chaquopy serves for 3.10~~ —
   answered by the first green `android.yml` run: its wheels satisfy the
   declared floors (`numpy>=1.24`, `scipy>=1.8`, `matplotlib>=3.7`) as they
   stand. Re-check if the floors ever rise.
2. Simulate runtime on a real phone (expected several× desktop; workbench
   default is 50k cycles for that reason). Needs a sideload measurement.
