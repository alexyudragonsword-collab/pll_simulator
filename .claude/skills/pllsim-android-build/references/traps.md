# Failure modes this build has actually produced

Ordered by how much time each one cost.  The symptom column is what you see
first; in most of these the error does not point at the cause.

## The second APK is quietly the first one

**Symptom:** the run is green, both artifacts upload, and the "compiled" APK
behaves and reverse-engineers exactly like the interpreted one.

**Cause:** an sdist left in `android/app/pysrc/` alongside the wheels.
Chaquopy's pip then still has a pure-Python `pllsim` to resolve and may take
it.  `rm -f android/app/pysrc/pllsim-*.tar.gz` before the compiled build; CI
does this explicitly.

**How you find out:** never from the log.  Run
`scripts/inspect_apk.py` on both files, or read the *Prove the two APKs
actually differ* step in `.github/workflows/android.yml` — it counts source
versus objects under `pllsim/{core,arch,blocks,calibration}/` and fails if
either APK carries the wrong kind.

## The arm64 wheel installed into the x86_64 variant

**Symptom:** the app crashes at import on one ABI with a message about the ELF
header, or works on a phone and not the emulator.

**Cause:** installing a wheel **by path**.  pip then does no tag matching.  The
Gradle config uses `options("--find-links", pysrc.absolutePath)` and
`install("pllsim")` precisely so pip picks per ABI from the tags.  Never
`install(wheels[0].absolutePath)`.

**Related trap, opposite direction:** do **not** add `--no-index` to scope that
resolve.  It is a global pip option and numpy, scipy and matplotlib come from
Chaquopy's index in the same resolve — it would cut all three off.  This was
caught before shipping, which is why it is written down.

## Gradle rejects the build over an undeclared dependency

**Symptom:** AGP task validation failure naming the pip task's inputs.

**Cause:** `install("../..")` — a directory install makes the whole repository
an input of the pip task, and the Gradle project lives inside that repository,
so every AGP task's output lands inside the pip task's input.  Hence the
sdist.  This was the first CI run's failure.

## `--no-docstrings` is real; `-X docstrings=False` is not

**Symptom:** the build appears to succeed, the `.so` files exist, and `strings`
still prints docstrings.  Worse: a compile that failed silently and Python
imported the neighbouring `.py` instead, so a "verification" proved nothing.

**Cause:** `-X docstrings=False` is not a Cython option; `cythonize -o` is not
one either.  When gcc's stderr is redirected, the failure is invisible and the
import falls back to source.  `packaging/android_wheel.py` uses
`--no-docstrings` and a dotted `--module-name`.

**Lesson that generalises:** after a compile step, delete or move the `.py` and
import again.  If it still imports, you compiled nothing.

## matplotlib dies on first import on the device

**Symptom:** the app boots, the page loads, and the first plot request returns
an error about a cache directory.

**Cause:** `MPLCONFIGDIR` set after `Python.start()`, or not at all.  It must be
set before, in `MainActivity.onCreate`.

## bash escapes a space instead of continuing a line

**Symptom:** a workflow step fails with `mv: cannot stat 'android/app/...apk out/...'`.

**Cause:** a **plain** YAML scalar folds onto one line and keeps the
backslash, so bash sees `\ ` — an escaped space — rather than a line
continuation.  Any multi-line `run:` needs a block scalar (`run: |`).

## A piped pytest reports the wrong exit code

**Symptom:** "exit code 0" with no summary line in the output.

**Cause:** `cmd | tail; echo $?` reports *tail's* status.  Use `set -o
pipefail`, or do not pipe when the exit code is the thing you are reporting.
This one has produced a false "tests passed" claim in this repo's own history.

## Qt smoke tests that skip instead of fail

Not an APK trap, but the same shape and it is how the two desktop GUIs drifted
for several releases: `tests/test_guiqt_smoke.py` **skips** without PySide6 and
the system GL libraries (`libegl1 libgl1 libxkbcommon0 libdbus-1-3`) rather
than failing.  Read the count, not the colour.

## The runner has no NDK

**Symptom:** would have been a second interpreted APK named "compiled".

**Handling:** the *Locate the NDK* step checks `ANDROID_NDK_HOME` then
`ANDROID_NDK_LATEST_HOME` and fails loudly if neither is a directory.  Keep it
that way — the whole point is that the failure is legible.
