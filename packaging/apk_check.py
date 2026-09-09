"""Look inside the Android build outputs instead of trusting the build log.

Two checks the APK workflow runs, moved here from two shell heredocs so they
are linted, type-checked and unit-tested like everything else -- a syntax
error in a heredoc was discoverable only by running the full SDK+NDK build.

* ``wheels``: each cross-compiled wheel must contain an ELF object of the
  architecture its filename tag claims (an arm64 tag on an x86-64 object is
  a wheel Chaquopy's pip will install and the phone will refuse to load).
* ``apks``: the interpreted and compiled APKs are built back to back in one
  workspace, so the real risk is that the second reuses the first's pip
  output and the "compiled" APK is the interpreted one renamed.  One must
  carry source for the modelling packages, the other objects, neither both.

    python packaging/apk_check.py wheels android/app/pysrc/pllsim-*.whl
    python packaging/apk_check.py apks out/pllsim-interpreted-debug.apk \\
                                       out/pllsim-compiled-debug.apk
"""
from __future__ import annotations

import io
import sys
import zipfile
from pathlib import Path

PKGS = ("core", "arch", "blocks", "calibration")
ELF_MACHINE = {0xB7: "AArch64", 0x3E: "x86-64", 0x28: "ARM"}
TAG_MACHINE = {"arm64": 0xB7, "x86_64": 0x3E}


def wheel_machine(whl: str | Path) -> int:
    """ELF e_machine of the first shared object in the wheel."""
    with zipfile.ZipFile(whl) as z:
        so = next((n for n in z.namelist() if n.endswith(".so")), None)
        if so is None:
            raise ValueError(f"{whl}: no .so inside -- not a compiled wheel")
        data = z.read(so)
    if data[:4] != b"\x7fELF":
        raise ValueError(f"{whl}: {so} is not an ELF object")
    return int.from_bytes(data[18:20], "little")


def expected_machine(whl: str | Path) -> int:
    name = Path(whl).name
    for tag, machine in TAG_MACHINE.items():
        if tag in name:
            return machine
    raise ValueError(f"{name}: filename names no ABI this check knows "
                     f"({', '.join(TAG_MACHINE)})")


def check_wheels(paths: list[str]) -> list[str]:
    """Problems found, one line each; empty means every wheel is honest."""
    problems = []
    for whl in sorted(paths):
        machine = wheel_machine(whl)
        want = expected_machine(whl)
        print(f"{Path(whl).name}: {ELF_MACHINE.get(machine, hex(machine))}")
        if machine != want:
            problems.append(f"{whl} is {ELF_MACHINE.get(machine, hex(machine))}, "
                            f"not the {ELF_MACHINE[want]} its tag claims")
    if not paths:
        problems.append("no wheels to check")
    return problems


def payload_names(apk: str | Path) -> list[str]:
    """Every file inside every Chaquopy payload (.imy) of the APK."""
    names: list[str] = []
    with zipfile.ZipFile(apk) as z:
        for entry in z.namelist():
            if not entry.endswith(".imy"):
                continue
            with zipfile.ZipFile(io.BytesIO(z.read(entry))) as p:
                names += p.namelist()
    return names


def source_object_counts(apk: str | Path) -> tuple[int, int]:
    """(source files, native objects) under the modelling packages."""
    src = obj = 0
    for n in payload_names(apk):
        if not any(f"pllsim/{p}/" in n for p in PKGS):
            continue
        if n.endswith((".py", ".pyc")):
            src += 1
        elif n.endswith(".so"):
            obj += 1
    return src, obj


def check_apks(interpreted: str | Path, compiled: str | Path) -> list[str]:
    """Problems found; empty means the two APKs are what their names say."""
    problems = []
    i_src, i_obj = source_object_counts(interpreted)
    c_src, c_obj = source_object_counts(compiled)
    print(f"interpreted: {i_src} source, {i_obj} native")
    print(f"compiled   : {c_src} source, {c_obj} native")
    if i_obj or not i_src:
        problems.append("the interpreted APK is not carrying source")
    if c_src or not c_obj:
        problems.append("the compiled APK still carries source for the "
                        "modelling packages -- the second build reused the first")
    return problems


def main(argv: list[str]) -> int:
    if len(argv) >= 2 and argv[0] == "wheels":
        problems = check_wheels(argv[1:])
    elif len(argv) == 3 and argv[0] == "apks":
        problems = check_apks(argv[1], argv[2])
    else:
        print(__doc__)
        return 2
    for p in problems:
        print(f"::error::{p}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
