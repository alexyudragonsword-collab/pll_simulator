"""Example 18: automatic architecture selection against a requirement.

`pllsim.selector` instantiates all seven architectures from technology-
class templates at the requested frequency plan, synthesizes each loop
(pllsim.synth), runs the linear model, and ranks them — with hard
infeasibilities excluded and the reason recorded.  It automates the first
whiteboard hour of a frequency-synthesis project; the winner is a
ready-to-simulate instance, not just a name.

Three procurement scenarios below.  The scores are linear-model: confirm
the shortlist in the time domain before committing (rep.best.pll is ready
for .simulate()).
"""
from pllsim.selector import Requirement, select

SCENARIOS = [
    ("wireline-class integer channel",
     Requirement(fref=100e6, fout=8e9, jitter_fs_max=120)),
    ("cellular-class fractional channel (Wu'19-like plan)",
     Requirement(fref=52e6, fout=(120 + 0.2503) * 52e6, jitter_fs_max=200,
                 int_band=(10e3, 10e6))),
    ("GMSK transmitter, moderate multiply, needs two-point TX",
     Requirement(fref=250e6, fout=3e9, jitter_fs_max=200, modulation=True)),
]

for name, req in SCENARIOS:
    rep = select(req)
    print("=" * 74)
    print(f"{name}: fref={req.fref / 1e6:g} MHz -> "
          f"fout={req.fout / 1e9:.4f} GHz, N={req.n:.4f} "
          f"({'fractional' if req.fractional else 'integer'}), "
          f"target < {req.jitter_fs_max:.0f} fs "
          f"[{req.int_band[0] / 1e3:.0f}k-{req.int_band[1] / 1e6:.0f}M]")
    print("=" * 74)
    print(rep.table())
    b = rep.best
    if b is not None:
        margin = 20.0 * (1.0 - b.jitter_fs / req.jitter_fs_max)
        print(f"\nrecommendation: {b.arch}  ({b.jitter_fs:.0f} fs, "
              f"{req.jitter_fs_max - b.jitter_fs:.0f} fs of margin)")
        if req.modulation and "no two-point" in "; ".join(b.notes):
            alts = [c for c in rep.candidates if c.feasible
                    and c.jitter_fs <= req.jitter_fs_max
                    and "no two-point" not in "; ".join(c.notes)]
            if alts:
                a = min(alts, key=lambda c: c.jitter_fs)
                print(f"modulation-ready alternative: {a.arch} "
                      f"({a.jitter_fs:.0f} fs)")
    else:
        close = min((c for c in rep.candidates if c.feasible),
                    key=lambda c: c.jitter_fs, default=None)
        print("\nno architecture meets the target with these technology "
              "classes;")
        if close:
            print(f"closest: {close.arch} at {close.jitter_fs:.0f} fs — "
                  "relax the target, improve the\noscillator class, or "
                  "raise fref.")
    print()

print("every ranked row is a live object: rep.best.pll.simulate(...) "
      "continues the flow.")
