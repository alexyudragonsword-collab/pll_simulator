"""Bit-true iverilog verification of every generated RTL block.

Zero tolerance: expected vectors come from the bit-true Python models
(core.deltasigma) and fixed-point mirrors (export.fixedpoint).
"""
import shutil
import subprocess
from pathlib import Path

import pytest

from pllsim.export import golden
from pllsim.export.formatting import write_file
from pllsim.export.rtl import dlf, fsm, lms, mash, tb

IVERILOG = shutil.which("iverilog")
pytestmark = pytest.mark.skipif(IVERILOG is None,
                                reason="iverilog not installed")


def run_iverilog(workdir: Path, tb_file: str, dut_file: str) -> str:
    subprocess.run([IVERILOG, "-g2005", "-o", "sim", tb_file, dut_file],
                   cwd=workdir, check=True, capture_output=True)
    out = subprocess.run(["vvp", "sim"], cwd=workdir, check=True,
                         capture_output=True, text=True).stdout
    assert "PASS" in out and "FAIL" not in out, out
    return out


@pytest.mark.parametrize("kind,emit,frac0", [
    ("efm1", mash.emit_efm1, 4242424),
    ("mash11", mash.emit_mash11, (1 << 23) + 12345),
    ("mash111", mash.emit_mash111, (1 << 23) + 12345),
])
def test_mash_bittrue(tmp_path, kind, emit, frac0):
    name, txt = emit()
    write_file(tmp_path / f"{name}.v", txt)
    g = golden.mash_vectors(kind, 24, frac0, 4096, tmp_path / "vectors")
    fn, ttxt = tb.tb_mash(kind, 24, g["n"])
    write_file(tmp_path / fn, ttxt)
    run_iverilog(tmp_path, fn, f"{name}.v")


@pytest.mark.parametrize("n_iir,sh_iir", [(0, ()), (1, (1,)), (2, (1, 2))])
def test_dlf_bittrue(tmp_path, n_iir, sh_iir):
    name, txt = dlf.emit_dlf(n_iir)
    write_file(tmp_path / f"{name}.v", txt)
    g = golden.dlf_vectors(4, 11, sh_iir, 32, 4096, tmp_path / "vectors")
    fn, ttxt = tb.tb_dlf(32, 4, 11, sh_iir, g["n"])
    write_file(tmp_path / fn, ttxt)
    run_iverilog(tmp_path, fn, f"{name}.v")


def test_sslms_bittrue(tmp_path):
    name, txt = lms.emit_sslms()
    write_file(tmp_path / f"{name}.v", txt)
    g = golden.sslms_vectors(24, 24, 28, 18, 21, 10, 2000, 4096,
                             tmp_path / "vectors")
    fn, ttxt = tb.tb_sslms(24, 24, 28, 18, 21, 10, 2000, g["n"])
    write_file(tmp_path / fn, ttxt)
    run_iverilog(tmp_path, fn, f"{name}.v")


def test_ftl_bittrue(tmp_path):
    name, txt = fsm.emit_ftl()
    write_file(tmp_path / f"{name}.v", txt)
    g = golden.ftl_vectors(16, 1, 500, 1, 2048, tmp_path / "vectors")
    fn, ttxt = tb.tb_ftl(16, 1, 500, 1, g["n"])
    write_file(tmp_path / fn, ttxt)
    run_iverilog(tmp_path, fn, f"{name}.v")


@pytest.mark.parametrize("band_true", [3, 17, 21, 30])
def test_bandselect_bittrue(tmp_path, band_true):
    name, txt = fsm.emit_bandselect()
    write_file(tmp_path / f"{name}.v", txt)
    g = golden.bandselect_vectors(32, 15625, band_true, 488, 21, 6,
                                  tmp_path / "vectors")
    fn, ttxt = tb.tb_bandselect(32, 15625, 21, 6, g["n"])
    write_file(tmp_path / fn, ttxt)
    run_iverilog(tmp_path, fn, f"{name}.v")


def test_fll_bittrue(tmp_path):
    name, txt = fsm.emit_fll()
    write_file(tmp_path / f"{name}.v", txt)
    g = golden.fll_vectors(64, 250 * 64, 128, 32, 250, 4096,
                           tmp_path / "vectors")
    fn, ttxt = tb.tb_fll(64, 250 * 64, 128, 32, g["n"])
    write_file(tmp_path / fn, ttxt)
    run_iverilog(tmp_path, fn, f"{name}.v")
