"""The APK workflow's two inspections, tested against fabricated archives.

They used to live in shell heredocs inside android.yml, where nothing linted
or ran them short of a full SDK+NDK build.
"""
from __future__ import annotations

import importlib.util
import io
import zipfile
from pathlib import Path

import pytest

# `packaging` is also a PyPI distribution on sys.path, so the repo directory
# of that name is loaded by path rather than imported
_spec = importlib.util.spec_from_file_location(
    "apk_check", Path(__file__).resolve().parents[1] / "packaging" / "apk_check.py")
apk_check = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(apk_check)
check_apks, check_wheels, main = apk_check.check_apks, apk_check.check_wheels, apk_check.main
source_object_counts, wheel_machine = apk_check.source_object_counts, apk_check.wheel_machine


def _elf(machine: int) -> bytes:
    hdr = bytearray(64)
    hdr[:4] = b"\x7fELF"
    hdr[18:20] = machine.to_bytes(2, "little")
    return bytes(hdr)


def _wheel(path, machine, so_name="pllsim/core/engine.cpython-310.so"):
    with zipfile.ZipFile(path, "w") as z:
        z.writestr(so_name, _elf(machine))
        z.writestr("pllsim/__init__.py", "")
    return str(path)


def _apk(path, files: dict[str, bytes]):
    inner = io.BytesIO()
    with zipfile.ZipFile(inner, "w") as p:
        for n, b in files.items():
            p.writestr(n, b)
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("assets/chaquopy/requirements-common.imy", inner.getvalue())
        z.writestr("classes.dex", b"dex")
    return str(path)


def test_wheel_machine_reads_the_elf_header(tmp_path):
    assert wheel_machine(_wheel(tmp_path / "a-arm64.whl", 0xB7)) == 0xB7
    assert wheel_machine(_wheel(tmp_path / "b-x86_64.whl", 0x3E)) == 0x3E


def test_honest_wheels_pass_and_a_mislabelled_one_is_named(tmp_path):
    good = [_wheel(tmp_path / "pllsim-0.9-cp310-android_21_arm64_v8a.whl", 0xB7),
            _wheel(tmp_path / "pllsim-0.9-cp310-android_21_x86_64.whl", 0x3E)]
    assert check_wheels(good) == []
    bad = _wheel(tmp_path / "pllsim-0.9-cp310-android_21_arm64_v8a.whl", 0x3E)
    problems = check_wheels([bad])
    assert problems and "x86-64" in problems[0] and "AArch64" in problems[0]
    assert check_wheels([]) == ["no wheels to check"]


def test_a_wheel_without_an_object_is_refused(tmp_path):
    p = tmp_path / "pllsim-arm64.whl"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("pllsim/core/engine.py", "")
    with pytest.raises(ValueError, match="no .so"):
        wheel_machine(p)


def test_apks_are_told_apart_by_what_they_carry(tmp_path):
    interp = _apk(tmp_path / "i.apk", {"pllsim/core/engine.py": b"",
                                       "pllsim/arch/cppll.pyc": b"",
                                       "pllsim/guiutil.py": b""})
    comp = _apk(tmp_path / "c.apk", {"pllsim/core/engine.cpython-310.so": _elf(0xB7),
                                     "pllsim/guiutil.py": b""})
    assert source_object_counts(interp) == (2, 0)
    assert source_object_counts(comp) == (0, 1)      # guiutil is not a modelling pkg
    assert check_apks(interp, comp) == []
    # the failure the check exists for: the second build reused the first
    assert any("reused" in p for p in check_apks(interp, interp))
    assert any("not carrying source" in p for p in check_apks(comp, comp))


def test_cli_exit_codes(tmp_path, capsys):
    good = _wheel(tmp_path / "pllsim-arm64.whl", 0xB7)
    assert main(["wheels", good]) == 0
    bad = _wheel(tmp_path / "pllsim-x86_64.whl", 0xB7)
    assert main(["wheels", bad]) == 1
    assert "::error::" in capsys.readouterr().out
    assert main(["nonsense"]) == 2
