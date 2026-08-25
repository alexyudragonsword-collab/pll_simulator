# The pinned toolchain, and why each pin is the one it is

Every version below is load-bearing in at least one direction.  The two that
bite hardest are Python 3.10 (a ceiling, not a floor) and the fact that AGP has
no upper bound despite what an earlier note in this repo claimed.

| what | version | where it is set | why this one |
|---|---|---|---|
| `buildPython` / `setup-python` | **3.10** | `.github/workflows/android.yml`, and the host Python locally | must match the Chaquopy `version` below.  Chaquopy's package repository has no scipy wheel past 3.10 ([chaquo/chaquopy#1237](https://github.com/chaquo/chaquopy/issues/1237)) |
| Chaquopy `version` | **"3.10"** | `android/app/build.gradle.kts`, `chaquopy { defaultConfig { … } }` | resolves to CPython target **3.10.13-0**; that string is `TARGET_VERSION` in `packaging/android_wheel.py` and the reason the wheels are tagged `cp310` |
| Chaquopy plugin | 15.0.1 | `android/build.gradle.kts` | newest line whose repo carries scipy for 3.10 |
| AGP `com.android.application` | 8.1.4 | `android/build.gradle.kts` | Chaquopy 15.0.1 enforces a **minimum** of AGP 7.0.0 and **no maximum** — `Common.java: MIN_AGP_VERSION = "7.0.0"`, a one-sided check.  An earlier note in this repo claimed a supported 8.1–8.2 *range*; the source does not say that |
| Kotlin | 1.9.24 | `android/build.gradle.kts` | pairs with AGP 8.1 |
| Gradle | 8.2 | CI's `gradle/actions/setup-gradle@v3`; locally whatever `gradle` is | pairs with that AGP.  There is no wrapper in the repo — `gradle -p android` uses the one on PATH |
| Java | 17 | `setup-java@v4`, and `compileOptions` / `jvmTarget` | what AGP 8.x requires |
| `compileSdk` / `targetSdk` | 34 | `android/app/build.gradle.kts` | Chaquopy's own floor is `COMPILE_SDK_VERSION = 34` |
| `minSdk` | 24 | same | Chaquopy's floor is `MIN_SDK_VERSION = 21`; 24 is ours.  Note `packaging/android_wheel.py` compiles against `API_LEVEL = 21`, the NDK sysroot level, which is a different number for a different purpose |
| `abiFilters` | arm64-v8a, x86_64 | same | phones and the emulator.  Each ABI carries its own CPython plus numpy/scipy — a third costs roughly 40 MB |
| `versionName` | tracks the pllsim version it bundles | same | bump together with `pyproject.toml` |

## Repositories

`android/settings.gradle.kts` adds `maven("https://chaquo.com/maven")` to both
`pluginManagement` and `dependencyResolutionManagement`.  That single URL
serves two different things: the Gradle **plugin**, and the Python **package
repository** its pip resolves numpy/scipy/matplotlib from.

The Android CPython headers and libraries that `packaging/android_wheel.py`
cross-compiles against are somewhere else entirely — **Maven Central**:

```
https://repo.maven.apache.org/maven2/com/chaquo/python/target/{v}/target-{v}-{abi}.zip
```

Worth knowing when a network policy blocks chaquo.com: the wheel build still
works, only the Gradle side is cut off.

## Is the 3.10 pin still true?

Open question, recorded in `cairn/android-app.md`.  Upstream Chaquopy 17.0.1
supports Python 3.10–3.14 and recommends `cibuildwheel` for 3.13+, which
suggests the scipy situation may have moved.  It was not verifiable from this
environment (chaquo.com's package index was unreachable), so the pin stands
until someone checks the index directly.  Bumping the plugin without checking
trades scipy away for a newer interpreter, and scipy is not optional here.

## Runtime, not build time

`MPLCONFIGDIR` must be set **before** `Python.start()` — `MainActivity.onCreate`
does it with `Os.setenv` into `filesDir/mpl`.  matplotlib writes its font cache
on first import and dies on a read-only default config dir.  This is not
enforced by anything; it is one line whose ordering is the whole story.
