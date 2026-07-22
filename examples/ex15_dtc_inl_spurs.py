"""Example 15: DTC INL -> fractional spurs — predict, validate, calibrate.

Fractional spurs in DTC-based loops are deterministic, not statistical: the
EFM/MASH residual is periodic in the accumulator, so DTC code quantization,
INL and residual gain error all turn into coherent tones at
f_spur = fold(k*frac)*fref.  `pllsim.core.dtcspurs` replays the bit-true
code sequence through the DTC transfer and predicts each tone through the
loop's DTC noise NTF; every fractional analyze() now carries the table in
`spurs_analytic["frac_spur@..."]`.

Three questions answered here (Wu JSSC'19 sampling-PLL config from ex14):

1. VALIDATE — does the prediction match the time domain?  (noise-free sim:
   within ~1.5 dB tone by tone; with noise on, weak tones sink below the
   local noise floor and find_spurs() readings become floor-limited.)
2. WORST CHANNEL — which fractional channel is worst?  Near-integer
   channels: the beat frac*fref falls inside the loop bandwidth where
   |NTF| ~ 1.  The published "worst spur < -64 dBc" class corresponds to
   ~30-50 fs of post-linearization INL — the real spec behind a "highly
   linear DTC".
3. CALIBRATE — the background sign-sign LMS (gain) also drags in-band INL
   tones down a few dB by tracking the beat; the LUT INL calibration
   (CPPLL, ex02 wiring) removes the INL mechanism itself.
"""
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from pllsim import presets
from pllsim.core.dtcspurs import dtc_spur_table

OUT = os.path.join(os.path.dirname(__file__), "out")
os.makedirs(OUT, exist_ok=True)

INL_SIN = (500e-15, 1.0, 0.3)      # 500 fs pk sine INL — deliberately coarse


def wu_pll(frac=0.2503, inl=(), eps=0.0):
    pll = presets.spll_frac_52m_6p253g()
    c = pll.cfg
    if frac != 0.2503:             # retune the channel, keep everything else
        c.fout = (120 + frac) * c.fref
        c.frac.frac = frac
    c.frac.dtc.inl_sin = inl
    c.frac.dtc.gain_error_residual = eps
    return pll


# ---------------------------------------------------- 1. validate vs sim
print("=== 1. prediction vs noise-free time domain (500 fs sine INL) ===")
pll = wu_pll(inl=INL_SIN)
ar = pll.analyze()
pred = {round(float(k.split("@")[1][:-2])): v
        for k, v in ar.spurs_analytic.items() if k.startswith("frac_spur")}
sim = pll.simulate(150_000, seed=5, noise=False, calibration=False)
meas = {round(f): v for f, v in sim.spurs_fft.items() if np.isfinite(v)}
print(f"{'offset':>12s}{'predicted':>12s}{'sim (dBc)':>12s}")
for off in sorted(pred):
    print(f"{off / 1e3:11.1f}k{pred[off]:12.1f}{meas.get(off, float('nan')):12.1f}")

sim_n = pll.simulate(150_000, seed=5, noise=True, calibration=True)
meas_n = {round(f): v for f, v in sim_n.spurs_fft.items() if np.isfinite(v)}
main = 62400
print(f"\nwith noise + background LMS: in-band tone @62.4 kHz reads "
      f"{meas_n.get(main, float('nan')):.1f} dBc\n"
      "(the gain LMS partially tracks the in-band INL beat — a real, "
      "documented effect;\n weak out-of-band tones sink below the local "
      "noise floor and become unmeasurable.)")

# ------------------------------------------------- 2. worst-channel sweep
print("\n=== 2. worst channel: spur vs fractional offset (INL 50 fs) ===")
fracs = [0.0013, 0.0053, 0.0161, 0.0503, 0.1253, 0.2503, 0.3753, 0.4703]
inl_wu = (50e-15, 1.0, 0.3)        # the "highly linear DTC" class
worst = []
for fr in fracs:
    p = wu_pll(frac=fr, inl=inl_wu, eps=0.002)
    a = p.analyze()
    tab = {k: v for k, v in a.spurs_analytic.items()
           if k.startswith("frac_spur")}
    w = max(tab.values()) if tab else float("nan")
    worst.append(w)
    print(f"  frac={fr:7.4f}  beat={fr * 52e6 / 1e3:9.1f} kHz  "
          f"worst spur = {w:7.1f} dBc")
print("published Wu'19 class: worst fractional spur < -64 dBc — reproduced "
      "with 50 fs INL:\nnear-integer channels are worst (beat inside the "
      "loop BW, |NTF| ~ 1).")

# ------------------------------------------------ 3. LUT INL calibration
print("\n=== 3. LUT INL calibration (CPPLL wiring, ex02 config) ===")
from pllsim.calibration.lms import LUTCal           # noqa: E402

INL_BIG = (2e-12, 3.0, 0.7)        # 2 ps pk, 3 cycles — an uncorrected DTC
cp = presets.cppll_frac_38p4m_6g()
cp.cfg.frac.dtc.inl_sin = INL_BIG
sim_no = cp.simulate(200_000, seed=7, dtc_gain_init_error=0.02)
cp2 = presets.cppll_frac_38p4m_6g()
cp2.cfg.frac.dtc.inl_sin = INL_BIG
cp2.cfg.frac.dtc_lut_cal = LUTCal(k=32, lo=-2.0, hi=2.0, mu=1e-16)
sim_lut = cp2.simulate(200_000, seed=7, dtc_gain_init_error=0.02)


def worst_meas(s):
    v = [x for x in s.spurs_fft.values() if np.isfinite(x)]
    return max(v) if v else float("nan")


print(f"2 ps INL, gain LMS only : jitter {sim_no.jitter_fs:7.1f} fs, "
      f"worst measured spur {worst_meas(sim_no):6.1f} dBc")
print(f"2 ps INL, + 32-bin LUT  : jitter {sim_lut.jitter_fs:7.1f} fs, "
      f"worst measured spur {worst_meas(sim_lut):6.1f} dBc")
print("(the LUT needs loop noise as dither for its sign updates — that is "
      "the normal\n operating condition; see test_dtc_cal.py for the "
      "bounded-LUT guarantee.)")

# ------------------------------------------------------------------ plot
fig, (axl, axr) = plt.subplots(1, 2, figsize=(12, 4.6))
offs = sorted(pred)
x = np.arange(len(offs))
axl.bar(x - 0.18, [pred[o] for o in offs], 0.36, label="predicted")
axl.bar(x + 0.18, [meas.get(o, np.nan) for o in offs], 0.36,
        label="time domain (noise-free)")
axl.set_xticks(x)
axl.set_xticklabels([f"{o / 1e3:.0f}k" for o in offs])
axl.set_ylabel("spur [dBc]")
axl.set_xlabel("offset")
axl.set_title("500 fs INL: prediction vs simulation")
axl.legend()
axl.grid(alpha=0.3)

beats = [fr * 52e6 for fr in fracs]
axr.semilogx(beats, worst, "o-", label="predicted worst spur (50 fs INL)")
axr.axhline(-64, color="r", ls="--", label="Wu'19 spec class (-64 dBc)")
axr.axvline(0.62e6, color="gray", ls=":", label="loop UGB")
axr.set_xlabel("fractional beat  frac*fref  [Hz]")
axr.set_ylabel("worst spur [dBc]")
axr.set_title("worst channel is near the integer boundary")
axr.legend(fontsize=8)
axr.grid(alpha=0.3, which="both")
fig.tight_layout()
fig.savefig(f"{OUT}/ex15_dtc_inl_spurs.png", dpi=130)
print(f"\nplot saved to {OUT}/ex15_dtc_inl_spurs.png")
