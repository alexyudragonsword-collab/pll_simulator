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
- The WebView page can be driven end-to-end without Android: serve
  `assets/www/` plus an HTTP shim for `window.host`, run real Chromium
  (Playwright) against the real bridge. That harness moved a form field and
  watched analyze jitter go 258.3 → 2955.2 fs, and ran a 12k-cycle simulate.

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

## Parity with the desktop GUIs (audited 2026-08-22)

8 of the Qt GUI's 11 pages have app equivalents. Within those 8, five
concrete gaps found by reading both sides rather than by memory:

| gap | where | consequence |
|---|---|---|
| `bank` bridge method is never called | app workbench | the coarse-band bank table Qt shows under analyze is absent; the method exists and is tested, only the render is missing |
| measured spectrum does not pass `fine_oversample` | app + **web** Spurs | Qt's spectrum plot can show the reference spur; the other two cannot. A three-way inconsistency that predates the app — Qt is the odd one out, and it is the one that is right |
| no `fine_oversample_note` on the Spurs tab | app Spurs | the "M too coarse, the spur will read low" warning appears only in the workbench. This is the silent-wrong-number class the repo cares most about |
| selector table drops the PM column | app Selector | `pm_deg` is in the bridge reply, unrendered |
| FLL banner goes blank for non-FLL architectures | app Hop | Qt says "no FLL in this architecture"; silence reads as a failed lookup |

Deliberate, not gaps: workbench cycle default (50k app vs 150k Qt — phone),
start offset in MHz (app follows the web GUI; Qt uses Hz), analytic spurs as
JSON rather than a table, and no "re-run live" button on Benchmarks (Qt's is
redundant — `benchmark_table()` already computes its linear column live).

**Third copy of the group labels:** `guiqt/widgets.py` keeps its own
English-only `GROUP_TITLES` beside `guiutil.GROUP_LABELS` (which the web GUI
and the app share). The key sets agree today — checked — but a new
sub-config would have to be added in two places.

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
