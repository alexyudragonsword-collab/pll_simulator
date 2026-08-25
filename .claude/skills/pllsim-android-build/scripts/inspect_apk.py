#!/usr/bin/env python3
"""Say which pllsim build an APK actually is, by looking inside it.

The interpreted and compiled APKs are produced by the same Gradle task from
the same workspace, differing only in what ``android/app/pysrc/`` held at the
time.  Nothing in the build log records which one you got, and the two are the
same application id, so a mislabelled artifact is invisible until someone
reverse-engineers it and finds source.

So look: Chaquopy packs the Python tree into ``.imy`` archives inside the APK.
This walks them and counts, for the four packages ``packaging/android_wheel.py``
compiles, how many entries are source (``.py``/``.pyc``) and how many are
native (``.so``).  A build carries one kind or the other; carrying both means
the wheels and an sdist were both present and pip picked the wrong one.

    python inspect_apk.py app-debug.apk [more.apk ...]

Exit status is 0 when every APK is unambiguously one build or the other,
1 otherwise -- so it works as a CI gate as well as a question.
"""

from __future__ import annotations

import io
import sys
import zipfile
from pathlib import Path

#: mirrors COMPILE_PACKAGES in packaging/android_wheel.py
PKGS = ("core", "arch", "blocks", "calibration")


def payload_names(apk: Path) -> list[str]:
    """Every path inside every Chaquopy .imy payload in the APK."""
    names: list[str] = []
    with zipfile.ZipFile(apk) as z:
        for entry in z.namelist():
            if not entry.endswith(".imy"):
                continue
            with zipfile.ZipFile(io.BytesIO(z.read(entry))) as payload:
                names += payload.namelist()
    return names


def counts(apk: Path) -> tuple[int, int]:
    """(source files, native modules) under the compiled packages."""
    src = obj = 0
    for name in payload_names(apk):
        if not any(f"pllsim/{p}/" in name for p in PKGS):
            continue
        if name.endswith((".py", ".pyc")):
            src += 1
        elif name.endswith(".so"):
            obj += 1
    return src, obj


def classify(src: int, obj: int) -> tuple[str, bool]:
    if src and not obj:
        return "interpreted", True
    if obj and not src:
        return "compiled", True
    if src and obj:
        return ("BOTH source and objects -- an sdist and wheels were both in "
                "pysrc/; this APK is not the build it claims"), False
    return ("no pllsim modelling packages found at all -- is this a pllsim "
            "APK?"), False


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    ok = True
    for arg in argv:
        apk = Path(arg)
        if not apk.is_file():
            print(f"{apk}: not a file")
            ok = False
            continue
        src, obj = counts(apk)
        verdict, good = classify(src, obj)
        print(f"{apk.name}: {src} source, {obj} native -> {verdict}")
        ok &= good
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
