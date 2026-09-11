---
name: pllsim-android-build
description: >
  Build, verify or repair the pllsim Android APK — the CPython/Chaquopy
  (interpreted) build and its Cython-compiled twin.  Use this skill whenever
  the work touches android/, the Android APK, Chaquopy, buildPython, the
  pysrc sdist or wheels, packaging/android_wheel.py, or the "Android APK"
  workflow; whenever someone asks how the app is built, why a Gradle or pip
  step failed, which APK a file is, or whether the APK protects the Python
  source; and whenever a change to guiutil, presets, plotting, appbridge or
  an arch/ signature needs the phone re-verified.  Reach for it even when the
  request just says "build the app", "make an APK", "the Android build is
  broken", or "sideload it" without naming Chaquopy at all.
---

# Building the pllsim Android APK

The app is a WebView shell (`MainActivity.kt`) over `pllsim.appbridge`, with
a real CPython — plus numpy, scipy and matplotlib — packed inside the APK by
[Chaquopy](https://chaquo.com/chaquopy/).  There is no server; nothing is
fetched at runtime; the manifest asks for **zero permissions**, and adding one
should stop a review.

Two APKs come out of every full run, from the same source:

| | what pllsim ships as | how it is installed |
|---|---|---|
| **interpreted** | `.py` | from an **sdist** in `android/app/pysrc/` |
| **compiled** | `.so` for `core`, `arch`, `blocks`, `calibration` | from one **wheel per ABI** in the same directory |

`assembleDebug` is the same task both times.  It builds whichever pllsim
`pysrc/` happens to hold — **that directory is the entire switch**.  Nothing
in the build log says which one you got, which is why the last section of this
file is about proving it after the fact rather than trusting the run.

## The interpreted build, start to finish

From a clean checkout, with Java 17, Python 3.10 and Gradle 8.2 on PATH and an
Android SDK the Gradle plugin can find:

```bash
pip install build
python -m build --sdist --outdir android/app/pysrc .   # from the repo root
gradle -p android :app:assembleDebug
# -> android/app/build/outputs/apk/debug/app-debug.apk
```

That is the whole thing.  Three details behind it are worth knowing, because
each one is a build failure if you guess differently.

**The sdist is not optional, and it is not a directory install.**
`chaquopy { pip { … } }` in `android/app/build.gradle.kts` reads `pysrc/` and
refuses to guess: with nothing there the build fails with that exact `python -m
build` command in the message.  It is an sdist rather than `install("../..")`
because a directory install makes the whole repository an input of Chaquopy's
pip task — and this Gradle project lives *inside* that repository, so every AGP
task's output lands inside the pip task's input and Gradle 8's validation
rejects the build.  That was the first CI run's failure, not a hypothetical.

**numpy, scipy and matplotlib come from Chaquopy's own wheel repository**
(`maven("https://chaquo.com/maven")` in `settings.gradle.kts`), unpinned, in
the same pip resolve as pllsim.  This is the reason `--no-index` must never be
added to scope the pllsim install: pip's `--no-index` is global and would take
those three down with it.

**`buildPython` must match the Chaquopy `version`.**  Both are 3.10 and the
match is checked nowhere — a mismatch surfaces later as wheels Chaquopy's pip
declines.  See `references/toolchain.md` for the full pinned set and why each
version is the one it is.

## The compiled build

Same Gradle command; only the contents of `pysrc/` change:

```bash
rm -f android/app/pysrc/pllsim-*.tar.gz          # or you build the other APK
pip install cython
for abi in arm64-v8a x86_64; do
  python packaging/android_wheel.py --abi "$abi" --ndk "$ANDROID_NDK_HOME"
done
gradle -p android :app:assembleDebug
```

`packaging/android_wheel.py` cythonises the four modelling packages and
cross-compiles them against Chaquopy's Android CPython — headers pulled from
**Maven Central**, compiled with plain NDK clang.  Only `Python.h` is needed;
the 3.10 headers keep to the public API (`pycore_frame.h` is behind
`PY_VERSION_HEX >= 0x030b00a6`), which is a large part of why this works at
all.  `--host` builds a wheel for the machine you are on and exercises the
entire path with no NDK, which is how to test changes to that script.

What it buys and what it does not: `strings` on an interpreted module prints
back function names, line numbers and whole docstrings, and the compiled one
gives machine code instead.  But `app.js` stays plain text in the assets, and
`presets.py` is **deliberately not compiled** — its calibration values would
sit in the constant pool as IEEE-754 doubles that an eight-byte
`struct.pack` search finds exactly, so compiling it buys the appearance of
protection and nothing else.  Read `references/compiled.md` before changing
`COMPILE_PACKAGES` or the target version.

## In CI

Actions → **Android APK** → Run workflow.  Manual on purpose: the APK is a
sideload artifact rather than a release gate, and the Chaquopy build is long
enough to hold a runner for a while.  (This used to say the minutes came off a
private repo's budget — the repository is public and Actions minutes are free;
the cost that remains is wall clock and queue contention.)  One run does both
builds back to back in one workspace and uploads
`pllsim-debug-apk-interpreted` and `pllsim-debug-apk-compiled`.

They share an application id, so installing one replaces the other on a phone.
Side-by-side would be an `applicationIdSuffix` away — ask first.  The
navigation flavors were removed for exactly the reason that unchosen variants
rot.

## Verify, do not infer

The two builds run in one workspace, so the real failure mode is silent: the
second build reuses the first's pip output and the "compiled" APK is the
interpreted one renamed.  Nothing in the log would say so.  Look inside:

```bash
python .claude/skills/pllsim-android-build/scripts/inspect_apk.py path/to.apk
```

It unpacks Chaquopy's `.imy` payloads and reports how many source files and
how many `.so` files the four modelling packages carry, then says
`interpreted`, `compiled`, or complains.  One must carry source, the other must
carry objects, and neither may carry both.  The CI job runs the same check on
both APKs, plus an ELF `e_machine` check that each wheel really is the
architecture its tag claims.

Two further things CI cannot prove, and a claim that the build is verified
should say so: **nothing has loaded a compiled module on a real phone** unless
someone sideloaded it and ran an analysis (expect **258.3 fs** for the default
workbench preset — the compiled and interpreted results were bit-identical on
the host), and gesture feel, display cutouts and the drawer's safe-area
insets are device-only.

Before touching anything shared with the other two front ends, re-read the
three-surfaces table in `AGENTS.md`: `webgui/`, `guiqt/` and `android/` render
the same library, and a change is not done until all three have been *run*.
For the phone specifically, `pytest tests/test_appbridge.py
tests/test_android_parity.py -q` is pure Python and cheap; `python
tests/android_page_harness.py` drives real Chromium against the real bridge
and is the only thing that has ever caught the page-level bugs.

## When it breaks

`references/traps.md` lists the failure modes this build has actually
produced, each with the symptom you will see first — an sdist and wheels both
present, the arm64 wheel landing in the x86_64 variant, matplotlib dying on a
read-only config dir, a YAML plain scalar eating a line continuation, a
`cythonize` flag that is not real and fails silently.  Read the symptom
column; the causes are rarely where the error points.
