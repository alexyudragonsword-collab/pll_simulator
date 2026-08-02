"""Example 17: two-point GMSK modulation and EVM (Markulic-style TX).

A PLL becomes a phase/frequency transmitter by summing the data at two
points: the FCW/DTC path (lowpass through the loop) and the direct DCO/VCO
push (highpass).  Matched gains sum to 1 at every offset, so the data rate
can exceed the loop bandwidth by orders of magnitude; a direct-path gain
error eps leaves eps * (highpassed modulation) as the error trajectory —
THE spec that two-point calibration (Markulic JSSC'16's self-calibration)
must meet.

Part 1  digital two-point: ADPLL (TDC), 10 Mb/s GMSK on a 10.05 GHz
        carrier, fref = 100 MHz, loop BW ~ 1 MHz.  Matched EVM is noise-
        limited (~0.7%, -43 dB); the EVM-vs-mismatch curve is the design
        chart for the direct-path DAC gain spec.
Part 2  analog two-point: fractional-N SSPLL (Markulic'16 class, ex14
        config), DTC lowpass point + VCO-bank direct point, 10.25 GHz.
        Matched EVM at 2.5 Mb/s lands in the paper's -40 dB class.

Honest engine limit, stated up front: the time-domain engines advance one
step per reference cycle, so the modulation is sampled at fref/Rb samples
per symbol and the *comparison* against the continuous ideal carries a
discretization floor that scales as 1/sps (measured: -33.5 dB at 4 s/sym,
-50 dB at 16 s/sym).  Hardware is continuous-time and does not have this
floor — quote matched-EVM numbers only at >= 8 samples per symbol.
"""
import os

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from pllsim import presets
from pllsim.modulation import evm, gmsk_trajectory, prbs


def _markulic(frac):
    """Markulic'16-class fractional SSPLL (the ex14 benchmark preset)."""
    return presets.bench_markulic16_sspll_frac_40m_10p25g()

OUT = os.path.join(os.path.dirname(__file__), "out")
os.makedirs(OUT, exist_ok=True)

N, SETTLE = 200_000, 60_000
ERRS = (0.0, 0.01, 0.02, 0.05, 0.10)


def run(pll, fref, rb, dp_gain, seed):
    bits = prbs(int((N - SETTLE) * rb / fref) - 20, seed=7)
    fdev, _ = gmsk_trajectory(bits, fref, rb)
    mod = np.zeros(N)
    mod[SETTLE:SETTLE + fdev.size] = fdev
    ideal = 2.0 * np.pi * np.cumsum(mod) / fref
    sim = pll.simulate(N, seed=seed, mod_freq=mod, mod_dp_gain=dp_gain)
    return evm(sim.phase_err_out[SETTLE + 4000:], ideal[SETTLE + 4000:]), sim


# ---------------------------------------------------------------- Part 1
print("=== Part 1: ADPLL (TDC) digital two-point, 10 Mb/s GMSK @ 10.05 GHz ===")
print(f"{'direct-path gain error':>26s}{'EVM [%]':>10s}{'EVM [dB]':>10s}")
evm_adpll = []
for eps in ERRS:
    e, _ = run(presets.adpll_100m_10g(), 100e6, 10e6, 1.0 + eps, seed=1)
    evm_adpll.append(e)
    print(f"{100 * eps:25.0f}%{e['evm_pct']:10.2f}{e['evm_db']:10.1f}")
print("matched two-point is noise-limited; the loop BW (~1 MHz) plays no "
      "role at 10 Mb/s\n— the whole point of two-point modulation.")

# ---------------------------------------------------------------- Part 2
print("\n=== Part 2: fractional-N SSPLL analog two-point (Markulic'16 class) ===")
print("2.5 Mb/s GMSK on the 10.25 GHz fractional carrier (16 samples/symbol):")
print(f"{'direct-path gain error':>26s}{'EVM [%]':>10s}{'EVM [dB]':>10s}")
evm_sspll = []
for eps in ERRS:
    e, sim2 = run(_markulic(0.2503), 40e6, 2.5e6, 1.0 + eps, seed=2)
    evm_sspll.append(e)
    print(f"{100 * eps:25.0f}%{e['evm_pct']:10.2f}{e['evm_db']:10.1f}")
print("published Markulic'16: -40.5 dB EVM (10 Mb/s GMSK, after background "
      "gain cal)\n— the matched model lands in the same class; at 10 Mb/s "
      "the 4-samples/symbol\ncomparison floor (-33.5 dB) masks it, see the "
      "docstring.")

# ------------------------------------------------------------------ plot
fig, (axl, axr) = plt.subplots(1, 2, figsize=(12, 4.6))
x = [100 * e for e in ERRS]
axl.plot(x, [e["evm_pct"] for e in evm_adpll], "o-",
         label="ADPLL 10 Mb/s (10 s/sym)")
axl.plot(x, [e["evm_pct"] for e in evm_sspll], "s-",
         label="SSPLL frac 2.5 Mb/s (16 s/sym)")
axl.set_xlabel("direct-path gain error [%]")
axl.set_ylabel("EVM [%]")
axl.set_title("two-point mismatch is THE EVM spec")
axl.grid(alpha=0.3)
axl.legend()

bits = prbs(60, seed=7)
fdev, ph = gmsk_trajectory(bits, 40e6, 2.5e6)
tt = np.arange(fdev.size) / 40e6 * 1e6
axr.plot(tt, fdev / 1e6, "C0", label="freq trajectory")
axr.set_xlabel("time [us]")
axr.set_ylabel("freq deviation [MHz]", color="C0")
ax2 = axr.twinx()
ax2.plot(tt, ph / np.pi, "C1", alpha=0.7, label="phase / pi")
ax2.set_ylabel("phase [pi rad]", color="C1")
axr.set_title("GMSK BT=0.5: +/- pi/2 per symbol")
axr.grid(alpha=0.3)
fig.tight_layout()
fig.savefig(f"{OUT}/ex17_two_point_mod.png", dpi=130)
print(f"\nplot saved to {OUT}/ex17_two_point_mod.png")
