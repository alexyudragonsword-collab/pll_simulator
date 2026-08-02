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
        fll_i=0.5e-6, fll_engage=2e6, fll_release=400e3))


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
        fll_i=1e-6, fll_engage=3e6, fll_release=600e3))


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
        fll_i=0.5e-6, fll_engage=2e6, fll_release=400e3,
        frac=FracConfig(frac=frac, mash_order=1,
                        dtc=DTCConfig(t_res=250e-15, n_bits=10,
                                      jitter_rms_s=30e-15),
                        dtc_cal=SignSignLMS(init=1.0, mu=5e-6,
                                            gear_shift_n=60_000,
                                            mu_final=5e-7))))


def spll_frac_52m_6p253g() -> SPLL:
    """DTC-assisted fractional-N sampling PLL (Wu-style, ex14), ~240 fs."""
    frac = 0.2503
    return SPLL(SPLLConfig(
        fref=52e6, fout=(120 + frac) * 52e6,
        osc=OscConfig(f0=6.2e9, gain=60e6, pn_dbchz=-118.0, pn_foffset=1e6,
                      pn_f1f3=3e5, pn_floor_dbchz=-152.0),
        sampler=SamplerConfig(amp_v=0.5, c_samp=150e-15, gm=4e-3,
                              pulse_width=600e-12, pedestal_v=1e-3),
        filt=FilterDesign(c1=470e-12, r2=12e3, c2=2.2e-12, r3=1.5e3, c3=1e-12),
        ref_pn_dbchz=-160.0,
        fll_i=1e-6, fll_engage=3e6, fll_release=600e3,
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


# --------------------------------------------------------------------------
# JSSC literature-benchmark presets (ex10 / ex14).  Published measurements
# are the targets; circuit values not disclosed in the papers are labelled
# technology-plausible assumptions — see the examples for the methodology.
# --------------------------------------------------------------------------

def bench_gao09_sspll_55p25m_2p21g() -> SSPLL:
    """Gao et al., JSSC Dec 2009 (0.18um int-N SSPLL, ex10).

    Published: in-band ~-126 dBc/Hz, 0.15 ps rms (10k-100M), BW=fref/20.
    Model lands at -126.8 dBc/Hz / 0.122-0.139 ps."""
    from .synth import design_sspll_filter
    samp = SamplerConfig(amp_v=0.8, c_samp=800e-15, gm=2e-3,
                         pulse_width=200e-12, pedestal_v=0.5e-3)
    osc = OscConfig(f0=2.19e9, gain=30e6, pn_dbchz=-121.0, pn_foffset=1e6,
                    pn_f1f3=2e5, pn_floor_dbchz=-150.0)
    filt = design_sspll_filter(samp.amp_v * samp.gm * samp.pulse_width,
                               osc.gain, 55.25e6 / 20, 60.0, 55.25e6)
    return SSPLL(SSPLLConfig(
        fref=55.25e6, fout=2.21e9, osc=osc, sampler=samp, filt=filt,
        ref_pn_dbchz=-160.0, fll_i=1e-6, fll_engage=1.5e6,
        fll_release=300e3, int_band=(10e3, 100e6)))


def bench_dartizio23_adpllbb_500m_9p2515g() -> ADPLL:
    """Dartizio et al., JSSC Dec 2023 (28nm inverse-constant-slope DTC
    BBPD digital PLL, ex14 part 1).

    Published: <77 fs rms, in-band frac spur <-70 dBc near 9.25 GHz.
    Linear model 57 fs; TIME DOMAIN is the reference for BB loops: 77 fs."""
    return ADPLL(ADPLLConfig(
        fref=500e6, fout=(18 + 0.503) * 500e6,
        osc=OscConfig(f0=9.25e9, gain=100e3, pn_dbchz=-112.0, pn_foffset=1e6,
                      pn_f1f3=1e6, pn_floor_dbchz=-147.0),
        dlf=DLFConfig(alpha=0.5, rho=0.5 * 2**-8),
        mode="dtc_bbpd",
        frac=FracConfig(frac=0.503, mash_order=2,
                        dtc=DTCConfig(t_res=250e-15, n_bits=12,
                                      jitter_rms_s=60e-15),
                        dtc_cal=SignSignLMS(init=1.0, mu=1e-5,
                                            gear_shift_n=100_000,
                                            mu_final=1e-6)),
        bb_jitter_rms_s=150e-15, ref_pn_dbchz=-158.0,
        int_band=(10e3, 100e6)))


def _bench_markulic16(frac: float | None) -> SSPLL:
    from .synth import design_sspll_filter
    samp = SamplerConfig(amp_v=0.6, c_samp=100e-15, gm=2e-3,
                         pulse_width=200e-12, pedestal_v=1e-3)
    osc = OscConfig(f0=10.20e9, gain=60e6, pn_dbchz=-109.5, pn_foffset=1e6,
                    pn_f1f3=4e5, pn_floor_dbchz=-145.0)
    filt = design_sspll_filter(samp.amp_v * samp.gm * samp.pulse_width,
                               osc.gain, 1.4e6, 60.0, 40e6)
    fr, fout = None, 10.24e9
    if frac is not None:
        fout = (256 + frac) * 40e6
        fr = FracConfig(frac=frac, mash_order=1,
                        dtc=DTCConfig(t_res=150e-15, n_bits=10,
                                      jitter_rms_s=30e-15),
                        dtc_cal=SignSignLMS(init=1.0, mu=5e-6,
                                            gear_shift_n=60_000,
                                            mu_final=5e-7))
    return SSPLL(SSPLLConfig(
        fref=40e6, fout=fout, osc=osc, sampler=samp, filt=filt,
        ref_pn_dbchz=-158.0, fll_i=1e-6, fll_engage=2e6, fll_release=400e3,
        frac=fr, int_band=(10e3, 40e6)))


def bench_markulic16_sspll_40m_10p24g() -> SSPLL:
    """Markulic et al., JSSC Dec 2016 (65nm imec DTC-SSPLL, ex14 part 2),
    integer-N channel.  Published: 176 fs rms; model 165/154 fs."""
    return _bench_markulic16(None)


def bench_markulic16_sspll_frac_40m_10p25g() -> SSPLL:
    """Markulic et al., JSSC Dec 2016, fractional channel.

    Published: 198 fs worst fractional; the linear model with its
    conservative 1% post-cal residual reads 199 fs, the calibrated time
    domain 155 fs (fractionalization nearly free - the paper's claim)."""
    return _bench_markulic16(0.2503)


def bench_wu19_spll_frac_52m_6p253g() -> SPLL:
    """Wu et al., JSSC May 2019 (Samsung 28nm fractional sampling PLL,
    ex14 part 3).

    Published: 75 fs rms over the paper's 10 kHz-10 MHz band, frac spur
    <-64 dBc.  Model: 77/78 fs.  Differs from spll_frac_52m_6p253g (the
    generic mid-class preset): stronger sampling front-end, quieter VCO,
    0.2% post-background-cal DTC gain residual."""
    return SPLL(SPLLConfig(
        fref=52e6, fout=(120 + 0.2503) * 52e6,
        osc=OscConfig(f0=6.2e9, gain=60e6, pn_dbchz=-124.0, pn_foffset=1e6,
                      pn_f1f3=2e5, pn_floor_dbchz=-154.0),
        sampler=SamplerConfig(amp_v=0.8, c_samp=3e-12, gm=10e-3,
                              pulse_width=1e-9, pedestal_v=1e-3),
        filt=FilterDesign(c1=1e-9, r2=3e3, c2=4.7e-12, r3=1e3, c3=2.2e-12),
        ref_pn_dbchz=-165.0, div_pn_dbchz=-165.0,
        fll_i=2e-6, fll_engage=3e6, fll_release=600e3,
        frac=FracConfig(frac=0.2503, mash_order=1,
                        dtc=DTCConfig(t_res=160e-15, n_bits=10,
                                      jitter_rms_s=20e-15,
                                      gain_error_residual=0.002),
                        dtc_cal=SignSignLMS(init=1.0, mu=5e-6,
                                            gear_shift_n=60_000,
                                            mu_final=5e-7)),
        int_band=(10e3, 10e6)))


ALL_PRESETS = {
    "cppll_19p2m_4p8g": cppll_19p2m_4p8g,
    "cppll_frac_38p4m_6g": cppll_frac_38p4m_6g,
    "sspll_19p2m_4p8g": sspll_19p2m_4p8g,
    "sspll_frac_19p2m_4p806g": sspll_frac_19p2m_4p806g,
    "spll_100m_8g": spll_100m_8g,
    "spll_frac_52m_6p253g": spll_frac_52m_6p253g,
    "adpll_100m_10g": adpll_100m_10g,
    "adpll_bb_100m_10g": adpll_bb_100m_10g,
    "ilcm_250m_12g": ilcm_250m_12g,
    "mdll_150m_2p4g": mdll_150m_2p4g,
    "bench_gao09_sspll_55p25m_2p21g": bench_gao09_sspll_55p25m_2p21g,
    "bench_dartizio23_adpllbb_500m_9p2515g":
        bench_dartizio23_adpllbb_500m_9p2515g,
    "bench_markulic16_sspll_40m_10p24g": bench_markulic16_sspll_40m_10p24g,
    "bench_markulic16_sspll_frac_40m_10p25g":
        bench_markulic16_sspll_frac_40m_10p25g,
    "bench_wu19_spll_frac_52m_6p253g": bench_wu19_spll_frac_52m_6p253g,
}


# Published measurements and the time-domain numbers ex10/ex14 produce.  The
# LINEAR column is deliberately absent: it is computed from the preset on
# demand (benchmark_table) so it cannot go stale the way two hand-maintained
# copies of this table did -- both still carried the pre-v0.6.0 numbers after
# the gm-noise and DTC-jitter corrections moved them.
BENCHMARKS = [
    {"paper": "Gao'09 SSPLL 2.21G int-N (10k-100M)",
     "preset": "bench_gao09_sspll_55p25m_2p21g",
     "published [fs]": "150", "time-domain [fs]": "139"},
    {"paper": "Dartizio'23 DTC-BB digital PLL 9.25G frac-N",
     "preset": "bench_dartizio23_adpllbb_500m_9p2515g",
     "published [fs]": "77", "time-domain [fs]": "77"},
    {"paper": "Markulic'16 SSPLL 10.24G int-N",
     "preset": "bench_markulic16_sspll_40m_10p24g",
     "published [fs]": "176", "time-domain [fs]": "154"},
    {"paper": "Markulic'16 SSPLL 10.24G frac-N",
     "preset": "bench_markulic16_sspll_frac_40m_10p25g",
     "published [fs]": "198 (worst)", "time-domain [fs]": "155"},
    {"paper": "Wu'19 sampling PLL 6.25G frac-N (10k-10M)",
     "preset": "bench_wu19_spll_frac_52m_6p253g",
     "published [fs]": "75", "time-domain [fs]": "78"},
]


def benchmark_table() -> list[dict]:
    """The literature anchor with the linear-model column computed live."""
    rows = []
    for b in BENCHMARKS:
        ar = ALL_PRESETS[b["preset"]]().analyze()
        rows.append({"paper": b["paper"],
                     "published [fs]": b["published [fs]"],
                     "linear [fs]": round(float(ar.jitter_fs), 1),
                     "time-domain [fs]": b["time-domain [fs]"]})
    return rows
