"""Example 16: import measured phase noise and fit model parameters.

The reverse direction of everything so far: instead of predicting L(f) from
a parameter set, take a bench measurement (signal-source-analyzer CSV) and
recover the parameters — then let the noise budget name the block that is
over budget on silicon.

Three stages, each on synthetic "measurements" (generated from the model
with 0.5 dB rms instrument noise, so ground truth is known):

1. free-running VCO  -> fit_leeson: the OscConfig triple
   (pn @ 1 MHz, 1/f^3 corner, floor)
2. locked spectrum   -> fit_closed_loop: in-band plateau, loop UGB,
   peaking/damping + the oscillator triple through |1-H|^2
3. silicon debug     -> attribute_budget: the "chip" comes back with the
   reference 6 dB hot and the sampler cap at half value (+3 dB kT/C);
   NNLS attribution against the *nominal* budget names both, quantitatively
"""
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from pllsim import presets
from pllsim.blocks.oscillator import OscConfig
from pllsim.core.jitter import ldbc_from_sphi
from pllsim.fit import (attribute_budget, fit_closed_loop, fit_leeson,
                        load_pn_csv)

OUT = os.path.join(os.path.dirname(__file__), "out")
os.makedirs(OUT, exist_ok=True)
rng = np.random.default_rng(42)

# ------------------------------------------------ 1. free-running oscillator
print("=== 1. fit_leeson: free-running VCO measurement ===")
osc_true = OscConfig(f0=6.2e9, gain=60e6, pn_dbchz=-124.0, pn_foffset=1e6,
                     pn_f1f3=2e5, pn_floor_dbchz=-154.0)
f_meas = np.geomspace(1e3, 100e6, 120)
l_true = ldbc_from_sphi(osc_true.leeson().psd(f_meas))
l_meas = l_true + rng.normal(0.0, 0.5, f_meas.size)     # instrument noise

csv_path = f"{OUT}/ex16_vco_meas.csv"
with open(csv_path, "w") as fh:                          # E5052-style export
    fh.write("# Agilent E5052B SSA  6.2 GHz carrier\n"
             "Offset Frequency (Hz), Phase Noise (dBc/Hz)\n")
    for fo, ld in zip(f_meas, l_meas):
        fh.write(f"{fo:.6g}, {ld:.3f}\n")

f_csv, l_csv = load_pn_csv(csv_path)
lee = fit_leeson(f_csv, l_csv)
print(f"{'parameter':28s}{'true':>12s}{'fitted':>12s}")
print(f"{'L(1 MHz) 1/f^2 [dBc/Hz]':28s}{-124.0:12.1f}{lee.pn_dbchz:12.1f}")
print(f"{'1/f^3 corner [kHz]':28s}{200.0:12.1f}{lee.pn_f1f3 / 1e3:12.1f}")
print(f"{'floor [dBc/Hz]':28s}{-154.0:12.1f}{lee.pn_floor_dbchz:12.1f}")
print(f"fit residual {lee.residual_db_rms:.2f} dB rms "
      f"(instrument noise was 0.5 dB)")

# ---------------------------------------------------- 2. locked spectrum
print("\n=== 2. fit_closed_loop: locked spectrum (SSPLL preset ex03) ===")
pll = presets.sspll_19p2m_4p8g()
ar = pll.analyze()
sel = (ar.f >= 1e3) & (ar.f <= 100e6)
f_cl = ar.f[sel]
l_cl = ldbc_from_sphi(ar.pn_breakdown["total"][sel]) \
    + rng.normal(0.0, 0.5, int(sel.sum()))
cl = fit_closed_loop(f_cl, l_cl)
print(f"{'parameter':30s}{'true':>12s}{'fitted':>12s}")
print(f"{'loop UGB [kHz]':30s}{ar.loop.f_ugb / 1e3:12.0f}"
      f"{cl.f_ugb / 1e3:12.0f}")
print(f"{'closed-loop f_3db [kHz]':30s}{'(meas.)':>12s}"
      f"{cl.f_3db / 1e3:12.0f}")
i200k = np.searchsorted(ar.f, 2e5)
print(f"{'in-band L [dBc/Hz]':30s}"
      f"{ldbc_from_sphi(ar.pn_breakdown['total'][i200k]):12.1f}"
      f"{cl.inband_dbchz:12.1f}")
print(f"{'peaking [dB]':30s}{'(meas.)':>12s}{cl.peaking_db:12.1f}")
print(f"{'skirt L(1M) AS SEEN [dBc/Hz]':30s}{'(bound)':>12s}"
      f"{cl.osc.pn_dbchz:12.1f}")
print(f"template residual {cl.residual_db_rms:.2f} dB rms")
print("two honest limits of a single PN curve, both by design here:\n"
      " * no visible peaking (sources fill the |H| peak) -> PM is NOT "
      "readable from\n   a total-noise plot; measure the loop transfer "
      "with injection instead;\n * the skirt mixes the VCO with in-band "
      "tails -> the skirt triple is an upper\n   bound on the VCO.  "
      "attribute_budget (below) splits sources with a model.")

# --------------------------------------------------- 3. budget attribution
print("\n=== 3. attribute_budget: what is over budget on this chip? ===")
sick = presets.spll_frac_52m_6p253g()
sick.cfg.ref_pn_dbchz = -150.0          # reference 10 dB hot (in-band group)
sick.cfg.osc.pn_dbchz = -114.0          # VCO 4 dB worse (out-of-band skirt)
ar_sick = sick.analyze()
sel2 = (ar_sick.f >= 3e3) & (ar_sick.f <= 40e6)
f_chip = ar_sick.f[sel2]
l_chip = ldbc_from_sphi(ar_sick.pn_breakdown["total"][sel2]) \
    + rng.normal(0.0, 0.3, int(sel2.sum()))

nominal = presets.spll_frac_52m_6p253g()
att = attribute_budget(nominal, f_chip, l_chip)
print("sources are clustered into shape-identifiable GROUPS first — a "
      "single PN curve\ncannot separate reference from divider from kT/C "
      "(all flat-through-H);\nNNLS factors per group (1.0 = on budget):")
for gn, a in sorted(att.factors.items(), key=lambda kv: -kv[1]):
    print(f"  x{a:6.2f} ({att.factors_db[gn]:+5.1f} dB)  {'+'.join(gn)}")
print("flagged:", "; ".join(att.notes))
print(f"attribution residual {att.residual_db_rms:.2f} dB rms")
print("ground truth: ref +10 dB, VCO +4 dB.  The VCO group reads its own "
      "excess\ndirectly; the reference excess appears DILUTED into its "
      "flat-through-H group\n(ref is a minority share of the group's power, "
      "so a x10 member excess reads\nas ~+2 dB on the group) — the honest "
      "identifiability limit of one curve;\nseparating members needs "
      "conditional measurements (another fref or N).")

# ------------------------------------------------------------------ plot
fig, (axl, axr) = plt.subplots(1, 2, figsize=(12.5, 4.8))
axl.semilogx(f_csv, l_csv, ".", ms=3, alpha=0.5, label="measurement (synth)")
basis = (lee.k[0] / f_csv**3 + lee.k[1] / f_csv**2 + lee.k[2])
axl.semilogx(f_csv, ldbc_from_sphi(basis), "r", lw=1.8, label="Leeson fit")
axl.set_title("free-running VCO fit")
axl.set_xlabel("offset [Hz]")
axl.set_ylabel("L(f) [dBc/Hz]")
axl.legend()
axl.grid(alpha=0.3, which="both")

axr.semilogx(f_chip, l_chip, ".", ms=3, alpha=0.4, color="gray",
             label='"silicon" measurement')
tot_nom = np.interp(np.log10(f_chip), np.log10(ar.f),
                    ar.pn_breakdown["total"])
axr.semilogx(f_chip, ldbc_from_sphi(tot_nom), "C0", lw=1.5,
             label="nominal budget")
bd_nom = nominal.analyze().pn_breakdown
fit_s = sum(att.factors[gn]
            * sum(np.interp(np.log10(f_chip), np.log10(ar.f), bd_nom[n])
                  for n in gn)
            for gn in att.factors)
axr.semilogx(f_chip, ldbc_from_sphi(fit_s), "r--", lw=1.8,
             label="NNLS-rescaled budget")
axr.set_title("budget attribution: ref +6 dB, VCO +4 dB")
axr.set_xlabel("offset [Hz]")
axr.legend(fontsize=8)
axr.grid(alpha=0.3, which="both")
fig.tight_layout()
fig.savefig(f"{OUT}/ex16_pn_fitting.png", dpi=130)
print(f"\nplot saved to {OUT}/ex16_pn_fitting.png")
