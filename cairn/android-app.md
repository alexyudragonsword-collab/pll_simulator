---
type: project_topic
status: active
summary: "How pllsim runs on Android: the Chaquopy constraints that shaped the build, the bridge architecture, and the traps already hit."
tags: [android, chaquopy, packaging, gui]
contains: [pitfall, decision]
created: "2026-08-18"
updated: "2026-08-18"
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
Still not in the app: Fit (needs Android file-picker plumbing in Kotlin),
MonteCarlo (simulation-heavy), Export (no phone-side consumer for an EDA
file tree) — 8 of the Qt GUI's 11 pages now have app equivalents.

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

## Open Questions

1. Which exact numpy/scipy/matplotlib versions Chaquopy's repo serves for
   3.10 — chaquo.com is unreachable from the dev container, so the first CI
   run of `android.yml` is the authority. If its matplotlib is older than
   the declared `>=3.7` floor, the floor needs the same measured treatment
   scipy got.
2. Simulate runtime on a real phone (expected several× desktop; workbench
   default is 50k cycles for that reason). Needs a sideload measurement.
