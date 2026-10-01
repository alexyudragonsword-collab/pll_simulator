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

fig, ax = plt.subplots(figsize=(9, 5))
for name, (f, l_dbc) in curves.items():
    ax.semilogx(f, l_dbc, lw=1.0, label=name.replace("bench_", "").split("_")[0])
ax.set_xlabel("offset [Hz]")
ax.set_ylabel("L(f) [dBc/Hz]")
ax.set_title("Clock phase-noise profiles as read back from the YAML files")
ax.grid(alpha=0.3, which="both")
ax.legend(fontsize=8, ncol=2)
fig.tight_layout()
fig.savefig(os.path.join(OUT, "ex22_clock_profiles.png"), dpi=130)
print(f"plot: {OUT}/ex22_clock_profiles.png")
