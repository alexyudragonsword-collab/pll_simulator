"""Example 10: Literature benchmark — Gao et al., JSSC Dec. 2009.

"A Low Noise Sub-Sampling PLL in Which Divider Noise is Eliminated and
 PD/CP Noise is Not Multiplied by N^2", X. Gao, E. Klumperink, M. Bohsali,
 B. Nauta, IEEE JSSC vol. 44 no. 12 (0.18 um CMOS).

Published measurements used as targets (from the paper/companion slides):
  * fref = 55.25 MHz, fout = 2.21 GHz  (N = 40)
  * in-band phase noise  ~ -126 dBc/Hz
  * integrated jitter    ~ 0.15 ps rms (10 kHz - 100 MHz)
  * companion JSSC 2010 spur-reduction chip: BW up to fref/20, spur < -80 dBc

Methodology: the sampler/gm/filter values below are NOT published in full —
they are technology-plausible choices for 0.18 um consistent with the paper's
architecture description.  What IS being checked is that the architecture
model, fed a self-consistent parameter set, lands on the published in-band
noise and jitter — and that a classic CPPLL with identical reference, VCO
and CP-class current CANNOT get there (the paper's central claim).
"""
import os

import numpy as np

from pllsim.arch.cppll import CPPLL, CPPLLConfig
from pllsim.arch.sspll import SSPLL, SSPLLConfig
from pllsim.blocks.chargepump import CPConfig
from pllsim.blocks.loopfilter import FilterDesign
from pllsim.blocks.oscillator import OscConfig
from pllsim.blocks.sampler import SamplerConfig
from pllsim.core.jitter import ldbc_from_sphi, rms_jitter_fs
from pllsim.plotting import plot_pn_breakdown
from pllsim.synth import design_sspll_filter

OUT = os.path.join(os.path.dirname(__file__), "out")
os.makedirs(OUT, exist_ok=True)

FREF, FOUT, N = 55.25e6, 2.21e9, 40
BAND = (10e3, 100e6)                      # the paper's integration band

# 2.21 GHz LC-VCO in 0.18um: -121 dBc/Hz @ 1 MHz free-running (typical class)
OSC = OscConfig(f0=2.19e9, gain=30e6, pn_dbchz=-121.0, pn_foffset=1e6,
                pn_f1f3=2e5, pn_floor_dbchz=-150.0)
SAMP = SamplerConfig(amp_v=0.8, c_samp=800e-15, gm=2e-3,
                     pulse_width=200e-12, pedestal_v=0.5e-3)

# BW = fref/20 (the ratio the JSSC'10 companion chip runs), synthesized on
# the exact discrete loop
filt = design_sspll_filter(SAMP.amp_v * SAMP.gm * SAMP.pulse_width,
                           OSC.gain, FREF / 20, 60.0, FREF)
sspll = SSPLL(SSPLLConfig(
    fref=FREF, fout=FOUT, osc=OSC, sampler=SAMP, filt=filt,
    ref_pn_dbchz=-160.0, fll_i=1e-6, fll_engage=1.5e6, fll_release=300e3,
    int_band=BAND))
ar = sspll.analyze()
i200k = np.searchsorted(ar.f, 200e3)
inband = ldbc_from_sphi(ar.pn_breakdown["total"][i200k])
sim = sspll.simulate(300_000, seed=1)

print("=== SSPLL model vs Gao JSSC'09 published measurements ===")
print(f"{'metric':38s}{'published':>12s}{'model':>12s}")
print(f"{'in-band PN [dBc/Hz]':38s}{'-126':>12s}{inband:12.1f}")
print(f"{'jitter 10k-100M [ps rms] (linear)':38s}{'0.15':>12s}"
      f"{ar.jitter_fs / 1e3:12.3f}")
print(f"{'jitter 10k-100M [ps rms] (time dom)':38s}{'0.15':>12s}"
      f"{sim.jitter_fs / 1e3:12.3f}")
print(f"{'loop UGB [kHz] (fref/20, JSSC10)':38s}{'~2760':>12s}"
      f"{ar.loop.f_ugb / 1e3:12.0f}")

# --- the paper's central claim: same blocks in a classic CPPLL fall short ---
cp_equiv = CPPLL(CPPLLConfig(
    fref=FREF, fout=FOUT, osc=OSC,
    # CP current chosen to give the same PD-path power class as the gm pulser
    cp=CPConfig(icp=SAMP.gm * SAMP.amp_v * 0.2, mismatch_pct=1.0,
                leakage_a=0.5e-9, t_reset=200e-12),
    filt=FilterDesign(c1=2.2e-9, r2=6.8e3, c2=15e-12, r3=1.5e3, c3=6.8e-12),
    ref_pn_dbchz=-160.0, int_band=BAND))
ar_cp = cp_equiv.analyze()
i200k_cp = np.searchsorted(ar_cp.f, 200e3)
print(f"\nclassic CPPLL, same fref/VCO, CP-class current "
      f"{cp_equiv.cfg.cp.icp * 1e6:.0f} uA:")
print(f"  in-band PN = {ldbc_from_sphi(ar_cp.pn_breakdown['total'][i200k_cp]):.1f} "
      f"dBc/Hz, jitter = {ar_cp.jitter_fs / 1e3:.3f} ps "
      f"(the N^2 penalty the SSPLL removes)")

plot_pn_breakdown(ar, sim, save=f"{OUT}/ex10_benchmark_gao.png", fmax=100e6)
print(f"\nplot saved to {OUT}/ex10_benchmark_gao.png")
print("\nnote: sampler/filter values are technology-plausible assumptions "
      "(not published); the check is architectural consistency with the "
      "measured in-band PN and jitter.")
