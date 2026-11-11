"""Example 22: hand a SerDes link simulator the clock it will actually run on.

A link simulator models its transmit clock as white random jitter plus one
sinusoidal tone, because that is what a jitter spec sheet says.  A PLL does
not make that clock: it makes 1/f^3 and 1/f^2 near the carrier, a flat
in-band floor where the reference and the detector dominate, and spurs at
the reference and fractional offsets.  A CDR is a high-pass to that jitter,
so two clocks with the same 200 fs RMS leave very different residues behind
it -- which is the question the link simulator cannot answer from one number.

The answer is a file, not an import.  This example writes the seven JSSC
benchmark anchors of ex14 as clock phase-noise profiles -- the carrier, the
total L(f) on a log-uniform grid from 100 Hz to f0/2, the analytic spur
table and a provenance line -- and reads each one back to show that what
the consumer integrates is what the model reported.  Those seven YAML files
are the ones Halo_Serdes ships in its data/clock_profiles/.

Two numbers per clock are printed on purpose.  The jitter over the paper's
integration band is the figure the benchmark is anchored on; the jitter over
the whole profile, 100 Hz to f0/2, is what a consumer integrating the file
end to end will see, and for the sampled-loop architectures (ADPLL, ILCM,
MDLL) it is much larger, because their z-domain models keep lobes above
fref that a log grid at 60 points per decade only roughly resolves.  That
gap is a property of the clock, not of the file -- and it is the reason the
file carries the curve rather than a jitter number.

The last part writes an eighth file for a different consumer: the Wu'19
loop retuned to 6.048 GHz and multiplied x10 to a 60.48 GHz LO, which is
what the 60 GHz transceiver simulator mmw60_trx asked for (issue #71).
"""
import math
import os

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from pllsim import presets
from pllsim.core.jitter import integrate_pn
from pllsim.export.clock_profile import (
    default_source,
    profile_grid,
    read_clock_profile,
    write_clock_profile,
)
from pllsim.guiutil import make_pll

OUT = os.path.join(os.path.dirname(__file__), "out")
PROFILES = os.path.join(OUT, "clock_profiles")
os.makedirs(PROFILES, exist_ok=True)

# the seven literature anchors of ex14 (parts 1-6; Markulic twice)
BENCH = [
    "bench_dartizio23_adpllbb_500m_9p2515g",
    "bench_markulic16_sspll_40m_10p24g",
    "bench_markulic16_sspll_frac_40m_10p25g",
    "bench_wu19_spll_frac_52m_6p253g",
    "bench_dadalt03_cppll_311m_2p488g",
    "bench_helal09_ilcm_50m_3p2g",
    "bench_elshazly13_mdll_375m_1p5g",
]


def jitter_fs_of(profile: dict, f1: float, f2: float) -> float:
    """What a consumer computes from the file alone: L(f) -> S_phi -> rad -> s."""
    f = np.asarray(profile["f_hz"])
    s_phi = 2.0 * 10.0 ** (np.asarray(profile["l_dbc_hz"]) / 10.0)
    return 1e15 * math.sqrt(integrate_pn(f, s_phi, f1, f2)) / (2 * math.pi * profile["f0_hz"])


print(f"{'preset':40s}{'f0 [GHz]':>9s}{'pts':>5s}{'spurs':>6s}"
      f"{'band jitter':>13s}{'file jitter':>13s}{'100Hz..f0/2':>13s}")
rows = []
curves = {}
for name in BENCH:
    pll = getattr(presets, name)()
    # the profile spans 100 Hz..f0/2 and the exporter does not extrapolate:
    # analyse on the profile grid and the file carries the model verbatim
    ar = pll.analyze(f=profile_grid(pll.cfg.fout))
    path = write_clock_profile(ar, os.path.join(PROFILES, f"{name}.yaml"),
                               source=default_source(name), fref=pll.cfg.fref)
    prof = read_clock_profile(path)
    lo, hi = ar.int_band
    j_file = jitter_fs_of(prof, lo, hi)
    j_full = jitter_fs_of(prof, 100.0, 0.5 * prof["f0_hz"])
    rows.append((name, path, ar.jitter_fs, j_file, j_full))
    curves[name] = (np.asarray(prof["f_hz"]), np.asarray(prof["l_dbc_hz"]))
    print(f"{name:40s}{ar.f0 / 1e9:9.4f}{len(prof['f_hz']):5d}{len(prof['spurs']):6d}"
          f"{ar.jitter_fs:13.3f}{j_file:13.3f}{j_full:13.1f}")
    # a profile that does not integrate back to the model's number is a
    # broken export, not a table entry
    if not math.isclose(j_file, ar.jitter_fs, rel_tol=1e-6):
        raise SystemExit(f"{name}: profile integrates to {j_file:.4f} fs, "
                         f"model reported {ar.jitter_fs:.4f} fs")

print(f"\n{len(rows)} profiles written to {PROFILES}/")
print("band jitter = the model over its own integration band; file jitter = the "
      "same band\nintegrated from the YAML; 100Hz..f0/2 = the whole profile, "
      "which is what a consumer\nintegrating the file end to end sees.")

# ------------------------------------------------- after a x N multiplier
# mmw60_trx (issue #71) builds a 60.48 GHz LO as a PLL followed by an integer
# multiplier, and asked for topology B: N = 10, so the PLL sits at 6.048 GHz.
# The Wu'19 anchor is designed at 6.253 GHz with its VCO centred at 6.2 GHz;
# 6.048 GHz needs -2.53 V of tuning from there, past the +/-1.5 V a single
# varactor band spans, so the VCO is recentred too (82.16 fs either way).
#
# Note the frequency plan, not the model: 60.48 GHz / 52 MHz = 15120/13, so
# for every integer N the divider lands on a k/13 fraction and the first-
# order fractional tone sits at fref/13 = 4 MHz (-63.7 dBc here, -43.7 x10).
#
# FLOOR and REJECTION are PLACEHOLDERS chosen for this example, not measured
# and not taken from any source; the exporter has no defaults for them on
# purpose.  -160 dBc/Hz sits 26 dB under the PLL's own far-out level x N^2
# (-134 dBc/Hz), so below f_in/2 the curve is the PLL's; above f_in/2 the
# file is this number alone, and a consumer that integrates there should
# replace it with its own.  Regenerate with other values from the shell:
#   pllsim export bench_wu19_spll_frac_52m_6p253g --set fout=6.048G \
#     --set osc.f0=6.048G --clock-profile x10.yaml --multiply-by 10 \
#     --floor-dbchz=-150 --spur-rejection-db 30
N_MULT, FLOOR, REJECTION = 10, -160.0, 40.0
x_name = "bench_wu19_spll_frac_x10_60p48g"
pll = make_pll("bench_wu19_spll_frac_52m_6p253g", {"fout": "6.048G", "osc.f0": "6.048G"})
ar = pll.analyze(f=profile_grid(pll.cfg.fout))
x_path = write_clock_profile(
    ar, os.path.join(PROFILES, f"{x_name}.yaml"),
    source=(default_source("bench_wu19_spll_frac_52m_6p253g")
            + f", retuned to fout=6.048G and osc.f0=6.048G, x{N_MULT} to 60.48 GHz;"
            f" floor_dbchz={FLOOR:g} and spur_rejection_db={REJECTION:g} are"
            " placeholders, not measured or sourced"),
    fref=pll.cfg.fref, multiply_by=N_MULT, floor_dbchz=FLOOR,
    spur_rejection_db=REJECTION)
xp = read_clock_profile(x_path)
lo, hi = ar.int_band
j_x = jitter_fs_of(xp, lo, hi)
tone = max(xp["spurs"], key=lambda r: r["dbc"] if r["f_hz"] < xp["f_in_hz"] else -999)
print(f"\nx{N_MULT}: {x_name}.yaml  f0 {xp['f0_hz'] / 1e9:.4f} GHz from "
      f"{xp['f_in_hz'] / 1e9:.4f} GHz, {len(xp['f_hz'])} points to "
      f"{xp['f0_hz'] / 2e9:.3g} GHz, floor-only above {xp['f_in_hz'] / 2e9:.4g} GHz")
print(f"  jitter over {lo / 1e3:.0f} kHz-{hi / 1e6:.0f} MHz: {j_x:.3f} fs "
      f"(PLL alone {ar.jitter_fs:.3f} fs: x N keeps seconds, the floor adds)")
print(f"  worst PLL spur after x{N_MULT}: {tone['dbc']:.1f} dBc at "
      f"{tone['f_hz'] / 1e6:.4g} MHz; harmonic leakage {-REJECTION:g} dBc at f_in")
# the floor sits 26 dB under the PLL in this band, so seconds barely move;
# a gap here means the multiplier law broke, not that the floor is large
if not math.isclose(j_x, ar.jitter_fs, rel_tol=1e-3):
    raise SystemExit(f"x{N_MULT}: {j_x:.4f} fs against the PLL's {ar.jitter_fs:.4f} fs")
curves[f"{x_name} (60.48G)"] = (np.asarray(xp["f_hz"]), np.asarray(xp["l_dbc_hz"]))

fig, ax = plt.subplots(figsize=(9, 5))
for name, (f, l_dbc) in curves.items():
    short = name.replace("bench_", "").split("_")[0]
    multiplied = "(" in name
    ax.semilogx(f, l_dbc, lw=1.0, ls="--" if multiplied else "-",
                label=f"{short} x{N_MULT} at 60.48G" if multiplied else short)
ax.set_xlabel("offset [Hz]")
ax.set_ylabel("L(f) [dBc/Hz]")
ax.set_title("Clock phase-noise profiles as read back from the YAML files")
ax.grid(alpha=0.3, which="both")
ax.legend(fontsize=8, ncol=2)
fig.tight_layout()
fig.savefig(os.path.join(OUT, "ex22_clock_profiles.png"), dpi=130)
print(f"plot: {OUT}/ex22_clock_profiles.png")
