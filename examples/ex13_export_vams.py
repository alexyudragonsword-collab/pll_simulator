"""Example 13: export every preset to Verilog-AMS / RNM / RTL.

Generates <repo>/examples/out/export/<preset>/{rtl,rnm,ams}/ + README per
instance and an INDEX.md summary.  The rtl/ testbenches are additionally
executed here with iverilog (bit-true, zero tolerance) when available.
"""
import shutil
import subprocess
from pathlib import Path

from pllsim import presets
from pllsim.export import export

OUT = Path(__file__).parent / "out" / "export"


def run_rtl_tbs(rep) -> str:
    """Run every exported rtl testbench with iverilog; returns summary."""
    if shutil.which("iverilog") is None:
        return "iverilog not installed — skipped"
    rtl = rep.outdir / "rtl"
    if not rtl.exists():
        return "no rtl blocks for this config"
    results = []
    for tbf in sorted((rtl / "tb").glob("tb_*.v")):
        dut = rtl / tbf.name.replace("tb_", "pllsim_")
        subprocess.run(["iverilog", "-g2005", "-o", "sim", str(tbf), str(dut)],
                       cwd=rtl, check=True, capture_output=True)
        out = subprocess.run(["vvp", "sim"], cwd=rtl, capture_output=True,
                             text=True).stdout
        tag = "PASS" if ("PASS" in out and "FAIL" not in out) else "FAIL"
        results.append(f"{tbf.stem.replace('tb_', '')}:{tag}")
    (rtl / "sim").unlink(missing_ok=True)
    return " ".join(results) if results else "no tbs"


if __name__ == "__main__":
    shutil.rmtree(OUT, ignore_errors=True)
    rows = []
    for nm, mk in presets.ALL_PRESETS.items():
        rep = export(mk(), OUT, name=nm)
        rtl_res = run_rtl_tbs(rep)
        n_files = sum(len(v) for v in rep.files.values())
        rows.append((nm, rep.kind, n_files, rtl_res, rep.warnings))
        print(f"{nm:28s} [{rep.kind:11s}] {n_files:3d} files | rtl: {rtl_res}")
        for w in rep.warnings:
            print(f"    warning: {w}")

    index = ["# pllsim Verilog-AMS export index", "",
             "| instance | kind | files | rtl bit-true (iverilog) |",
             "|---|---|---|---|"]
    for nm, kind, n, rtl_res, _ in rows:
        index.append(f"| [{nm}]({nm}/README.md) | {kind} | {n} | {rtl_res} |")
    index += ["", "Each instance directory: `rtl/` (synthesizable digital + "
              "vectors), `rnm/` (wreal top + golden CSV tb), `ams/` "
              "(electrical blocks + scalar tb), `README.md` (xrun lines, "
              "tolerances, noise policy)."]
    (OUT / "INDEX.md").write_text("\n".join(index) + "\n")
    print(f"\nindex written to {OUT}/INDEX.md")
