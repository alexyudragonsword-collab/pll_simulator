# Contributing to pllsim

This file is the things you would otherwise learn by breaking them.  The
design rationale lives in [`docs/index.html`](docs/index.html); this is the
mechanics.

## Setup

```bash
pip install -e .[test,gui,guiqt]
pip install ruff mypy pytest-cov
pytest tests/                    # ~18 min; -x -k <name> while iterating
```

`QT_QPA_PLATFORM=offscreen` is needed for the desktop-GUI tests on a headless
box.  They *skip* without PySide6 and its system GL libraries rather than
fail — see the next section for why that matters.

## Three front ends share one library

`webgui/` (Streamlit), `guiqt/` (PySide6) and `android/` (a WebView over
`pllsim.appbridge`) all render the same models.  Anything they share —
`guiutil`, `presets`, `plotting`, an `arch/` signature, a config field —
lands in all three, so **a change is not finished until all three are
checked**, by running them rather than by reading them:

```bash
QT_QPA_PLATFORM=offscreen pytest tests/test_gui_smoke.py \
    tests/test_gui_compute.py -q            # web pages, via Streamlit AppTest
QT_QPA_PLATFORM=offscreen pytest tests/test_guiqt_smoke.py -q   # read the count
pytest tests/test_appbridge.py -q           # the Android bridge, no SDK needed
```

The Android *page* is not covered by any of those.  `python
tests/android_page_harness.py` is: it stands up its own shim for
`window.host` and drives every tab in real Chromium against the real
bridge (`pip install playwright` first; it is deliberately not in CI, and
not collected by pytest).  The invisible overlay that swallowed every tap,
and a crash in the measured spectrum, were both found that way and by
nothing else.

The phone navigates by a left drawer.  A horizontal tab bar coexisted with it
for one release, selected by `?nav=` and by a pair of Gradle flavors, so the
two could be compared on a real device; the comparison settled on the drawer
and everything that selected the bar went with it.  That is the pattern worth
copying — "kept so they can be compared" stops being a reason the day you have
compared, and a shell nobody chose is a shell that rots.

### Building the APK

From Actions → *Android APK* → Run workflow, which is manual and deliberately
off the push path.  Locally, the interpreted build is two commands:

```bash
python -m build --sdist --outdir android/app/pysrc .   # from the repo root
gradle -p android :app:assembleDebug
```

The first is not optional.  Chaquopy installs pllsim from `android/app/pysrc/`,
and the Gradle config refuses to guess: with nothing there it fails with that
exact command in the message.  It is an sdist rather than
`install("../..")` because a directory install makes the whole repository an
input of Chaquopy's pip task — and this Gradle project lives inside that
repository, so every AGP task's output lands inside the pip task's input and
Gradle 8's validation rejects the build.  That was the first CI run's failure.

`assembleDebug` builds whichever pllsim `pysrc/` holds: an sdist gives the
interpreted APK, wheels give the compiled one.  For the compiled build,
replace the first command with

```bash
python packaging/android_wheel.py --abi arm64-v8a --ndk $ANDROID_NDK_HOME
python packaging/android_wheel.py --abi x86_64   --ndk $ANDROID_NDK_HOME
```

and delete any sdist from `pysrc/` first — with both present Chaquopy still has
a pure-Python pllsim to resolve, and you would get the interpreted APK under
the impression it was compiled.  CI does both builds in one run and uploads
both.

The toolchain versions are pinned and several of them are load-bearing:

| what | version | why this one |
|---|---|---|
| `buildPython` / `setup-python` | **3.10** | must match `version` in `android/app/build.gradle.kts`; Chaquopy's repository has no scipy wheel past 3.10 (chaquo/chaquopy#1237) |
| Chaquopy plugin | 15.0.1 | resolves `"3.10"` to CPython target 3.10.13-0 |
| AGP (`com.android.application`) | 8.1.4 | Chaquopy 15.0.1 enforces a **minimum** of AGP 7.0.0 and no maximum (`Common.java: MIN_AGP_VERSION`) — an earlier note here claimed a supported 8.1–8.2 *range*, which the source does not say |
| Gradle | 8.2 | pairs with that AGP |
| Java | 17 | what AGP 8.x requires |
| `compileSdk` / `minSdk` | 34 / 24 | Chaquopy's own floors are `COMPILE_SDK_VERSION = 34` and `MIN_SDK_VERSION = 21`, so 24 is ours, not its |
| `abiFilters` | arm64-v8a, x86_64 | phones and the emulator.  Each ABI carries its own CPython plus numpy/scipy, so a third costs about 40 MB |

One runtime detail that is easy to lose and fatal when lost: `MPLCONFIGDIR`
must be set **before** `Python.start()` (`MainActivity`, via `Os.setenv`).
matplotlib writes its font cache on first import and dies on a read-only
default.

The compiled build exists because `strings` on an interpreted module prints
back function names, line numbers and whole docstrings; `packaging/android_wheel.py`
cythonises `core`, `arch`, `blocks` and `calibration` and cross-compiles them
against Chaquopy's Android CPython (headers from Maven Central, plain NDK
clang).  Run it with `--host` to exercise the whole path without an NDK.

Two things about it are easy to get wrong and are commented where they live:
the wheels must be resolved by tag (`--find-links`), never installed by path,
or the arm64 wheel lands in the x86_64 variant too; and `--no-index` must stay
off, because it is global and would cut numpy, scipy and matplotlib off from
Chaquopy's index in the same resolve.

`presets.py` is deliberately not compiled.  Its calibration values end up as
IEEE-754 doubles in the constant pool, where a four-line script finds each one
exactly — compiling it would buy the appearance of protection and nothing
else.

A bridge method with no caller is half a feature: `appbridge._METHODS`
gaining an entry that no page renders looks tested and does nothing.  Wire
the UI in the same change — `tests/test_android_parity.py` checks both
directions from text alone, so it runs in every CI job at no browser cost.

Where the surfaces differ on purpose — phone defaults, unit choices — record
it in `cairn/android-app.md` so the next reader can tell a decision from a
gap.

Plot zoom and the readout cursor are two of those places, and the surfaces do
them differently because they have to: Qt figures carry matplotlib's own
`NavigationToolbar2QT` plus a `PlotCursor` (both added in `widgets.FigList`, so
every page gets them), Android has no matplotlib in its WebView and instead
opens a tapped plot in a full-screen pinch/double-tap viewer whose cursor is
driven by data the bridge ships beside the image, and the web GUI keeps static
`st.pyplot()` PNGs on purpose. Do not "fix" the web GUI's difference without
reading the Parity note first.

The cursor has one rule worth stating separately: **neither surface
re-evaluates the model.** `plotting.figure_cursor_data()` reads the curves off
the rendered figure's `Line2D`s, and Qt reads the same artists directly, so a
readout cannot drift from the line the reader is pointing at. If you add a
plot, it inherits a cursor for free — and if its traces are too long to ship,
the bridge refuses them by name rather than thinning them, because a decimated
cursor would report numbers the drawn curve does not show.

## What CI enforces

| gate | command |
|---|---|
| lint | `ruff check src tests examples packaging docs` |
| types | `mypy` (file list in `pyproject.toml`) |
| tests | `pytest tests/ -m "not sweep and not sensitivity" -n 4` on 3.11 and 3.12; the cross-domain sweep and the field-sensitivity gate run in their own parallel job (`-m "sweep or sensitivity" -n 4`, 3.11) |
| floor | the same suite on **3.10** with the declared minimum `numpy`/`scipy`/`matplotlib` pinned — the interpreter and wheels the phone actually runs — plus both GUI extras, and a step that refuses if an extra moved a pin (`test-minimum` job; read its *selected* count against the 3.11 job, not just the colour) |
| no silent skips | both test jobs set `PLLSIM_CI=1`: `tests/_require.py` turns a missing optional dependency (streamlit, PySide6, iverilog) into a failure instead of a module-level skip, which reports as *one* item and hides every test in the file — the floor job first went green with 97 fewer tests that way |
| coverage | floor of 88% (`[tool.coverage.report]`), measured in the 3.11/3.12 job only |
| apk contents | `packaging/apk_check.py` (unit-tested with synthetic zips; the Android workflow runs it on the real wheels and both APKs) |

What CI does **not** enforce: the Android APK build (manual
`workflow_dispatch`), the Windows exes (`windows-exe` and
`windows-exe-nuitka` are two thin entries over one reusable
`windows-exe-build.yml`, also manual), the Android page itself (no headless browser in the
test job), and — even in the harness — the hardware back button, the feel of
the drawer gesture on glass, and display cutouts and gesture bars.  Those need
a sideload.  The rest is on you —
see "Three front ends" above.

The mypy gate is the whole package (`files = ["src/pllsim"]`) — every module
whose types carry a *convention* (rad²/Hz vs dBc/Hz, seconds vs UI, amps vs
coulombs), and everything else too, since `export/` and `webgui/` — the last
two paths outside — were fixed and gated together.  If something ever has to
leave the gate, it goes in `docs/gen_roadmap.py`'s `TYPE_CANDIDATES`, so its
cost is **measured** in [`docs/roadmap.md`](docs/roadmap.md) rather than
remembered here; silencing with `ignore_errors` is not an option, because a
blanket ignore reads as "type-checked".

## Conventions that will bite you

* **Phase PSDs are double-sideband** `S_φ(f)` in rad²/Hz.  Plots and spot
  numbers are `L(f) = S_φ/2` in dBc/Hz, and `ipn_dbc` sits 3.01 dB below the
  integral of `S_φ` for the same reason.  Mixing the two is a silent 3 dB and
  has happened more than once — and 3 dB on an integrated figure is a factor
  of √2 on every jitter derived from it, which is the difference between
  meeting a spec and missing it.  `core.jitter.convert_phase_noise` converts
  between degrees, RMS jitter and integrated dBc and deliberately returns
  **both** dBc conventions, so a number carried in from a datasheet can be
  matched against the right one rather than assumed into the wrong one.  All
  three GUIs expose it; `test_phase_units.py` ties its single-sideband figure
  to `AnalysisResult.ipn_dbc` on every preset.
* **Two conventions for noise injection.**  `CurrentNoise(duty=...)` scales a
  continuous current by its duty cycle; a per-cycle *sampled* charge injection
  is `2σ²/fref`.  They differ by exactly 2.  The charge-pump path carries the
  factor deliberately (`duty = 2*t_reset/tref`); if you add a source, say
  which convention it is in.
* **Every dual-domain architecture has a cross-domain test.**  The settled
  time-domain periodogram must match the linear model within 2–3 dB
  band-averaged.  The mechanism is `pllsim.validation.compare_domains` — do
  not hand-roll the comparison; it clips the band to where both estimates
  mean something (and records every clip), keeps thin bins visible, returns
  same-band jitter for both domains, and reports which capability-boundary
  flags are active.  `tests/test_cross_domain_sweep.py` runs the same
  contract across the parameter space in its own CI job: over base tolerance
  with no boundary flag active is a model defect; a confirmed limitation too
  large to fix inline goes into `validation.CROSS_DOMAIN_GAPS`, pinned at
  its measured value and re-measured on every push.  When the domains
  disagree, one of them is wrong — finding out which is where most of §9 of
  the design guide came from.
* **`analyze()` is not allowed to invent numbers.**  An impairment that is not
  configured is an absent key, not a `-600 dBc` entry; an architecture that
  genuinely has no such mechanism says so in `notes` rather than returning a
  blank.  A sub-sampling loop reports no reference spur *because it has none*,
  and that sentence is the deliverable.

* **The per-cycle code is a kernel, and it has two readers.**  Every
  engine loop and every block's per-cycle arithmetic is a plain function of
  scalars and arrays under `core.jit.kernel`; numba compiles it when the
  `[fast]` extra is installed and Python runs it otherwise, and
  `tests/test_kernels.py` requires the two to agree to the last bit on every
  preset.  The rules that keep them agreeing are in the `core/jit.py`
  docstring — `math.*` not `np.*` on scalars, no `**`, no numpy array
  operations in the loop, complex division written out, random draws from a
  pool through a cursor — and every one of them was found by breaking it.
  A block gets its state as an array and its parameters as scalars; the
  `*_kernel_args()` helpers in `arch/base.py` build those runs from the
  block objects, and the kernel call takes them as one tuple (mypy cannot
  count arguments after a star-argument of unknown length).  A new random
  draw is one more slot per cycle in the pool and one more cursor step, in
  the place the object used to draw; `cairn/compiled-kernels.md` has the
  measurements and the pitfalls.  Coverage is measured on the interpreted
  leg only, because a compiled function never executes its Python lines —
  with the kernels compiled the same passing suite reads 84 % instead of
  92 %.

## Testing

Two habits this codebase learned the hard way.

**Drive one source to dominance before comparing.**  A test that compares
*total* jitter with a 2–3 dB tolerance will pass with a single contributor 3 dB
wrong.  Raise the source under test to >90% of the budget, then compare.
Three real physics bugs survived for months behind total-comparison tests.

**Prove your test can fail.**  After writing a check, break the thing it
checks and confirm it goes red.  Vacuous tests here have included: a regex
matching zero instances (so every assertion passed on nothing), an assertion
whose `or` branch accepted anything, and a button test that pressed by index
and kept passing after a button was inserted ahead of it.  Where the check is
subtle, leave the mutation in the docstring so the next reader knows what it
is guarding.

**A tolerance says where it came from.**  Every bound in a test is one of
three things, and the line should make clear which: *algebra* (both sides are
the same expression, so `rel=1e-9` and tighter is round-off and needs no more
than a word), *a measurement* (state the value you saw, the seed and the run
length: `# measured 2026-09-10 (seed 5, 400k): ratio 0.999, -0.01 dB`), or
*a statistic* (state the spread the bound is a multiple of: `1/sqrt(2N) =
0.35 %, so 3 % is ~8 sigma`).  A bare `< 0.35` is unfalsifiable a year later
— nobody can tell a real budget from a number that was widened until the test
went green, which is exactly how a 4.3 dB spur error survived.  When you widen
a tolerance, say what you measured that made you widen it.

**Numbers in prose are code.**  `tests/test_docs_consistency.py` pins the
counts in `README.md`, `docs/index.html` and the management deck against the
package.  If you add a preset, an example or an architecture, that test tells
you which sentences to update.

Two files there are generated, and the same test fails when they go stale:

```bash
python docs/gen_config_reference.py     # after adding or renaming a config field
python docs/gen_roadmap.py              # after changing the mypy gate
python docs/reports/collect_facts.py    # then: cd docs/reports && node build_deck.js
```

A new config field also needs an entry in `guiutil.FIELD_INFO` — that is where
its unit and bilingual label come from, for the reference *and* for both GUI
forms.  Without one the form shows the raw field name, which tells a user
nothing about what to type; the test rejects it.

## How to add …

**A preset** — write the factory in `src/pllsim/presets.py`, register it in
`ALL_PRESETS`, and give it a docstring saying where the numbers come from.
Both GUIs and the selector pick it up from that dict; nothing else needs
touching.  A literature-anchored preset also goes in `BENCHMARKS` with its
published figure, and `benchmark_table()` recomputes the linear column live.

**An example** — `examples/exNN_<slug>.py`, `matplotlib.use("Agg")` before
pyplot, figures into `examples/out/`.  The header docstring should say what
question the example answers, not what functions it calls.  CI runs every
example on merges to `main` and a fast subset on every push; if yours runs in
a few seconds, add it to the subset.

**An architecture** — subclass `arch.base.PLLBase` and implement `analyze()`
and `simulate()`.  The shared helpers in `base.py` (`supply_ripple_v`,
`pull_hz`, `attach_fine`, `start_offset_kwarg`) exist so that a config field
on the common `OscConfig` is not a decoration on five of six engines — wire
them up rather than reimplementing.  Then: a preset, a cross-domain test, and
the docs counts.

**An impairment** — model it in `blocks/`, expose it as a config field, give
it both an `analyze()` path and a `simulate()` path, and add a test that drives
that source to dominance across the two.  An impairment with only one of the
two paths is how a parameter becomes decorative.

## Releasing

`docs/release-notes/vX.Y.Z.md` is not documentation *about* a release — it is
what *causes* one.  The `auto-release` job in `ci.yml` walks that directory on
every push to `main` and tags plus releases anything without a tag.

So a release is: bump `version` in `pyproject.toml`, write the notes file with
the matching name, merge.  Skipping the notes file means the version bump
ships silently and no tag is ever created — which happened to v0.9.1 and
v0.9.2, because iterating over an unchanged directory is a legitimate success.
CI now fails on `main` when `pyproject`'s version has no notes file.

Write the notes **in the same change as the version bump**.  They cannot be
backfilled: tagging an older commit is impossible from CI, because a ref whose
`.github/workflows/ci.yml` differs from the current one is refused to
`GITHUB_TOKEN` by `git push` ("without workflows permission" — a PAT scope no
`permissions:` block can grant) and by the refs API alike.  A version that
already shipped without notes therefore stays untagged: it carries a
`<!-- no-tag: -->` marker explaining why, the job skips it, and its content
goes out with the next release.  `v0.9.1` is the example in the tree.

Write the notes for someone diffing two versions: **every number that changed,
and why**.  If jitter figures move, say which presets and by how much.  A
release that quietly re-baselines a number is worse than one that breaks.

## Pull requests

Say what you found and how you know, not what you touched — the diff already
says that.  If a fix changes a published number, the PR body carries the
before/after table.
