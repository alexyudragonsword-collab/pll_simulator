"""Example 21: the three things a design review asks after the jitter number.

Monte Carlo answers "what is the yield".  It does not answer the three
questions that come first in a review, because none of them is a sample:

1. **Does it still work at SS/125C/0.9*VDD?**  A corner is a named,
   reproducible point, and `pllsim.corners` applies one without retuning the
   loop -- that is the whole point.  The bandwidth and phase margin move, and
   how far they move IS the result.  A design can pass MC and fail a corner.

2. **When does LOCK go high, and does it stay high?**  A frequency trajectory
   that "looks settled" is not a lock detector.  `blocks.lockdetect` is the
   asymmetric up/down counter that real silicon ships, and it reports the
   assert time, the fraction of the run in lock, and -- the number nobody
   plots -- how many times it dropped out afterwards.

3. **What happens when the PA pulls the tank?**  Injection pulling couples
   into the oscillator, not into the loop, so it reaches every architecture
   and the loop can only reject the part inside its own bandwidth.

Four figures: corner spread per architecture, the supply axis on its own,
lock-detector traces, and the pulling spur vs offset against Adler.
"""
import os

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from pllsim import corners, presets
from pllsim.blocks.lockdetect import LockDetectConfig

OUT = os.path.join(os.path.dirname(__file__), "out")
os.makedirs(OUT, exist_ok=True)

# ---------------------------------------------------- 1. the corner box
print("=== 1. corner sweep, no retuning ===")
ARCHS = ["cppll_19p2m_4p8g", "sspll_19p2m_4p8g", "spll_100m_8g",
         "adpll_100m_10g", "ilcm_250m_12g", "mdll_150m_2p4g"]
rows_by_arch = {}
for nm in ARCHS:
    rows = corners.corner_report(presets.ALL_PRESETS[nm]())
    rows_by_arch[nm] = rows
    worst = corners.worst_case(rows)
    ok = [r for r in rows if r.error is None]
    span = max(r.f_ugb_hz for r in ok) / max(min(r.f_ugb_hz for r in ok), 1e-30)
    print(f"{nm:22s} worst {worst.corner:14s} {worst.jitter_fs:7.1f} fs   "
          f"UGB spread {span:5.2f}x")

print()
print(corners.corner_table(rows_by_arch["cppll_19p2m_4p8g"]))

fig, ax = plt.subplots(figsize=(9, 4.5))
width = 0.15
names = [c.name for c in corners.STANDARD_CORNERS]
for i, cn in enumerate(names):
    vals = [next(r.jitter_fs for r in rows_by_arch[a] if r.corner == cn)
            for a in ARCHS]
    ax.bar(np.arange(len(ARCHS)) + (i - 2) * width, vals, width, label=cn)
ax.set_xticks(range(len(ARCHS)))
ax.set_xticklabels([a.split("_")[0] for a in ARCHS])
ax.set_ylabel("integrated jitter [fs]")
ax.set_title("Named corners, loop NOT retuned (that is the question being asked)")
ax.legend(fontsize=8)
ax.grid(alpha=0.3, axis="y")
fig.tight_layout()
fig.savefig(os.path.join(OUT, "ex21_corner_jitter.png"), dpi=130)

# ------------------------------------------- 2. the supply axis on its own
# vdd acts through the oscillator's own pushing figure, which is the only
# honest route: an oscillator states Hz/V, and a corner states a relative
# supply, so the two need a nominal in volts to meet.  A preset that has not
# characterised pushing comes back untouched rather than guessing.
print("\n=== 2. supply pushing (osc.pushing_hz_v = 5 MHz/V, 1.8 V part) ===")
pll = presets.cppll_19p2m_4p8g()
pll.cfg.osc.pushing_hz_v = 5e6
f0 = pll.cfg.osc.f0
sags = np.linspace(0.85, 1.15, 13)
shift = [corners.apply_corner(
    pll, corners.Corner("v", vdd=v, vdd_nominal_v=1.8)).cfg.osc.f0 - f0
    for v in sags]
for v, d in zip(sags[::4], shift[::4]):
    print(f"  vdd = {v:.2f} x 1.8 V   f0 {d / 1e6:+7.3f} MHz")

fig, ax = plt.subplots(figsize=(7, 3.6))
ax.plot(sags * 1.8, np.array(shift) / 1e6, "o-")
ax.set_xlabel("supply [V]")
ax.set_ylabel("free-running shift [MHz]")
ax.set_title("Corner.vdd through OscConfig.pushing_hz_v")
ax.grid(alpha=0.3)
fig.tight_layout()
fig.savefig(os.path.join(OUT, "ex21_supply_pushing.png"), dpi=130)

# ---------------------------------------------------- 3. the lock detector
print("\n=== 3. lock detector: assert time, and whether it holds ===")
fig, ax = plt.subplots(figsize=(9, 4))
for win_ps, hop in ((20.0, -60e6), (5.0, -60e6), (2.0, -60e6)):
    p = presets.cppll_19p2m_4p8g()
    p.cfg.lock_detect = LockDetectConfig(window_s=win_ps * 1e-12, count=64,
                                         down_weight=4)
    sim = p.simulate(120_000, seed=1, f_start_offset=hop)
    st = sim.extra["lock_detect"]
    lt = "never" if st.lock_time_s is None else f"{st.lock_time_s * 1e6:.1f} us"
    print(f"  window {win_ps:4.1f} ps, hop {hop / 1e6:+5.0f} MHz -> "
          f"lock at {lt:>8s}, in lock {st.lock_fraction * 100:5.1f}% of the "
          f"run, {st.n_unlock_events} drop-out(s) after asserting")
    ax.plot(sim.t * 1e6, sim.cal_traces["lock_detect"] + 0.0,
            lw=1.0, label=f"{win_ps:g} ps window, {hop / 1e6:+.0f} MHz hop")
ax.set_xlabel("t [us]")
ax.set_ylabel("LOCK")
ax.set_yticks([0, 1])
ax.set_title("An asymmetric counter: slow to assert, quick to drop -- a "
             "window near the loop's own error asserts once and falls out")
ax.legend(fontsize=8)
ax.grid(alpha=0.3)
fig.tight_layout()
fig.savefig(os.path.join(OUT, "ex21_lock_detect.png"), dpi=130)

# ------------------------------------------------- 4. injection pulling
# Adler's weak-pulling sideband is f_L/(2*df).  The aggressor couples into
# the tank, so the loop sees it as oscillator noise and rejects it with E(f)
# -- inside the bandwidth the spur is suppressed, outside it is bare.
print("\n=== 4. injection pulling vs offset ===")
p = presets.cppll_19p2m_4p8g()
f_l = 20e3                      # lock range: f0*(Iinj/Iosc)/(2Q)
p.cfg.osc.pull_lock_range_hz = f_l
f_ugb = p.analyze().loop.f_ugb
offsets = np.logspace(np.log10(0.06 * f_ugb), np.log10(60 * f_ugb), 40)
got, bare = [], []
for df in offsets:
    p.cfg.osc.pull_offset_hz = float(df)
    got.append(p.analyze().spurs_analytic.get("pull_spur", np.nan))
    bare.append(20 * np.log10(f_l / df / 2))
print(f"  f_UGB = {f_ugb / 1e3:.0f} kHz, f_L = {f_l / 1e3:.0f} kHz")
print(f"  at 0.06*UGB the loop buys {bare[0] - got[0]:.1f} dB; "
      f"at 60*UGB it buys {bare[-1] - got[-1]:.1f} dB")

fig, ax = plt.subplots(figsize=(7.5, 4.2))
ax.semilogx(offsets, bare, "--", label="Adler, open loop: f_L/(2*df)")
ax.semilogx(offsets, got, "o-", ms=3, label="through the loop's E(f)")
ax.axvline(f_ugb, color="gray", ls=":", label="UGB")
ax.set_xlabel("aggressor offset [Hz]")
ax.set_ylabel("pulling spur [dBc]")
ax.set_title("Pulling couples into the tank, so the loop rejects it in band")
ax.legend(fontsize=8)
ax.grid(alpha=0.3, which="both")
fig.tight_layout()
fig.savefig(os.path.join(OUT, "ex21_injection_pulling.png"), dpi=130)

# and the case that is not a spur at all
p.cfg.osc.pull_offset_hz = 0.5 * f_l
ar = p.analyze()
print(f"  inside the lock range: 'pull_spur' present = "
      f"{'pull_spur' in ar.spurs_analytic}")
for n in ar.notes:
    if "CAPTURE" in n.upper():
        print("  note:", n)

print(f"\nfigures written to {OUT}")
