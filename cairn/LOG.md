# Project Cairn Log

This file records substantive progress in reverse-chronological order — newest entry at the top, right below this line. Keep each entry short — summary and pointer only; conclusions settle into `cairn/<topic>.md`.

## 2026-08-25 · Cython cross-compile spike: the core ships as .so in a real APK

- Asked how reverse-engineerable the APK is. It is trivially so: `strings` on
  a compiled module prints the whole DSB convention docstring, and bytecode
  keeps line numbers and variable names.
- Built the answer rather than argued it. CI cross-compiled `core/` for both
  ABIs, checked the ELF machine type against the wheel tag, and the APK now
  carries 11 `.so` and no `.py` under `pllsim/core/`.
- The reason it was tractable: Android CPython is on **Maven Central**, the
  compiler is plain NDK clang, and cythonised pure-Python needs **only
  Python.h** — so nothing rebuilds numpy/scipy. All read from Chaquopy's
  source, since chaquo.com is unreachable here.
- Behaviour unchanged, by the project's own suite: 564 passed / 13 skipped
  with every `.py` deleted, `analyze()` still 258.3043 fs.
- Size was never the obstacle: 4.7 MB per ABI, ~11% of the APK. My first
  estimate was wrong by having guessed instead of compiling.
- Two traps: `--no-index` would have cut numpy/scipy/matplotlib off from
  Chaquopy's index, and installing a wheel by path puts the arm64 build into
  the x86_64 variant. Both in `cairn/android-app.md`.
- Bounds worth repeating: `app.js` stays plain text and presets are one
  `fields()` call away, so this protects formulas only.

## 2026-08-24 · The drawer wins; the tab bar and everything selecting it are deleted

- Comparison settled on a device: the phone keeps the left drawer. Removed
  the bar, the `?nav=` switch, both Gradle flavors, `BuildConfig.NAV_MODE`,
  the workflow's `variant` input, and the harness's two-shell loop.
  `:app:assembleDebug` is the only build again.
- Cheap to remove because both were deliberate a week ago: one set of buttons
  shared between shells (so deleting one was deleting CSS), and a page-level
  `?nav=` rather than a compile-time constant (so only three JS guards
  branched on it).
- Also fixed the Qt title clipping, which was **not** what I had assumed. The
  canvas does not crop: matplotlib resizes the figure to the widget. The IPN
  pie anchors its legend outside the wedges, so `tight_layout` leaves the
  axes on the left ~70% — and a title centred on *that* started at x = −77 px
  on a 666 px canvas. Font sizes are absolute points, so it only shows once
  the figure is drawn narrower than it is laid out for. Centred on the figure
  instead, and 4 window widths are now pinned by a test.
- Two more of my assertions matched my own comments rather than code (`?nav=`
  in the prose recording its removal) and mis-counted path parents. Same
  shape as the `setPointerCapture` one yesterday; both fixed to pin code.

## 2026-08-24 · Readout cursors on Qt and Android: every curve at once, plus Δ

- `plotting.figure_cursor_data()` extracts the axes rectangle in PNG pixels
  plus the curves, **from the rendered figure**, so no surface re-evaluates
  the model and no readout can drift from the drawn line.
- Qt: `PlotCursor` in `widgets.FigList`, on every data axes of every page.
  Android: the bridge ships the map with every plot and the full-screen
  viewer draws it.
- Measurements that changed the design, not decorated it: the tight crop
  costs 3.2 px of x (dropped it — map now exact to 0.3 px); the shared f grid
  and the arithmetic periodogram grid cut payloads 57→28 and 150→67 KiB; 4
  significant digits displayed −107.45 dBc/Hz as "−107.40", so 5.
- **Found a shipped bug:** the viewer's ✕ never worked. `setPointerCapture`
  moves the *click* target too, so the button's handler never ran. It went
  out in the drawer release because the harness tapped the scrim and the
  back button, never the ✕.
- Four of my own mistakes, all caught by measurement: a Qt slope test using a
  pair exactly one decade apart (where the division is invisible); a parity
  regex matching `setPointerCapture` inside its own explaining comment; path
  arithmetic pointing at a directory that does not exist; and a harness
  assertion comparing the readout against a preset the page was no longer
  showing, which I first mistook for an image-load race and "fixed" twice
  before noticing the failure never moved. See `cairn/android-app.md`.

## 2026-08-24 · Plots become zoomable: Qt gets its toolbar, Android a full-screen viewer

- Qt was missing `NavigationToolbar2QT` outright — `FigureCanvasQTAgg` had
  been there since the GUI was written, the toolbar never was. One change in
  `widgets.FigList` covers all 13 `set_figs()` call sites; one toolbar per
  figure, since a stack often holds two unrelated plots.
- Android cannot have a matplotlib widget at all (it is a PNG in a WebView),
  so: tap a plot → full-screen viewer, pinch / double-tap / drag / back.
- Double-tap goes to `naturalWidth / offsetWidth`, not a round number. The
  bridge renders 1153 px wide at dpi=130, which in a 412 px column is 2.80×
  native — a fixed 3× was already upscaling and softening the detail.
- Two old lessons re-applied without being re-learned: the viewer carries an
  explicit `[hidden] { display: none }` (it is `display: flex` over the whole
  screen — the busy-overlay bug would have been much worse here), and the
  plot click is delegated rather than bound per render.
- One defect found by thinking about the device, not the browser: the
  activity handles orientation itself, so rotating relayouts the image while
  the anchor origin still describes the old box. A `resize` listener
  re-measures.
- Two weak assertions caught by mutation and fixed: `findChildren` finds a Qt
  toolbar that was never added to a layout (invisible to the user), and
  `"closeLightbox()" in js` passed with the back-button branch deleted
  because the string also lives in the close button. Both now pin the
  load-bearing structure.
- web GUI deliberately unchanged; recorded under Parity in
  `cairn/android-app.md` so it reads as a decision, not drift.

## 2026-08-24 · Android gets a second navigation shell; both ship, build-time choice

- A left drawer that opens by horizontal slide, alongside the original tab
  bar. 412 px could not hold eight entries: the bar squeezed them to
  two-character stubs with the last few behind a scroll, and an entry you
  cannot see does not exist.
- **One shell over one set of buttons**: same `#tabs`, same `data-tab`
  markup, same `showTab()`; only CSS keyed on `html[data-nav]` and ~60 lines
  of pointer-drag differ. Every `#tabs button` selector and both parity
  regexes kept working untouched — that was the point, not a coincidence.
- Mode arrives as `?nav=`, not a compile-time constant, so the harness drives
  both in one run; the APK passes `BuildConfig.NAV_MODE` through the same
  query string. Two Gradle flavors (`assembleTabsDebug` /
  `assembleDrawerDebug`) with different application ids, so both install at
  once — comparison is the whole reason the bar was kept.
- Verified: harness green on both shells end to end; 4 mutations red,
  including the scrim reproducing the busy-overlay bug verbatim
  (`<div hidden id="scrim"> intercepts pointer events`). 3 new browser-free
  parity tests.
- One self-inflicted timeout worth remembering: `wait_for_selector` defaults
  to `state="visible"`, so waiting on `#scrim[hidden]` waits for a
  `display:none` element to become visible. Forever.
- Device-only, and said so in the PR: hardware back, gesture feel, cutouts,
  and whether the two APKs really co-install. See `cairn/android-app.md`
  (Navigation) — including that deleting the losing flavor is the finishing
  move once the comparison is settled.

## 2026-08-23 · IPN breakdown pie on the benchmark pages (all three surfaces)

- `AnalysisResult.ipn_shares()` + `plotting.plot_ipn_pie()`; `dominant_source`
  now derives from the former, so there is one ranking, not two.
- The pie's premise was checked before it was drawn: per-source integrated
  powers sum to `total` to 1e-9 on all five benchmarks, and the per-source
  jitters recombine in quadrature to the reported total (80.9 fs both ways
  on Wu'19). Both are tests, parametrized over every benchmark preset.
- Labels carry each source's own RMS jitter alongside its percentage,
  because a share of power is not a share of jitter — halving a 50%
  contributor buys 29% of the total, not 25%.
- Wired into Qt, web and the Android tab in the same change (the rule), and
  driven on each. 4 mutations verified red.
- Then extended from the 5 benchmark presets to **every** analyze(): the
  workbench carries it on all three surfaces, so it covers all 15 presets
  plus edited configs and selector candidates. Checked on each of the 15 —
  shares sum to 100.0000% including the degenerate ILCM case (3 sources,
  one at 97.9%), which is where a pie routine would fall over.

## 2026-08-22 · All five parity gaps closed, plus a Qt crash the audit surfaced

- The five app/Qt differences are fixed and each verified in Chromium; see
  `cairn/android-app.md` → Parity for the table and one **correction**: the
  bank table is empty in *all three* GUIs for stock presets, so that gap's
  user-visible consequence was smaller than the audit claimed.
- **New bug found while fixing:** Qt's Spurs page passed M straight into
  `simulate()`, and two of its own seven fractional presets are ADPLLs that
  take no `fine_oversample` — `TypeError` on either. All three surfaces now
  route through `simulate_kwargs`. Regression test mutation-verified.
- Measured, not assumed: M=0 shows nothing at fref; M=64 puts the reference
  spur at −111.9 dBc. That is what the web and app spectra were missing.
- The rule stopped being prose-only: `tests/test_android_parity.py` (16
  checks, browser-free, 3 mutations verified) and the committed
  `tests/android_page_harness.py`. `guiqt/widgets.py`'s third copy of the
  group labels is gone.

## 2026-08-22 · Rule recorded: a change is not done until all three front ends are checked

- `AGENTS.md` gains "Three front ends, one contract" — web / Qt / Android
  share `guiutil`, `presets`, `plotting` and the `arch/` signatures, so a
  shared change must be *run* on all three, with the exact command per
  surface (and the reminder to read the Qt skip count, not the silence).
  `CONTRIBUTING.md` carries the contributor-facing version plus what CI
  does not enforce.
- Two corollaries from this week's findings: a bridge method with no caller
  is half a feature (`bank`), and deliberate differences go in
  `cairn/android-app.md` → Parity so a decision is not read as a gap.
- **Prose-only so far.** The Android-page check needs the Chromium shim
  harness, which currently exists only in a session scratchpad; committing
  it (and a test asserting every `appbridge._METHODS` entry is referenced by
  `app.js`) is what would make this rule self-enforcing.

## 2026-08-22 · Android line paused after a parity audit against the Qt GUI

- v3+v4 merged (#38, CI + APK green). Android work stops here by request.
- Audited both GUIs side by side: 8/11 pages covered, and **5 within-page
  gaps** the page count hid — see `cairn/android-app.md` → Parity. The one
  that matters is the missing `fine_oversample_note` on the app's Spurs tab
  (an under-resolved M reads the spur low, silently); the one worth fixing
  everywhere is that only Qt passes `fine_oversample` to the measured
  spectrum — web and app both cannot show the reference spur there.
- Two earlier judgments **corrected by measurement**: Fit's synthetic-demo
  path needs no file picker and fits in <0.03 s; MonteCarlo runs serially
  at 0.88 s/chip (50k cycles) with `n_jobs=1`, so neither is blocked the
  way the first pass claimed. Correction note is in the topic note.
- `guiqt/widgets.py` still keeps a third copy of the form group labels.

## 2026-08-22 · Android app v4: Modulation and Drift tabs (8/11 Qt pages)

- appbridge grew modulate / drift / drift_info; EVM 0.98%→2.90% under 5%
  direct-path error (the ex17 sensitivity), drift lag 2.60% at the slew
  wall with the −71.4 dBc lag spur.
- Mutation lesson worth keeping: "lag(slow) < lag(fast)" survived a bridge
  that never injected the ramp — the lag *formula* carries the drift array,
  so monotonicity holds with zero simulation coupling. The discriminating
  assertion is "the calibrator tracked": peak lag strictly below total
  drift. Recorded in the test docstring.

## 2026-08-22 · Android app v3: Selector, Synthesis, Benchmarks tabs

- appbridge grew 7 methods + a selector→workbench candidate handoff: the
  synthesized candidate crosses via module state (`_CANDIDATES`), every
  consumer deep-copies, and all workbench methods take `candidate=`.
  bw_sweep reports requested-vs-returned (sweep_bandwidth silently skips
  infeasible UGB points — 5 asked, 3 answered must be visible).
- 4 new test groups, 5 mutations each red; Chromium end-to-end including
  the full handoff loop (candidate analyze 115→1014 fs via the form,
  back-to-presets restores). Coverage vs Qt: 6 of 11 pages in the app;
  the rest are listed with reasons in `cairn/android-app.md`.

## 2026-08-22 · mypy gate closed: files = ["src/pllsim"], 85/85, 0 errors

- export/ (24 errors) fixed at the *source*: FracConfig.dtc and
  SSPLL/SPLL.frac were annotated `"object | None"` since their creation —
  the type information died there, and every consumer error was fallout.
  Real types + a `_need()` narrowing helper in rnm_golden (restating what
  arch `__post_init__` validation already guarantees). `_DsmBase` gained the
  `step` contract its three subclasses always had.
- webgui/ (15) fixed: `HopResult.sim` object→`SimResult | None`;
  session_state round-trips annotated; arch-specific simulate kwargs go
  through a typed dict; 5_Fit's guard checked only one of two arrays.
- The files list collapsed to `["src/pllsim"]` — nothing is outside, so the
  roadmap's exclusion table is empty and gen_roadmap says so explicitly.
- Measurement trap logged: `cmd | tail; echo $?` reports tail's exit, not
  the command's — several earlier "exit=0" full-suite reads were unverified.
  pipefail from now on.

## 2026-08-22 · Android app v2: Spurs and Hop tabs

- appbridge grew 7 methods (spur_predict/spur_spectrum/spur_sweep/ref_spur,
  hop_check/hop/hop_stats); 6 new tests, each mutation-proven able to fail —
  including one whose first assertion over-specified the physics (in-band
  channels are a |NTF|~1 plateau, not a strict maximum at the smallest beat)
  and one that couldn't catch a dropped µs conversion until bounded both ways.
- Found en route: webgui Spurs page's "k max" input was read and passed to
  nothing for four releases — the decorative-parameter bug in the GUI layer.
  Removed.
- Both tabs driven end to end in Chromium against the real bridge.

## 2026-08-22 · Android app builds green; APK artifact produced

- `android.yml` run 2 on `7c7c5a6`: success in 2m45s after the sdist fix
  (run 1 died in Gradle 8 task validation — `install("../..")` trap, see
  `cairn/android-app.md`). Artifact `pllsim-debug-apk`, 84 MB, arm64+x86_64.
- Chaquopy resolved numpy/scipy/matplotlib for Python 3.10 from its own
  repo with pllsim's floors (`numpy>=1.24, scipy>=1.8, matplotlib>=3.7`) —
  the open question about its matplotlib version resolved itself green.
- Still unverified: touch on a physical phone (needs a sideload).
- Shipped as one PR (#36, two commits) rather than the planned two.

## 2026-08-18 · appbridge: JSON layer for the Android app (PR-1 of 2)

- `src/pllsim/appbridge.py` + tests: str→str JSON RPC over the existing
  `guiutil` machinery, in-package so pytest reaches it. 5 mutations each
  turned a test red before the suite was trusted.
- Found and fixed en route: `np.trapezoid` (numpy≥2-only) made the declared
  `numpy>=1.24` floor a lie; floors now measured — full suite green on
  Python 3.10 + numpy 1.24.4 + scipy 1.8.1, so `scipy>=1.8`.
- `GROUP_LABELS` moved webgui→guiutil (third consumer appeared).
- Conclusions to settle in `cairn/android-app.md` with PR-2.

## 2026-08-18 · Project Cairn initialized

- Initialized Project Cairn structure: `AGENTS.md`, `CLAUDE.md` (now the
  one-line `@AGENTS.md` stub), `.cairn/config.yaml`, `cairn/LOG.md`.
- Config: `git_policy: track`, `language: en`, graduation provider deferred
  (`none`), `migration_mode: start_fresh`.
- Retrofit, not greenfield: the 95 lines of always-read rules that were in
  `CLAUDE.md` (verify-do-not-infer, the generated-file table, the release
  mechanism, the two physics conventions) moved verbatim into `AGENTS.md`
  below the Cairn sections. Nothing was dropped — the pre-Cairn file is
  recoverable at `git show HEAD:CLAUDE.md`.
- No `cairn/ROADMAP.md` was created. `docs/roadmap.md` already fills that role
  and is *generated* (`docs/gen_roadmap.py`) so its numbers are measured; a
  second hand-written roadmap is the drift that file exists to prevent. See
  `AGENTS.md` → Reading order, step 4.
- `.gitignore` untouched: `track` writes no ignore rule, and no existing rule
  covered `cairn/`.
- Details: `AGENTS.md` and `.cairn/config.yaml`.
