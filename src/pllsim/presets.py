"""Ready-made example configurations (fref 19.2-250 MHz, fout up to 12 GHz).

Each factory returns a fresh architecture instance whose analyze() jitter
lands in the 50-200 fs class (except the deliberately pedestrian CPPLL
baseline).  Calibrator objects are created per call — they carry state.
"""
from __future__ import annotations

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


def cppll_19p2m_4p8g() -> CPPLL:
    """Integer-N charge-pump baseline (ex01), ~260 fs."""
    return CPPLL(CPPLLConfig(
        fref=19.2e6, fout=4.8e9,
        osc=OscConfig(f0=4.75e9, gain=60e6, pn_dbchz=-122.0, pn_foffset=1e6,
                      pn_f1f3=3e5, pn_floor_dbchz=-155.0),
        cp=CPConfig(icp=1.5e-3, mismatch_pct=2.0, leakage_a=1e-9,
                    t_reset=200e-12),
        filt=FilterDesign(c1=680e-12, r2=20e3, c2=3.3e-12, r3=2e3, c3=2.2e-12),
        ref_pn_dbchz=-162.0))


def cppll_frac_38p4m_6g() -> CPPLL:
    """Fractional-N + DTC + sign-sign LMS gain cal (ex02), ~170 fs."""
    return CPPLL(CPPLLConfig(
        fref=38.4e6, fout=(156 + 0.2525) * 38.4e6,
        osc=OscConfig(f0=5.95e9, gain=80e6, pn_dbchz=-120.0, pn_foffset=1e6,
                      pn_f1f3=3e5, pn_floor_dbchz=-152.0),
        cp=CPConfig(icp=1.5e-3, mismatch_pct=1.0, leakage_a=1e-9,
                    t_reset=150e-12),
        filt=FilterDesign(c1=470e-12, r2=15e3, c2=3.3e-12, r3=1.5e3, c3=2.2e-12),
        ref_pn_dbchz=-160.0,
        frac=FracConfig(frac=0.2525, mash_order=2,
                        dtc=DTCConfig(t_res=250e-15, n_bits=12,
                                      jitter_rms_s=30e-15),
                        dtc_cal=SignSignLMS(init=1.0, mu=5e-6,
                                            gear_shift_n=100_000,
                                            mu_final=5e-7))))


def sspll_19p2m_4p8g() -> SSPLL:
    """Sub-sampling PLL with FLL (ex03), ~150 fs — compare cppll_19p2m_4p8g."""
    return SSPLL(SSPLLConfig(
        fref=19.2e6, fout=4.8e9,
        osc=OscConfig(f0=4.75e9, gain=60e6, pn_dbchz=-122.0, pn_foffset=1e6,
                      pn_f1f3=3e5, pn_floor_dbchz=-155.0),
        sampler=SamplerConfig(amp_v=0.4, c_samp=60e-15, gm=1e-3,
                              pulse_width=150e-12, pedestal_v=1e-3),
        filt=FilterDesign(c1=680e-12, r2=20e3, c2=2.2e-12, r3=2e3, c3=1e-12),
        ref_pn_dbchz=-162.0,
        fll_i=1e-6, fll_engage=2e6, fll_release=400e3))


def spll_100m_8g() -> SPLL:
    """Reference-sampling PLL (ex04), ~200 fs, sampler noise x N."""
    return SPLL(SPLLConfig(
        fref=100e6, fout=8e9,
        osc=OscConfig(f0=7.92e9, gain=80e6, pn_dbchz=-118.0, pn_foffset=1e6,
                      pn_f1f3=3e5, pn_floor_dbchz=-152.0),
        sampler=SamplerConfig(amp_v=0.4, c_samp=100e-15, gm=4e-3,
                              pulse_width=800e-12, pedestal_v=1e-3),
        filt=FilterDesign(c1=330e-12, r2=12e3, c2=2.2e-12, r3=1.5e3, c3=1e-12),
        ref_pn_dbchz=-160.0,
        fll_i=2e-6, fll_engage=3e6, fll_release=600e3))


def adpll_100m_10g() -> ADPLL:
    """Counter-assisted fractional ADPLL (ex05 part 1), ~110 fs."""
    return ADPLL(ADPLLConfig(
        fref=100e6, fout=100.503 * 100e6,
        osc=OscConfig(f0=10.0e9, gain=20e3, pn_dbchz=-112.0, pn_foffset=1e6,
                      pn_f1f3=4e5, pn_floor_dbchz=-150.0),
        dlf=DLFConfig(alpha=2**-4, rho=2**-11, iir_lambdas=(0.5,)),
        tdc=TDCConfig(t_res=0.5e-12, n_bits=8),
        ref_pn_dbchz=-158.0))


def ilcm_250m_12g() -> ILCM:
    """Injection-locked clock multiplier with FTL (ex06), ~115 fs."""
    return ILCM(ILCMConfig(
        fref=250e6, fout=12e9,
        osc=OscConfig(f0=12e9, gain=1.0, pn_dbchz=-105.0, pn_foffset=1e6,
                      pn_f1f3=5e5, pn_floor_dbchz=-145.0),
        beta=0.6, q_tank=8, i_ratio=0.15, inj_jitter_rms_s=15e-15,
        ref_pn_dbchz=-155.0, ftl_f_lsb=20e3))


def adpll_bb_100m_10g() -> ADPLL:
    """DTC + bang-bang fractional ADPLL (ex05 part 2), ~120 fs."""
    from .blocks.dtc import DTCConfig
    return ADPLL(ADPLLConfig(
        fref=100e6, fout=100.503 * 100e6,
        osc=OscConfig(f0=10.0e9, gain=20e3, pn_dbchz=-112.0, pn_foffset=1e6,
                      pn_f1f3=4e5, pn_floor_dbchz=-150.0),
        dlf=DLFConfig(alpha=2.0, rho=2**-6),
        mode="dtc_bbpd",
        frac=FracConfig(frac=0.503, mash_order=2,
                        dtc=DTCConfig(t_res=250e-15, n_bits=12,
                                      jitter_rms_s=50e-15),
                        dtc_cal=SignSignLMS(init=1.0, mu=1e-5,
                                            gear_shift_n=100_000,
                                            mu_final=1e-6)),
        bb_jitter_rms_s=200e-15, ref_pn_dbchz=-158.0))


def sspll_frac_19p2m_4p806g() -> SSPLL:
    """DTC-assisted fractional-N SSPLL (ex08), ~150 fs."""
    from .blocks.dtc import DTCConfig
    frac = 0.2503
    return SSPLL(SSPLLConfig(
        fref=19.2e6, fout=(250 + frac) * 19.2e6,
        osc=OscConfig(f0=4.755e9, gain=60e6, pn_dbchz=-122.0, pn_foffset=1e6,
                      pn_f1f3=3e5, pn_floor_dbchz=-155.0),
        sampler=SamplerConfig(amp_v=0.4, c_samp=60e-15, gm=1e-3,
                              pulse_width=150e-12, pedestal_v=1e-3),
        filt=FilterDesign(c1=680e-12, r2=20e3, c2=2.2e-12, r3=2e3, c3=1e-12),
        ref_pn_dbchz=-162.0,
        fll_i=1e-6, fll_engage=2e6, fll_release=400e3,
        frac=FracConfig(frac=frac, mash_order=1,
                        dtc=DTCConfig(t_res=250e-15, n_bits=10,
                                      jitter_rms_s=30e-15),
                        dtc_cal=SignSignLMS(init=1.0, mu=5e-6,
                                            gear_shift_n=60_000,
                                            mu_final=5e-7))))


def mdll_150m_2p4g() -> MDLL:
    """Multiplying DLL on a -95 dBc/Hz ring (ex12)."""
    return MDLL(MDLLConfig(
        fref=150e6, fout=2.4e9,
        osc=OscConfig(f0=2.4e9, gain=100e3, pn_dbchz=-95.0, pn_foffset=1e6,
                      pn_f1f3=8e5, pn_floor_dbchz=-140.0),
        mux_jitter_rms_s=40e-15, ref_pn_dbchz=-160.0))


ALL_PRESETS = {
    "cppll_19p2m_4p8g": cppll_19p2m_4p8g,
    "cppll_frac_38p4m_6g": cppll_frac_38p4m_6g,
    "sspll_19p2m_4p8g": sspll_19p2m_4p8g,
    "sspll_frac_19p2m_4p806g": sspll_frac_19p2m_4p806g,
    "spll_100m_8g": spll_100m_8g,
    "adpll_100m_10g": adpll_100m_10g,
    "adpll_bb_100m_10g": adpll_bb_100m_10g,
    "ilcm_250m_12g": ilcm_250m_12g,
    "mdll_150m_2p4g": mdll_150m_2p4g,
}
