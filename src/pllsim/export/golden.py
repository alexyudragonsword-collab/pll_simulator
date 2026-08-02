"""Golden-vector generation.

RTL vectors: stimulus + expected outputs as $readmemh hex files, produced by
the bit-true Python models (core.deltasigma Mash*) and the fixed-point
mirrors (fixedpoint.DlfFx / SignSignLmsFx / FtlFx / BandSelectFx / FllFx).
Comparison in iverilog is ZERO tolerance.

RNM vectors: per-cycle CSV from golden RNM engines that replicate the
exported wreal semantics exactly (impulse-only loop filter update) while
reusing the same Python objects; asserted against simulate() in tests.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

from ..core.deltasigma import Efm1, Mash11, Mash111
from .fixedpoint import BandSelectFx, DlfFx, FixedCoeff, FllFx, FtlFx, SignSignLmsFx


def to_hex(value: int, width_bits: int) -> str:
    """Two's-complement hex of `value` in width_bits."""
    mask = (1 << width_bits) - 1
    return format(value & mask, f"0{(width_bits + 3) // 4}x")


def write_hex(path: Path, values, width_bits: int) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(to_hex(int(v), width_bits) for v in values) + "\n")
    return path


def _frac_stimulus(bits: int, frac0: int, n: int, rng: np.random.Generator):
    """Constant segment, then random walks and steps — exercises the state."""
    fr = np.full(n, frac0, dtype=np.int64)
    third = n // 3
    fr[third:2 * third] = frac0 + rng.integers(-(1 << (bits - 8)),
                                               1 << (bits - 8), third)
    fr[2 * third:] = rng.integers(0, 1 << bits, n - 2 * third)
    return np.clip(fr, 0, (1 << bits) - 1)


def mash_vectors(kind: str, bits: int, frac0: int, n: int, outdir: Path,
                 seed: int = 1):
    """Returns dict of written files for a MASH block."""
    rng = np.random.default_rng(seed)
    fr = _frac_stimulus(bits, frac0, n, rng)
    mod = {"efm1": Efm1, "mash11": Mash11, "mash111": Mash111}[kind](bits)
    ys, res = [], []
    for f in fr:
        ys.append(mod.step(int(f)))
        res.append(mod._sum_y * mod.mod - mod._sum_frac)
    ywidth = {"efm1": 1, "mash11": 3, "mash111": 4}[kind]
    return {
        "stim": write_hex(outdir / f"{kind}_frac.hex", fr, bits),
        "exp_y": write_hex(outdir / f"{kind}_y.hex", ys, ywidth),
        "exp_res": write_hex(outdir / f"{kind}_res.hex", res, bits + 4),
        "n": n, "ywidth": ywidth,
    }


def dlf_vectors(sh_a: int, sh_r: int, sh_iir: tuple[int, ...], w: int,
                n: int, outdir: Path, seed: int = 2):
    rng = np.random.default_rng(seed)
    e = rng.integers(-(1 << 16), 1 << 16, n)
    mk = lambda s: FixedCoeff(2.0 ** (-s))
    fx = DlfFx(mk(sh_a), mk(sh_r), tuple(mk(s) for s in sh_iir))
    y = [fx.step(int(v)) for v in e]
    return {"stim": write_hex(outdir / "dlf_e.hex", e, w),
            "exp": write_hex(outdir / "dlf_y.hex", y, w), "n": n}


def sslms_vectors(w_err: int, f_gain: int, w_gain: int, sh_mu: int,
                  sh_muf: int, sh_ema: int, gear_n: int, n: int,
                  outdir: Path, seed: int = 3):
    rng = np.random.default_rng(seed)
    # correlated err/reg plus noise: converging-like stimulus
    reg = rng.integers(-(1 << 12), 1 << 12, n)
    err = (reg * 3 // 7) + rng.integers(-(1 << 12), 1 << 12, n)
    fx = SignSignLmsFx(f_gain, FixedCoeff(2.0 ** (-sh_mu)), sh_ema,
                       gear_shift_n=gear_n,
                       mu_final=FixedCoeff(2.0 ** (-sh_muf)))
    g = [fx.step(int(a), int(b)) for a, b in zip(err, reg)]
    return {"stim_err": write_hex(outdir / "sslms_err.hex", err, w_err),
            "stim_reg": write_hex(outdir / "sslms_reg.hex", reg, w_err),
            "exp": write_hex(outdir / "sslms_gain.hex", g, w_gain), "n": n}


def ftl_vectors(w_dac: int, mu: int, gear_n: int, mu_f: int, n: int,
                outdir: Path, seed: int = 4):
    rng = np.random.default_rng(seed)
    pos = rng.integers(0, 2, n)
    zero = (rng.integers(0, 8, n) == 0).astype(int)
    fx = FtlFx(mu=mu, gear_n=gear_n, mu_f=mu_f)
    code = [fx.step(bool(p), bool(z)) for p, z in zip(pos, zero)]
    stim = (pos << 1) | zero          # bit1 = drift_pos, bit0 = drift_zero
    return {"stim": write_hex(outdir / "ftl_drift.hex", stim, 2),
            "exp": write_hex(outdir / "ftl_code.hex", code, w_dac), "n": n}


def bandselect_vectors(n_bands: int, target: int, band_true: int,
                       band_step_counts: int, w_cnt: int, w_band: int,
                       outdir: Path, seed: int = 5):
    """Feeds measured counts consistent with a monotonic band->freq map."""
    rng = np.random.default_rng(seed)
    fx = BandSelectFx(n_bands, target)
    meas, bands, dones = [], [], []
    guard = 0
    while not fx.done and guard < 2 * n_bands:
        m = target + (fx.band - band_true) * band_step_counts \
            + int(rng.integers(-2, 3))
        b, d = fx.observe(m)
        meas.append(m)
        bands.append(b)
        dones.append(int(d))
        guard += 1
    return {"stim": write_hex(outdir / "bsel_meas.hex", meas, w_cnt),
            "exp_band": write_hex(outdir / "bsel_band.hex", bands, w_band),
            "exp_done": write_hex(outdir / "bsel_done.hex", dones, 1),
            "n": len(meas)}


def fll_vectors(window: int, n_target_counts: int, th_eng: int, th_rel: int,
                n_cyc_nom: int, n: int, outdir: Path, seed: int = 6):
    """Frequency ramp toward lock, then noise around it: engage->release."""
    rng = np.random.default_rng(seed)
    # start 3 counts/cycle off, ramp to 0 over first half, then jitter
    off = np.linspace(3.0, 0.0, n // 2)
    off = np.concatenate([off, np.zeros(n - n // 2)])
    cyc = n_cyc_nom + np.round(off).astype(int) \
        + (rng.integers(0, 4, n) == 0).astype(int) \
        - (rng.integers(0, 4, n) == 0).astype(int)
    fx = FllFx(window, n_target_counts, th_eng, th_rel)
    eng, ferr = [], []
    for c in cyc:
        e, f = fx.step(int(c))
        eng.append(int(e))
        ferr.append(f)
    return {"stim": write_hex(outdir / "fll_cycles.hex", cyc, 8),
            "exp_eng": write_hex(outdir / "fll_eng.hex", eng, 1),
            "exp_ferr": write_hex(outdir / "fll_ferr.hex", ferr, 21),
            "n": n}
