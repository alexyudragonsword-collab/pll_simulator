"""pllsim.export — Verilog-AMS / RNM / RTL export bridge (Cadence).

    from pllsim import presets
    from pllsim.export import export
    rep = export(presets.cppll_frac_38p4m_6g(), "vams_out")
    print(rep.summary())

Per instance directory: rtl/ (bit-true synthesizable digital + iverilog
testbenches + vectors), rnm/ (wreal cycle-true top + golden CSV testbench),
ams/ (electrical blocks + top + scalar testbench), README.md.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from ..arch.adpll import ADPLL
from ..arch.cppll import CPPLL
from ..arch.ilcm import ILCM
from ..arch.mdll import MDLL
from ..arch.spll import SPLL
from ..arch.sspll import SSPLL
from . import golden as gv
from . import rnm_golden as rg
from .ams import AMS_FULL_ELECTRICAL, emit_ams_library, emit_ams_tb, emit_ams_top
from .fixedpoint import FixedCoeff
from .formatting import write_file
from .manifest import emit_readme, flicker_delta_fs
from .rnm import emit_rnm_library, emit_rnm_tb, emit_rnm_top
from .rtl import (emit_bandselect, emit_dlf, emit_efm1, emit_fll, emit_ftl,
                  emit_mash11, emit_mash111, emit_sslms)
from .rtl import tb as rtl_tb


@dataclass
class ExportReport:
    name: str
    kind: str
    outdir: Path
    files: dict[str, list[str]] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    golden: dict[str, float] = field(default_factory=dict)

    def all_files(self) -> list[Path]:
        out = []
        for flavor, names in self.files.items():
            base = self.outdir if flavor == "." else self.outdir / flavor
            out += [base / n for n in names]
        return out

    def summary(self) -> str:
        nf = sum(len(v) for v in self.files.values())
        w = f", {len(self.warnings)} warnings" if self.warnings else ""
        return f"{self.name} [{self.kind}]: {nf} files -> {self.outdir}{w}"


def _kind_of(pll) -> str:
    if isinstance(pll, CPPLL):
        return "cppll_frac" if pll.cfg.frac is not None else "cppll_int"
    if isinstance(pll, SSPLL):
        return "sspll_frac" if pll.cfg.frac is not None else "sspll_int"
    if isinstance(pll, SPLL):
        return "spll"
    if isinstance(pll, ADPLL):
        return "adpll_tdc" if pll.cfg.mode == "tdc" else "adpll_bbpd"
    if isinstance(pll, ILCM):
        return "ilcm"
    if isinstance(pll, MDLL):
        return "mdll"
    raise TypeError(f"no exporter for {type(pll).__name__}")


# ------------------------------------------------------------------ RTL leg
def _export_rtl(pll, kind: str, outdir: Path, rep: ExportReport,
                n_vec: int) -> None:
    c = pll.cfg
    rtl_dir = outdir / "rtl"
    vec = rtl_dir / "vectors"
    files: list[str] = []

    def add_block(emit, tbgen, gen_vectors):
        name, txt = emit()
        write_file(rtl_dir / f"{name}.v", txt)
        files.append(f"{name}.v")
        g = gen_vectors()
        fn, ttxt = tbgen(g)
        write_file(rtl_dir / "tb" / fn, ttxt)
        files.append(f"tb/{fn}")

    frac = getattr(c, "frac", None)
    if frac is not None:
        bits, word = frac.bits, frac.frac_word
        order = frac.mash_order
        emit = {1: emit_efm1, 2: emit_mash11, 3: emit_mash111}[order]
        mash_kind = {1: "efm1", 2: "mash11", 3: "mash111"}[order]
        add_block(emit,
                  lambda g: rtl_tb.tb_mash(mash_kind, bits, g["n"]),
                  lambda: gv.mash_vectors(mash_kind, bits, word, n_vec, vec))
        if getattr(frac, "dtc_cal", None) is not None:
            add_block(emit_sslms,
                      lambda g: rtl_tb.tb_sslms(24, 24, 28, 18, 21, 10,
                                                2000, g["n"]),
                      lambda: gv.sslms_vectors(24, 24, 28, 18, 21, 10, 2000,
                                               n_vec, vec))
    if kind == "adpll_tdc":
        sha = FixedCoeff(c.dlf.alpha)
        shr = FixedCoeff(c.dlf.rho)
        lams = tuple(FixedCoeff(l) for l in c.dlf.iir_lambdas)
        if sha.is_pow2 and shr.is_pow2 and all(l.is_pow2 for l in lams):
            sh_iir = tuple(l.shift for l in lams)
            add_block(lambda: emit_dlf(len(sh_iir)),
                      lambda g: rtl_tb.tb_dlf(32, sha.shift, shr.shift,
                                              sh_iir, g["n"]),
                      lambda: gv.dlf_vectors(sha.shift, shr.shift, sh_iir,
                                             32, n_vec, vec))
        else:
            rep.warnings.append(
                "DLF coefficients are not powers of two: RTL DLF not "
                "emitted (RNM top carries the real-coefficient filter)")
    if kind in ("sspll_int", "sspll_frac", "spll"):
        window = c.fll_window
        n_t = int(round(c.fout / c.fref)) * window
        th_eng = max(int(round(c.fll_engage / c.fref * window)), 1)
        th_rel = max(int(round(c.fll_release / c.fref * window)), 1)
        add_block(emit_fll,
                  lambda g: rtl_tb.tb_fll(window, n_t, th_eng, th_rel, g["n"]),
                  lambda: gv.fll_vectors(window, n_t, th_eng, th_rel,
                                         int(round(c.fout / c.fref)),
                                         n_vec, vec))
    if kind in ("ilcm", "mdll"):
        add_block(emit_ftl,
                  lambda g: rtl_tb.tb_ftl(16, 1, 0, 1, g["n"]),
                  lambda: gv.ftl_vectors(16, 1, 0, 1, n_vec, vec))
    osc = c.osc
    if getattr(osc, "n_bands", 1) > 1:
        window = 64
        target = int(round(c.fout / c.fref)) * window
        step_counts = max(int(round(osc.band_step_hz / c.fref * window)), 1)
        band_true = min(max(int(round((c.fout - osc.f0) / osc.band_step_hz
                                      + (osc.n_bands - 1) / 2.0)), 0),
                        osc.n_bands - 1)
        add_block(emit_bandselect,
                  lambda g: rtl_tb.tb_bandselect(osc.n_bands, target, 21, 6,
                                                 g["n"]),
                  lambda: gv.bandselect_vectors(osc.n_bands, target,
                                                band_true, step_counts,
                                                21, 6, vec))
    if vec.exists():
        files += [f"vectors/{p.name}" for p in sorted(vec.glob("*.hex"))]
    if files:
        rep.files["rtl"] = files


# ------------------------------------------------------------------ RNM leg
def _export_rnm(pll, kind: str, name: str, outdir: Path, rep: ExportReport,
                n_golden: int) -> None:
    rnm_dir = outdir / "rnm"
    files = []
    for stem, txt in emit_rnm_library():
        write_file(rnm_dir / f"{stem}.vams", txt)
        files.append(f"{stem}.vams")
    top_txt, cols = emit_rnm_top(kind, pll.cfg, name)
    write_file(rnm_dir / f"{name}_top_rnm.vams", top_txt)
    files.append(f"{name}_top_rnm.vams")

    engine = {"cppll_int": rg.golden_cppll, "cppll_frac": rg.golden_cppll,
              "sspll_int": rg.golden_sspll, "sspll_frac": rg.golden_sspll,
              "spll": rg.golden_spll, "adpll_tdc": rg.golden_adpll_tdc,
              "adpll_bbpd": rg.golden_adpll_bbpd, "ilcm": rg.golden_ilcm,
              "mdll": rg.golden_mdll}[kind]
    if kind in ("ilcm", "mdll"):
        cols_data = engine(pll.cfg, n_golden, f_free_error=0.0)
    else:
        cols_data = engine(pll.cfg, n_golden)
    cols_data = {k: cols_data[k] for k in cols}       # tb column order
    rg.write_golden_csv(rnm_dir / "golden_rnm.csv", cols_data)
    files.append("golden_rnm.csv")
    tb_txt = emit_rnm_tb(name, cols, pll.cfg.fref, n_golden)
    write_file(rnm_dir / f"tb_{name}_rnm.vams", tb_txt)
    files.append(f"tb_{name}_rnm.vams")
    rep.files["rnm"] = files
    if "fv" in cols_data:
        rep.golden["fv_final_hz"] = float(cols_data["fv"][-1])


# ------------------------------------------------------------------ AMS leg
def _export_ams(pll, kind: str, name: str, outdir: Path,
                rep: ExportReport) -> None:
    ams_dir = outdir / "ams"
    files = []
    for stem, txt in emit_ams_library():
        write_file(ams_dir / f"{stem}.vams", txt)
        files.append(f"{stem}.vams")
    write_file(ams_dir / f"{name}_top_ams.vams",
               emit_ams_top(kind, pll.cfg, name))
    files.append(f"{name}_top_ams.vams")

    c = pll.cfg
    vctrl_gold = c.osc.v_for(c.fout) if hasattr(c.osc, "v_for") else 0.0
    if kind in AMS_FULL_ELECTRICAL:
        try:
            t_settle = 30.0 / max(pll.analyze().loop.f_ugb, 1e4)
        except Exception:
            t_settle = 3000.0 / c.fref
    else:
        t_settle = 5000.0 / c.fref
    write_file(ams_dir / f"tb_{name}_ams.vams",
               emit_ams_tb(name, kind, c.fref, c.fout, vctrl_gold, t_settle))
    files.append(f"tb_{name}_ams.vams")
    rep.files["ams"] = files
    rep.golden["vctrl_gold_v"] = float(vctrl_gold)
    rep.golden["t_settle_s"] = float(t_settle)


# ------------------------------------------------------------------- entry
def export(pll, outdir, *, name: str | None = None,
           flavors: tuple[str, ...] = ("rtl", "rnm", "ams"),
           n_golden: int = 16384, n_vectors: int = 4096) -> ExportReport:
    """Export one architecture instance to <outdir>/<name>/{rtl,rnm,ams}."""
    kind = _kind_of(pll)
    name = name or f"{kind}_{int(pll.cfg.fout / 1e6)}m"
    outdir = Path(outdir) / name
    rep = ExportReport(name=name, kind=kind, outdir=outdir)
    rep.golden["f_lock_hz"] = float(pll.cfg.fout)

    if "rtl" in flavors:
        _export_rtl(pll, kind, outdir, rep, n_vectors)
    if "rnm" in flavors:
        _export_rnm(pll, kind, name, outdir, rep, n_golden)
    if "ams" in flavors:
        _export_ams(pll, kind, name, outdir, rep)

    fl = flicker_delta_fs(pll) if "rnm" in flavors else None
    write_file(outdir / "README.md",
               emit_readme(name, kind, rep.files, rep.golden, rep.warnings, fl))
    rep.files["."] = ["README.md"]
    return rep


def export_all(plls: dict[str, object], outdir,
               flavors=("rtl", "rnm", "ams")) -> list[ExportReport]:
    return [export(pll, outdir, name=nm, flavors=flavors)
            for nm, pll in plls.items()]
