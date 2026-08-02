"""Architecture selector: rank all seven architectures against a target.

    from pllsim.selector import Requirement, select
    rep = select(Requirement(fref=100e6, fout=8e9, jitter_fs_max=120))
    print(rep.table())
    pll = rep.best.pll          # ready-to-simulate instance

For each architecture family a technology-class template (the same classes
the presets use — LC oscillator ~-122 dBc/Hz @ 1 MHz at 4.8 GHz, scaled
20log10(f/4.8G); ring for the MDLL) is instantiated at the requested
frequency plan, its loop synthesized with pllsim.synth, and analyze() run.
Candidates are ranked by linear-model jitter; hard infeasibilities (e.g.
injection-locked multiplier on a fractional channel) are excluded with the
reason recorded.  The output is a design shortlist with margins — the
starting point the presets were for single architectures, automated across
all of them.  Scores are linear-model; confirm the shortlist in the time
domain (simulate) before committing.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .arch.adpll import ADPLL, ADPLLConfig, DLFConfig
from .arch.cppll import CPPLL, CPPLLConfig, FracConfig
from .arch.ilcm import ILCM, ILCMConfig
from .arch.mdll import MDLL, MDLLConfig
from .arch.spll import SPLL, SPLLConfig
from .arch.sspll import SSPLL, SSPLLConfig
from .blocks.chargepump import CPConfig
from .blocks.dtc import DTCConfig
from .blocks.loopfilter import FilterDesign
from .blocks.oscillator import OscConfig
from .blocks.sampler import SamplerConfig
from .blocks.tdc import TDCConfig
from .calibration.lms import SignSignLMS
from .modulation import supports_two_point
from .synth import cppll_kdet, design_adpll_dlf, design_cp_filter, design_sspll_filter


@dataclass
class Requirement:
    fref: float
    fout: float
    jitter_fs_max: float
    int_band: tuple = (10e3, 40e6)
    modulation: bool = False       # needs two-point TX support
    ring_ok: bool = True           # allow ring-oscillator architectures

    @property
    def n(self) -> float:
        return self.fout / self.fref

    @property
    def fractional(self) -> bool:
        return abs(self.n - round(self.n)) > 1e-9


@dataclass
class Candidate:
    arch: str
    pll: object | None
    jitter_fs: float = float("nan")
    f_ugb: float = float("nan")
    pm_deg: float = float("nan")
    feasible: bool = True
    notes: list[str] = field(default_factory=list)

    @property
    def key(self):
        return (not self.feasible, self.jitter_fs)


def _osc(req: Requirement) -> OscConfig:
    """LC-oscillator technology class scaled to the target frequency."""
    pn = -122.0 + 20.0 * np.log10(req.fout / 4.8e9)
    return OscConfig(f0=req.fout * 0.99, gain=max(60e6, req.fout / 80.0),
                     pn_dbchz=pn, pn_foffset=1e6, pn_f1f3=3e5,
                     pn_floor_dbchz=pn - 31.0)


def _frac_cfg(req: Requirement, mash: int) -> FracConfig | None:
    if not req.fractional:
        return None
    return FracConfig(frac=req.n % 1.0, mash_order=mash,
                      dtc=DTCConfig(t_res=250e-15, n_bits=12 if mash > 1
                                    else 10, jitter_rms_s=30e-15),
                      dtc_cal=SignSignLMS(init=1.0, mu=5e-6,
                                          gear_shift_n=60_000,
                                          mu_final=5e-7))


def _try(fn):
    try:
        return fn(), None
    except Exception as exc:                       # infeasible synthesis
        return None, str(exc)


def _mk_cppll(req):
    osc = _osc(req)
    icp = 1.5e-3
    ugb = min(req.fref / 15.0, 2e6)
    filt = design_cp_filter(cppll_kdet(icp, req.n), osc.gain, ugb, 58.0,
                            req.fref)
    return CPPLL(CPPLLConfig(
        fref=req.fref, fout=req.fout, osc=osc,
        cp=CPConfig(icp=icp, mismatch_pct=1.0, leakage_a=1e-9,
                    t_reset=150e-12),
        filt=filt, ref_pn_dbchz=-160.0, int_band=req.int_band,
        frac=_frac_cfg(req, mash=2)))


def _mk_sspll(req):
    osc = _osc(req)
    samp = SamplerConfig(amp_v=0.5, c_samp=100e-15, gm=2e-3,
                         pulse_width=min(200e-12, 0.1 / req.fref),
                         pedestal_v=1e-3)
    ugb = min(req.fref / 20.0, 2e6)
    filt = design_sspll_filter(samp.amp_v * samp.gm * samp.pulse_width,
                               osc.gain, ugb, 60.0, req.fref)
    return SSPLL(SSPLLConfig(
        fref=req.fref, fout=req.fout, osc=osc, sampler=samp, filt=filt,
        ref_pn_dbchz=-160.0, fll_i=1e-6, fll_engage=2e6, fll_release=400e3,
        frac=_frac_cfg(req, mash=1), int_band=req.int_band))


def _mk_spll(req):
    osc = _osc(req)
    samp = SamplerConfig(amp_v=0.8, c_samp=1e-12, gm=8e-3,
                         pulse_width=min(1e-9, 0.1 / req.fref),
                         pedestal_v=1e-3)
    return SPLL(SPLLConfig(
        fref=req.fref, fout=req.fout, osc=osc, sampler=samp,
        filt=FilterDesign(c1=1e-9, r2=3e3, c2=4.7e-12, r3=1e3, c3=2.2e-12),
        ref_pn_dbchz=-160.0, fll_i=2e-6, fll_engage=3e6, fll_release=600e3,
        frac=_frac_cfg(req, mash=1), int_band=req.int_band))


def _mk_adpll_tdc(req):
    osc = _osc(req)
    osc = OscConfig(f0=req.fout, gain=20e3, pn_dbchz=osc.pn_dbchz + 6.0,
                    pn_foffset=1e6, pn_f1f3=4e5,
                    pn_floor_dbchz=osc.pn_floor_dbchz + 4.0)   # DCO class
    alpha, rho = design_adpll_dlf(req.fref, min(req.fref / 50.0, 2e6),
                                  55.0, iir_lambdas=(0.5,))
    return ADPLL(ADPLLConfig(
        fref=req.fref, fout=req.fout, osc=osc,
        dlf=DLFConfig(alpha=alpha, rho=rho, iir_lambdas=(0.5,)),
        tdc=TDCConfig(t_res=0.5e-12, n_bits=8),
        ref_pn_dbchz=-158.0, int_band=req.int_band))


def _mk_adpll_bb(req):
    if not req.fractional:
        raise ValueError("DTC+BBPD loop is a fractional-N architecture; "
                         "use adpll_tdc for integer channels")
    osc = _osc(req)
    osc = OscConfig(f0=req.fout, gain=20e3, pn_dbchz=osc.pn_dbchz + 6.0,
                    pn_foffset=1e6, pn_f1f3=4e5,
                    pn_floor_dbchz=osc.pn_floor_dbchz + 4.0)
    return ADPLL(ADPLLConfig(
        fref=req.fref, fout=req.fout, osc=osc,
        dlf=DLFConfig(alpha=1.0, rho=2**-8), mode="dtc_bbpd",
        frac=_frac_cfg(req, mash=2), bb_jitter_rms_s=150e-15,
        ref_pn_dbchz=-158.0, int_band=req.int_band))


def _mk_ilcm(req):
    if req.fractional:
        raise ValueError("injection locking needs an integer multiple "
                         "(realignment cannot cancel a fractional residue)")
    if req.n > 64:
        raise ValueError(f"N = {req.n:.0f}: injection lock range "
                         "beta*fref/2 impractical beyond N ~ 64")
    osc = OscConfig(f0=req.fout, gain=1.0, pn_dbchz=-105.0
                    + 20.0 * np.log10(req.fout / 12e9), pn_foffset=1e6,
                    pn_f1f3=5e5, pn_floor_dbchz=-145.0)
    return ILCM(ILCMConfig(
        fref=req.fref, fout=req.fout, osc=osc, beta=0.6, q_tank=8,
        i_ratio=0.15, inj_jitter_rms_s=15e-15, ref_pn_dbchz=-155.0,
        ftl_f_lsb=20e3, int_band=req.int_band))


def _mk_mdll(req):
    if req.fractional:
        raise ValueError("MDLL edge replacement needs an integer multiple")
    if not req.ring_ok:
        raise ValueError("MDLL is a ring-oscillator architecture "
                         "(ring_ok=False)")
    if req.fout > 4e9:
        raise ValueError(f"fout = {req.fout / 1e9:.1f} GHz: MDLL ring class "
                         "impractical above ~4 GHz")
    return MDLL(MDLLConfig(
        fref=req.fref, fout=req.fout,
        osc=OscConfig(f0=req.fout, gain=100e3, pn_dbchz=-95.0, pn_foffset=1e6,
                      pn_f1f3=8e5, pn_floor_dbchz=-140.0),
        mux_jitter_rms_s=40e-15, ref_pn_dbchz=-160.0, int_band=req.int_band))


_TEMPLATES = {
    "cppll": _mk_cppll,
    "sspll": _mk_sspll,
    "spll": _mk_spll,
    "adpll_tdc": _mk_adpll_tdc,
    "adpll_bbpd": _mk_adpll_bb,
    "ilcm": _mk_ilcm,
    "mdll": _mk_mdll,
}



@dataclass
class SelectorReport:
    req: Requirement
    candidates: list[Candidate]

    @property
    def best(self) -> Candidate | None:
        ok = [c for c in self.candidates
              if c.feasible and c.jitter_fs <= self.req.jitter_fs_max]
        return min(ok, key=lambda c: c.jitter_fs) if ok else None

    def table(self) -> str:
        w = max(len(c.arch) for c in self.candidates) + 2
        lines = [f"{'arch':{w}s}{'jitter':>10s}{'target':>9s}{'UGB':>10s}"
                 f"{'PM':>6s}  notes"]
        for c in sorted(self.candidates, key=lambda c: c.key):
            if c.feasible:
                mark = "PASS" if c.jitter_fs <= self.req.jitter_fs_max \
                    else "fail"
                ugb = f"{c.f_ugb / 1e3:8.0f}k" if np.isfinite(c.f_ugb) \
                    else f"{'-':>9s}"
                pm = f"{c.pm_deg:5.0f}d" if np.isfinite(c.pm_deg) \
                    else f"{'-':>6s}"
                lines.append(f"{c.arch:{w}s}{c.jitter_fs:8.0f}fs{mark:>9s}"
                             f"{ugb}{pm}  " + "; ".join(c.notes))
            else:
                lines.append(f"{c.arch:{w}s}{'-':>10s}{'excl.':>9s}"
                             f"{'-':>10s}{'-':>6s}  " + "; ".join(c.notes))
        return "\n".join(lines)


def select(req: Requirement) -> SelectorReport:
    cands = []
    for arch, mk in _TEMPLATES.items():
        pll, err = _try(lambda mk=mk: mk(req))
        c = Candidate(arch=arch, pll=pll)
        if pll is None:
            c.feasible = False
            c.notes.append(err)
            cands.append(c)
            continue
        ar, err = _try(pll.analyze)
        if ar is None:
            c.feasible = False
            c.notes.append(f"analyze failed: {err}")
            cands.append(c)
            continue
        c.jitter_fs = float(ar.jitter_fs)
        c.f_ugb = float(ar.loop.f_ugb)
        c.pm_deg = float(ar.loop.pm_deg)
        if req.modulation and not supports_two_point(pll):
            # a hard gate, not a note: recommending an architecture whose
            # engine cannot inject mod_freq means the modulation requirement
            # silently did not participate in the ranking
            c.feasible = False
            c.notes.append("no two-point TX wiring in this engine")
        if req.fractional and arch in ("cppll", "adpll_bbpd"):
            c.notes.append("MASH-2 + DTC")
        elif req.fractional and arch in ("sspll", "spll"):
            c.notes.append("EFM1 + DTC on the sampling path")
        cands.append(c)
    return SelectorReport(req=req, candidates=cands)
