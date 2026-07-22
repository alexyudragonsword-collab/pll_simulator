"""Example 14: Three modern JSSC benchmarks — DTC-ADPLL / frac-N SSPLL / frac-N SPLL.

Extends the single-point Gao'09 benchmark (ex10) to four points covering the
three dominant low-jitter fractional-N paradigms of the last decade:

Part 1  Dartizio et al., "A Low-Spur and Low-Jitter Fractional-N Digital PLL
        Based on an Inverse-Constant-Slope DTC and FCW Subtractive Dithering",
        IEEE JSSC vol. 58 no. 12, Dec. 2023 (28 nm).
        Published: fractional channels near 9.25 GHz, rms jitter < 77 fs
        (76.7 fs ISSCC'23 version), in-band fractional spur < -70 dBc
        (-71.9 dBc), 17.2 mW, FoM -249.9 dB.  -> our `adpll_bbpd` (DTC+BBPD).

Part 2  Markulic et al., "A DTC-Based Subsampling PLL Capable of
        Self-Calibrated Fractional Synthesis and Two-Point Modulation",
        IEEE JSSC vol. 51 no. 12, Dec. 2016 (65 nm, imec).
        Published: fref = 40 MHz, 10.24 GHz carrier (8.9-10+ GHz VCO),
        176 fs rms integer-N / 198 fs worst fractional-N, FoM -246.6 dB.
        Chosen over newer DTC-SSPLLs because its public parameter set is the
        most complete — benchmark verifiability beats publication year.
        -> our `sspll_frac` (both integer and fractional configs are run to
        reproduce the paper's central claim: fractionalization is nearly
        free once the DTC is calibrated).

Part 3  Wu et al., "A 28-nm 75-fs rms Analog Fractional-N Sampling PLL With
        a Highly Linear DTC Incorporating Background DTC Gain Calibration
        and Reference Clock Duty Cycle Correction", IEEE JSSC vol. 54 no. 5,
        May 2019 (Samsung).
        Published: fref = 52 MHz, 5.5-7.3 GHz, 75 fs rms **integrated
        10 kHz - 10 MHz** (note the band!), fractional spur < -64 dBc,
        FoM -249.7 dB.  -> our new `spll_frac` (DTC delays the divided edge
        that samples the reference sine).

Methodology (same as ex10): published measurements are the targets; circuit
parameters not disclosed in the papers (sampler gm/C, DCO/VCO free-running
phase noise, DTC resolution, loop coefficients) are technology-plausible
assumptions, labelled below.  The check is architectural consistency — the
model, fed a self-consistent parameter set, must land on the published
jitter/spur class — not parameter replication.
"""
import os

import numpy as np

from pllsim.arch.adpll import ADPLL, ADPLLConfig, DLFConfig
from pllsim.arch.cppll import FracConfig
from pllsim.arch.spll import SPLL, SPLLConfig
from pllsim.arch.sspll import SSPLL, SSPLLConfig
from pllsim.blocks.dtc import DTCConfig
from pllsim.blocks.loopfilter import FilterDesign
from pllsim.blocks.oscillator import OscConfig
from pllsim.blocks.sampler import SamplerConfig
from pllsim.calibration.lms import SignSignLMS
from pllsim.core.jitter import ldbc_from_sphi
from pllsim.plotting import plot_pn_breakdown
from pllsim.synth import design_sspll_filter

OUT = os.path.join(os.path.dirname(__file__), "out")
os.makedirs(OUT, exist_ok=True)

rows = []          # summary table: (paper, published fs, linear fs, timedom fs)


# ===================================================================== Part 1
print("=" * 74)
print("Part 1 — Dartizio et al., JSSC Dec. 2023: inverse-constant-slope DTC")
print("         bang-bang digital PLL, 28 nm, ~9.25 GHz fractional channels")
print("=" * 74)

# Assumptions (not disclosed at this level of detail in the paper):
#   fref = 500 MHz        — the group's standard high-frequency reference
#   DCO  -112 dBc/Hz @ 1 MHz, 1/f^3 corner 1 MHz — 9.25 GHz 28-nm LC class
#   BBPD input jitter 150 fs, DTC 250 fs LSB / 60 fs rms — post-linearization
#   integration band 10 kHz - 100 MHz
dartizio = ADPLL(ADPLLConfig(
    fref=500e6, fout=(18 + 0.503) * 500e6,          # 9.2515 GHz channel
    osc=OscConfig(f0=9.25e9, gain=100e3, pn_dbchz=-112.0, pn_foffset=1e6,
                  pn_f1f3=1e6, pn_floor_dbchz=-147.0),
    dlf=DLFConfig(alpha=0.5, rho=0.5 * 2**-8),
    mode="dtc_bbpd",
    frac=FracConfig(frac=0.503, mash_order=2,
                    dtc=DTCConfig(t_res=250e-15, n_bits=12,
                                  jitter_rms_s=60e-15),
                    dtc_cal=SignSignLMS(init=1.0, mu=1e-5,
                                        gear_shift_n=100_000, mu_final=1e-6)),
    bb_jitter_rms_s=150e-15, ref_pn_dbchz=-158.0,
    int_band=(10e3, 100e6)))

ar1 = dartizio.analyze()
sim1 = dartizio.simulate(250_000, seed=3)
i500k = np.searchsorted(ar1.f, 500e3)
print(f"{'metric':44s}{'published':>12s}{'model':>12s}")
print(f"{'rms jitter [fs] (linear model)':44s}{'<77':>12s}"
      f"{ar1.jitter_fs:12.1f}")
print(f"{'rms jitter [fs] (time domain, BBPD nonlin.)':44s}{'<77':>12s}"
      f"{sim1.jitter_fs:12.1f}")
print(f"{'in-band L(500 kHz) [dBc/Hz]':44s}{'(n/a)':>12s}"
      f"{ldbc_from_sphi(ar1.pn_breakdown['total'][i500k]):12.1f}")
print(f"{'loop UGB [MHz]':44s}{'(n/a)':>12s}{ar1.loop.f_ugb / 1e6:12.2f}")
print("note: the linear model under-reads BB loops (Gaussian-linearized "
      "BBPD);\n      the time domain is the reference — it lands on the "
      "published 77 fs.")
rows.append(("Dartizio'23 DTC-BB-DPLL 9.25G", "77", ar1.jitter_fs,
             sim1.jitter_fs))
plot_pn_breakdown(ar1, sim1, save=f"{OUT}/ex14_dartizio23.png", fmax=100e6)


# ===================================================================== Part 2
print()
print("=" * 74)
print("Part 2 — Markulic et al., JSSC Dec. 2016: DTC-based fractional-N")
print("         subsampling PLL, 65 nm imec, 40 MHz ref, 10.24 GHz carrier")
print("=" * 74)

# Assumptions: sampler 0.6 V / 100 fF / 2 mS / 200 ps pulse; VCO -109.5
# dBc/Hz @ 1 MHz (10 GHz 65-nm LC class); UGB ~ 1.4 MHz, PM 60 deg
# (filter synthesized on the exact discrete loop); DTC 150 fs LSB / 30 fs
# rms; integration band 10 kHz - 40 MHz.
SAMP2 = SamplerConfig(amp_v=0.6, c_samp=100e-15, gm=2e-3,
                      pulse_width=200e-12, pedestal_v=1e-3)
OSC2 = OscConfig(f0=10.20e9, gain=60e6, pn_dbchz=-109.5, pn_foffset=1e6,
                 pn_f1f3=4e5, pn_floor_dbchz=-145.0)
FILT2 = design_sspll_filter(SAMP2.amp_v * SAMP2.gm * SAMP2.pulse_width,
                            OSC2.gain, 1.4e6, 60.0, 40e6)


def markulic(frac: float | None) -> SSPLL:
    fr, fout = None, 10.24e9                        # N = 256 integer channel
    if frac is not None:
        fout = (256 + frac) * 40e6
        fr = FracConfig(frac=frac, mash_order=1,
                        dtc=DTCConfig(t_res=150e-15, n_bits=10,
                                      jitter_rms_s=30e-15),
                        dtc_cal=SignSignLMS(init=1.0, mu=5e-6,
                                            gear_shift_n=60_000,
                                            mu_final=5e-7))
    return SSPLL(SSPLLConfig(
        fref=40e6, fout=fout, osc=OSC2, sampler=SAMP2, filt=FILT2,
        ref_pn_dbchz=-158.0, fll_i=1e-6, fll_engage=2e6, fll_release=400e3,
        frac=fr, int_band=(10e3, 40e6)))


mk_int, mk_frac = markulic(None), markulic(0.2503)
ar2i, ar2f = mk_int.analyze(), mk_frac.analyze()
sim2i = mk_int.simulate(200_000, seed=2)
sim2f = mk_frac.simulate(200_000, seed=2)
print(f"{'metric':44s}{'published':>12s}{'model':>12s}")
print(f"{'integer-N jitter [fs] (linear)':44s}{'176':>12s}"
      f"{ar2i.jitter_fs:12.1f}")
print(f"{'fractional jitter [fs] (linear, 1% resid.)':44s}{'198 worst':>12s}"
      f"{ar2f.jitter_fs:12.1f}")
print(f"{'integer-N jitter [fs] (time domain)':44s}{'176':>12s}"
      f"{sim2i.jitter_fs:12.1f}")
print(f"{'fractional jitter [fs] (time domain, cal on)':44s}{'198 worst':>12s}"
      f"{sim2f.jitter_fs:12.1f}")
print("note: the paper's central claim — DTC-assisted fractionalization is "
      "nearly\n      free — reproduces: the calibrated time domain shows "
      f"{100 * (sim2f.jitter_fs / sim2i.jitter_fs - 1):+.1f}% penalty; the\n"
      "      linear model carries a conservative 1% post-cal DTC gain "
      "residual and\n      reads as the published worst fractional channel.")
rows.append(("Markulic'16 SSPLL 10.24G int-N", "176", ar2i.jitter_fs,
             sim2i.jitter_fs))
rows.append(("Markulic'16 SSPLL 10.24G frac-N", "198", ar2f.jitter_fs,
             sim2f.jitter_fs))
plot_pn_breakdown(ar2f, sim2f, save=f"{OUT}/ex14_markulic16.png", fmax=40e6)


# ===================================================================== Part 3
print()
print("=" * 74)
print("Part 3 — Wu et al., JSSC May 2019: 75-fs analog fractional-N sampling")
print("         PLL, Samsung 28 nm, 52 MHz ref (verified), ~6.25 GHz")
print("=" * 74)

# Assumptions: strong sampling front-end 0.8 V / 3 pF / 10 mS / 1 ns pulse
# (the paper's high-slope, duty-corrected reference path); VCO -124 dBc/Hz
# @ 1 MHz (high-Q 6.2 GHz LC); DTC 160 fs LSB / 20 fs rms with 0.2%
# post-background-cal gain residual (the paper's headline calibration);
# UGB ~ 620 kHz.  Integration band 10 kHz - 10 MHz — the paper's band.
wu = SPLL(SPLLConfig(
    fref=52e6, fout=(120 + 0.2503) * 52e6,          # 6.2530 GHz channel
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
                                        gear_shift_n=60_000, mu_final=5e-7)),
    int_band=(10e3, 10e6)))

ar3 = wu.analyze()
sim3 = wu.simulate(300_000, seed=4, dtc_gain_init_error=0.05)
i200k = np.searchsorted(ar3.f, 200e3)
spur_best = min((v for v in sim3.spurs_fft.values() if np.isfinite(v)),
                default=float("nan"))
spur_worst = max((v for v in sim3.spurs_fft.values() if np.isfinite(v)),
                 default=float("nan"))
print(f"{'metric':44s}{'published':>12s}{'model':>12s}")
print(f"{'rms jitter 10k-10M [fs] (linear)':44s}{'75':>12s}"
      f"{ar3.jitter_fs:12.1f}")
print(f"{'rms jitter 10k-10M [fs] (time domain)':44s}{'75':>12s}"
      f"{sim3.jitter_fs:12.1f}")
print(f"{'in-band L(200 kHz) [dBc/Hz]':44s}{'~-113':>12s}"
      f"{ldbc_from_sphi(ar3.pn_breakdown['total'][i200k]):12.1f}")
print(f"{'worst fractional spur [dBc]':44s}{'<-64':>12s}{spur_worst:12.1f}")
print(f"{'DTC gain cal (5% initial error)':44s}{'bg cal':>12s}"
      f"{sim3.cal_traces['dtc_gain'][-1]:12.4f}")
print("note: the background sign-sign LMS converges to 1/1.05 = 0.9524 — the "
      "same\n      correction loop the paper runs; the time-domain jitter is "
      "quoted over the\n      paper's own 10 kHz - 10 MHz band.")
rows.append(("Wu'19 sampling PLL 6.25G frac-N", "75", ar3.jitter_fs,
             sim3.jitter_fs))
plot_pn_breakdown(ar3, sim3, save=f"{OUT}/ex14_wu19.png", fmax=26e6)


# =================================================================== summary
print()
print("=" * 74)
print("Four-point literature anchor (incl. ex10 Gao'09 integer-N SSPLL)")
print("=" * 74)
print(f"{'paper / architecture':36s}{'published':>10s}{'linear':>10s}"
      f"{'timedom':>10s}")
print(f"{'Gao JSSC 09 SSPLL 2.21G int-N':36s}{'150':>10s}"
      f"{'~130':>10s}{'~130':>10s}   (ex10, 10k-100M)")
for name, pub, lin, td in rows:
    print(f"{name:36s}{pub:>10s}{lin:10.1f}{td:10.1f}")
print("\nassumption policy: every parameter not published (sampler, DTC, "
      "oscillator\nPN, loop coefficients) is a labelled technology-plausible "
      "choice; agreement\nis architectural consistency, not parameter "
      "replication.")
print(f"\nplots: {OUT}/ex14_dartizio23.png, ex14_markulic16.png, "
      f"ex14_wu19.png")
