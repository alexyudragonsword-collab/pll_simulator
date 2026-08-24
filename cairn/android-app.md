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

### Navigation: deliberately unlike either desktop GUI, and currently doubled

The phone does not copy Qt's page list or the web GUI's sidebar, and that is
a decision, not a gap: 412 px could not hold eight entries, so the original
tab bar squeezed them to `min-width: 4em` two-character stubs with the last
few off-screen behind a horizontal scroll — **an entry you cannot see does not
exist**. Since 2026-08-24 the page carries two shells and the APK picks one at
build time:

| shell | flavor | what it is |
|---|---|---|
| `tabs` | `:app:assembleTabsDebug` | the original horizontal bar |
| `drawer` | `:app:assembleDrawerDebug` | left drawer, opens by horizontal slide, closes on choose |

The two are **one shell over one set of buttons**: the same `#tabs` element,
the same `<button data-tab="…">` markup, the same `showTab()`. Only the CSS
(keyed on `html[data-nav]`) and ~60 lines of pointer-drag differ. That was the
governing constraint — two independent navs would be two things to maintain,
and this repository has paid for that twice already (the two GUIs that drifted
for several releases, the group labels that lived in three places). It is also
why every `#tabs button` selector in `app.js` and both regexes in
`test_android_parity.py` kept working unchanged.

The mode travels as `?nav=tabs|drawer` in the page URL rather than as a
compile-time constant, so `tests/android_page_harness.py` drives **both** in
one run. Without that, whichever shell the flavor did not build would rot
unobserved.

Two things that carried over from earlier lessons rather than being
rediscovered: the drawer scrim has an explicit `#scrim[hidden] { display:
none }` (the busy overlay, below), and the drag uses **Pointer** events, not
Touch events, because `page.mouse` drives pointer events — a Touch-event
gesture would be verifiable only by hand. Mutation-checked: giving the scrim
an author `display` reproduces the old bug exactly (Chromium reports
`<div hidden id="scrim"> intercepts pointer events`), and disabling the edge
pull or dropping `setDrawer(false)` from `showTab()` both turn the harness
red.

Not reachable from the harness, so device-only: the hardware back button
(`MainActivity.onBackPressed` → `window.onAndroidBack`), gesture feel, display
cutouts, and whether the two `applicationIdSuffix`-separated APKs really
co-install.

**Both shells exist in order to be compared.** Once the comparison is
settled on a real phone, deleting the losing flavor is the finishing move —
"kept for comparison" stops being a reason the day you have compared.

### Plot zoom: matplotlib's toolbar on Qt, a full-screen viewer on Android

Asked for as "加上 matplotlib 的图片控件". Only one of the three surfaces can
literally have that, and saying so was the useful part of the answer:

| surface | before | now |
|---|---|---|
| Qt | `FigureCanvasQTAgg` with **no** toolbar | `NavigationToolbar2QT` per figure — home / back / forward / pan / zoom-rect / save |
| Android | base64 PNG in a WebView | tap a plot → full-screen viewer with pinch, double-tap and drag |
| web | `st.pyplot()` static PNG | **unchanged, deliberately** — see below |

The Qt half was a genuine omission, not a new feature: `FigureCanvasQTAgg`
was there since the GUI was written and the toolbar that normally accompanies
it never was. All 13 `set_figs()` call sites go through `widgets.FigList`, so
one change covers every Qt page. One toolbar **per figure**, because these
stacks routinely hold two unrelated plots (the PN breakdown and its IPN pie)
and a toolbar acts on one canvas.

Measured while building the Android side, and worth keeping: the bridge
renders at `dpi=130`, which for the workbench PN plot is **1153 × 766 px**
(131 KiB). In a 412 px column that is **2.80×** native. So double-tap zooms to
`naturalWidth / offsetWidth` rather than to a round number — a fixed 3× was
already past native and softening the very detail the zoom exists to show.
The viewer allows up to 8× by pinch; past ~2.8× it is upscaling, which is
sometimes still what you want.

Two lessons re-applied rather than re-learned:

- `#lightbox` is `display: flex` and covers the whole screen, so it carries an
  explicit `#lightbox[hidden] { display: none; }`. Without it the app would
  become an unresponsive black page — the busy-overlay bug, one layer up and
  much worse.
- The plot click is **delegated** (`document` → `closest('img.plot')`), not
  bound per render. Nine render paths inject plots into a dozen containers; a
  per-render binding is one somebody forgets on the next tab, which is the
  same shape as the bridge method with no caller.

Found by thinking about the device rather than the browser: the activity
handles orientation itself (`configChanges` in the manifest), so the WebView
reflows **without** a reload — the image gets a new box while the anchor
origin still describes the old one, and every zoom anchor after that is
wrong. A `resize` listener re-measures and returns to fit.

**Parity, deliberate:** the web GUI keeps its static `st.pyplot()` PNGs. It
runs on a desktop browser where the OS zoom is adequate and the plots are not
squeezed into 412 px, and Streamlit offers no matplotlib interaction short of
swapping the plotting backend — which would change how every figure in the
project looks. Not a gap; revisit only if someone actually uses the web GUI
on a phone.

**Known, pre-existing, not fixed here:** in the Qt GUI a figure whose minimum
width exceeds the viewport is clipped on the left (the second plot's title
reads "kdown @ 4.8 GHz"). Verified by screenshotting the same page with the
toolbar change stashed — identical clipping — so the toolbar did not cause it.

### Cursors: one set of numbers, two readouts

Asked for after the zoom ("结果图上能加 cursor 么"). Both surfaces snap to a
sample and then report **every** curve at that abscissa, worst first, because
"what is it at 1 MHz" and "which source is responsible" are two questions and
a crosshair reporting one (x, y) answers neither. A second cursor gives Δ and,
on a log axis, dB/dec.

The load-bearing decision is that neither side re-evaluates the model.
`plotting.figure_cursor_data()` reads `Line2D.get_xdata()` off the **rendered
figure**, so the readout cannot drift from the line under the finger; Qt reads
the same artists directly (no transfer, so full precision and no length cap)
and selects curves with the same `plotting.data_lines` predicate.

Measured, and each one changed the design:

| measurement | consequence |
|---|---|
| `bbox_inches="tight"` costs a constant **3.2 px** of x error | the bridge saves untrimmed; the map is then exact to 0.27 × 0.43 px |
| all 7 breakdown curves share one f grid | send it once — 57 → 28 KiB |
| the periodogram grid is arithmetic | `start/step/n` rebuilds it with **zero** error — 150 → 67 KiB |
| 4 significant digits showed −107.45 dBc/Hz as "−107.40" | 5 digits; worst transfer error now 0.0048 dB against a readout printing 0.01 |
| a 20 000-point transient is 481 KiB against a 131 KiB PNG | refused **by name** rather than thinned — a decimated cursor would read numbers the drawn curve does not show |

**A wrong diagnosis, recorded because the shape repeats.** The harness read
`vco = -111.12` where the preset says `-142.84` and it looked exactly like a
broken cursor. It was a broken *assertion*: `_workbench` runs earlier in the
same session and leaves `osc.pn_dbchz` at −90, so the plot on screen was an
edited configuration while the reference was the stock preset. −111.12 is
simply what that curve is with a −90 dBc/Hz oscillator.

Two rounds of defensive code went in before that was noticed — a pinned aspect
ratio, a `load` re-measure, a decode guard — on the theory that the image had
not laid out yet. None of them changed the failure, which was the signal that
the theory was wrong, and two were reverted. What survives is the `load`
re-measure, kept because a `src` assignment genuinely is asynchronous, and
labelled in the source as reasoning rather than measurement. The harness now
re-selects the preset before comparing, so the page and the reference are the
same configuration.

The lesson is the one this file keeps repeating from the other direction: when
a fix does not move the failure, the diagnosis is wrong. Adding a second fix on
top of the first is how three unnecessary defences end up in a file.

**A live bug this uncovered:** the full-screen viewer's ✕ never worked.
`setPointerCapture` on `#lightbox` does not merely retarget pointer events, it
moves the *click* target to the capturing element too, so the button's handler
never ran. It shipped in the drawer release and no test had ever tapped it —
the harness pressed the scrim and the back button instead. Both a text check
(the guard exists, and runs before the capture) and a real tap in the harness
now cover it.

Two mistakes of mine that measurement caught, recorded because the shape
repeats: curves were selected by label, which dropped the measured periodogram
(the main curve of the spur plot, which carries no legend entry) — the
transform is what separates a trace from an `axvline`; and grid uniformity was
tested on the *rounded* abscissa, where 6 significant digits at 100 MHz is
±100 Hz against a 2560 Hz step.

**Parity, deliberate:** the web GUI still has neither zoom nor cursor. Same
reason as before — Streamlit offers no matplotlib interaction short of
swapping the plotting backend.

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
