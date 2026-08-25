# The Cython-compiled variant

`packaging/android_wheel.py` produces one wheel per ABI in which the four
modelling packages are native code instead of `.py`.  Everything else about the
APK — Chaquopy, the Gradle task, numpy/scipy/matplotlib, the assets — is
unchanged.

## What it does, in order

1. **Copy** `src/pllsim` into a work tree.  The real source tree is never
   mutated.
2. **Fetch** Chaquopy's Android CPython for the ABI, from Maven Central:
   `com/chaquo/python/target/3.10.13-0/target-3.10.13-0-{abi}.zip`.  Only the
   headers and `libpython3.10.so` are used.
3. **Cythonise** every `.py` under `core/`, `arch/`, `blocks/`, `calibration/`
   with `cython -3 --no-docstrings --module-name <dotted.name>`.  The dotted
   module name matters: without it the generated init function is named for the
   bare filename and the import fails at runtime.
4. **Compile** each `.c` with the NDK's clang wrapper for the triplet
   (`aarch64-linux-android21-clang`, etc.), `-shared -fPIC -O2
   -fvisibility=hidden`, linking `libpython3.10`.
5. **Delete** the corresponding `.py` and assemble a wheel tagged
   `cp310-cp310-android_21_<abi>`, reusing the real `dist-info` from a normal
   `pip wheel` of the project so METADATA never drifts from `pyproject.toml`.

`--host` runs steps 3–5 against the machine's own Python and compiler, no NDK
required.  That is the way to test changes to this script; the ABI path differs
only in which compiler and headers it points at.

## Measured facts

Do not restate these from memory — they were measured, and the numbers are the
reason the boundary is where it is.

- **31 of 85 modules** compiled.  The full suite passed with every compiled
  `.py` deleted: 564 passed / 13 skipped via `PYTHONPATH`, 563 / 14 from the
  installed wheel (the extra skip is a missing `python-pptx`, unrelated).
- `analyze()` on the default workbench preset returns **258.3043 fs** in both
  builds — bit-identical, not merely close.
- Size: **4.7 MB per ABI**, APK 84.21 MB → **87.33 MB**.
- `strings` on an interpreted module prints function names, line numbers and
  whole docstrings.  On a compiled one it does not — but only because
  `--no-docstrings` is passed.  Verified both ways.

## What it does not protect

Say this plainly whenever the question comes up, because the compiled build
invites the opposite assumption:

- `android/app/src/main/assets/www/app.js` is **plain text** in the APK.
- `presets.py` is not compiled, and compiling it would not help: the
  calibration values become IEEE-754 doubles in the constant pool, findable
  exactly by an eight-byte `struct.pack` search (−122, 4.8e9 and 1.92e7 each
  matched exactly once in a test build).  They are also one `fields()` call
  away at runtime.
- The remaining 54 modules — including `appbridge`, `plotting`, `guiutil` —
  still ship as bytecode.

The honest summary: it raises the cost of reading the modelling code from
"unzip and read" to "disassemble", and changes nothing else.

## Changing the compiled set

`COMPILE_PACKAGES` is a measured boundary, not a preference.  If you add a
package to it, the claim you are implicitly making is that the suite still
passes with that package's `.py` deleted — so make it true the same way:
build, delete the sources, run the full suite, and put the counts in the
commit message.  A module that quietly falls back to its neighbouring `.py`
looks identical to one that compiled correctly.

Bumping `TARGET_VERSION` means bumping `PY_TAG`, the Chaquopy plugin version
and `buildPython` together — see `toolchain.md`, and check the scipy question
before touching any of them.
