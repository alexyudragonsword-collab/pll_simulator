"""Fit measured phase noise to model parameters (bench-data import).

Turns spectrum-analyzer / signal-source-analyzer exports into pllsim model
parameters, closing the loop between the noise budget and silicon:

* load_pn_csv        — read an (offset_hz, L_dBc/Hz) table (E5052/FSWP-style
                       exports: comma/semicolon/tab, headers and comment
                       lines skipped automatically)
* fit_leeson         — free-running oscillator: recover (pn_dbchz @ spot,
                       1/f^3 corner, floor), the OscConfig parameter triple
* fit_closed_loop    — locked spectrum: recover the in-band plateau, loop
                       UGB and peaking (damping) plus the oscillator triple,
                       by nonlinear least squares on a type-II closed loop
* attribute_budget   — given a PLL instance and a measurement, scale each
                       modeled noise source by a non-negative factor (NNLS)
                       to explain the measurement: sources with factor >> 1
                       are the ones over budget on silicon

All PSDs follow the package convention: S_phi DSB [rad^2/Hz], L = S/2.
"""
from __future__ import annotations

import io
from dataclasses import dataclass, field

import numpy as np
from scipy.optimize import nnls

TWOPI = 2.0 * np.pi


# ---------------------------------------------------------------- data IO
def load_pn_csv(path_or_buf, min_offset: float = 1.0) -> tuple[np.ndarray,
                                                               np.ndarray]:
    """Read (offset_hz, ldbc) pairs; skips headers, comments, blank lines."""
    if isinstance(path_or_buf, (str, bytes)):
        raw = open(path_or_buf, "r", errors="ignore").read()
    else:
        raw = path_or_buf.read()
    f, l = [], []
    for line in io.StringIO(raw):
        line = line.strip()
        if not line or line[0] in "#;%!\"'":
            continue
        for sep in (",", ";", "\t"):
            line = line.replace(sep, " ")
        parts = line.split()
        try:
            fo, ld = float(parts[0]), float(parts[1])
        except (ValueError, IndexError):
            continue                     # header / units line
        if fo >= min_offset and -400.0 < ld < 40.0:
            f.append(fo)
            l.append(ld)
    if len(f) < 4:
        raise ValueError("no parseable (offset, dBc/Hz) rows found")
    f_arr, l_arr = np.asarray(f), np.asarray(l)
    order = np.argsort(f_arr)
    return f_arr[order], l_arr[order]


def _sphi(ldbc: np.ndarray) -> np.ndarray:
    return 2.0 * 10.0 ** (np.asarray(ldbc) / 10.0)


def _ldbc(sphi: np.ndarray) -> np.ndarray:
    return 10.0 * np.log10(np.maximum(sphi, 1e-40) / 2.0)


# ---------------------------------------------------------------- Leeson
@dataclass
class LeesonFit:
    pn_dbchz: float          # L at pn_foffset (1/f^2 component)
    pn_foffset: float
    pn_f1f3: float           # 1/f^3 corner [Hz]
    pn_floor_dbchz: float
    residual_db_rms: float
    k: tuple = ()            # (k3, k2, floor) raw DSB coefficients

    def as_oscconfig_kwargs(self) -> dict:
        return dict(pn_dbchz=self.pn_dbchz, pn_foffset=self.pn_foffset,
                    pn_f1f3=self.pn_f1f3, pn_floor_dbchz=self.pn_floor_dbchz)


def fit_leeson(f: np.ndarray, ldbc: np.ndarray,
               pn_foffset: float = 1e6) -> LeesonFit:
    """Nonnegative LS of S = k3/f^3 + k2/f^2 + floor on relative error.

    Weighting by 1/S makes the fit relative (each decade counts equally),
    which is how phase-noise plots are read.
    """
    f = np.asarray(f, dtype=float)
    s = _sphi(ldbc)
    basis = np.stack([1.0 / f**3, 1.0 / f**2, np.ones_like(f)], axis=1)
    w = 1.0 / s
    coef, _ = nnls(basis * w[:, None], s * w)
    k3, k2, floor = coef
    fit = basis @ coef
    resid = float(np.sqrt(np.mean((_ldbc(fit) - _ldbc(s)) ** 2)))
    return LeesonFit(
        pn_dbchz=float(_ldbc(np.array([k2 / pn_foffset**2]))[0]),
        pn_foffset=pn_foffset,
        pn_f1f3=float(k3 / k2) if k2 > 0 else 0.0,
        pn_floor_dbchz=float(_ldbc(np.array([floor]))[0]) if floor > 0
        else -400.0,
        residual_db_rms=resid, k=(float(k3), float(k2), float(floor)))


# ------------------------------------------------------------ closed loop
@dataclass
class ClosedLoopFit:
    """What a single locked spectrum can actually tell you.

    Identifiable: the in-band plateau, the closed-loop corner (f_3db), the
    peaking (-> damping -> phase-margin estimate).  NOT identifiable in a
    well-balanced design: the true oscillator triple — the skirt of a good
    PLL is a mix of the oscillator and the in-band sources' rolloff tails,
    so `osc` is the Leeson fit of the skirt AS SEEN (an upper bound on the
    oscillator).  Use attribute_budget() with a design model to split
    sources.
    """
    f_3db: float             # closed-loop -3 dB corner (measured) [Hz]
    f_ugb: float             # UGB estimate via the 2nd-order template [Hz]
    zeta: float              # damping from peaking
    inband_dbchz: float      # flat in-band plateau L
    peaking_db: float        # max above plateau near the corner
    osc: LeesonFit           # skirt triple AS SEEN (upper bound on VCO)
    residual_db_rms: float   # descriptive: template vs data

    @property
    def pm_deg_est(self) -> float:
        """Damping -> phase-margin estimate (2nd-order relation)."""
        z = min(self.zeta, 10.0)
        val = np.sqrt(np.sqrt(1.0 + 4.0 * z**4) - 2.0 * z**2)
        if val < 1e-9:
            return 90.0
        return float(np.degrees(np.arctan(2.0 * z / val)))


def _type2_h(f: np.ndarray, fugb: float, zeta: float) -> np.ndarray:
    """Standard 2nd-order type-II closed loop |H|, wn from UGB and zeta."""
    wu = TWOPI * fugb
    wn = wu / np.sqrt(2.0 * zeta**2 + np.sqrt(4.0 * zeta**4 + 1.0))
    s = 2j * np.pi * f
    return (2.0 * zeta * wn * s + wn**2) / (s**2 + 2.0 * zeta * wn * s + wn**2)


def fit_closed_loop(f: np.ndarray, ldbc: np.ndarray) -> ClosedLoopFit:
    """Direct (non-iterative) estimators — no local minima, no divergence.

    1. knee   : steepest slope of the smoothed log-log curve
    2. plateau: median of S in [knee/8, knee/2] (below the flicker rise)
    3. f_3db  : first smoothed crossing of plateau/2 beyond the plateau
    4. peaking: max smoothed S near the knee over the plateau -> zeta ->
                phase-margin estimate and UGB via the 2nd-order template
    5. skirt  : Leeson fit of f >= 3*f_3db, labelled AS SEEN
    """
    f = np.asarray(f, dtype=float)
    s = _sphi(ldbc)
    logf = np.log10(f)
    k = max(5, f.size // 15)
    sm_db = np.convolve(10.0 * np.log10(s), np.ones(k) / k, mode="same")
    sm = 10.0 ** (sm_db / 10.0)
    slope = np.gradient(sm_db, logf)               # dB/dec

    # loop-rolloff onset: first frequency where the slope goes below
    # -12 dB/dec and STAYS mostly below for the next half decade.  In-band
    # flicker sits at -10..0 dB/dec, the closed-loop rolloff at <= -20:
    # the -12 threshold separates them robustly.
    onset_i = None
    for i in range(k, f.size - k):
        if slope[i] < -12.0:
            ahead = slope[(f >= f[i]) & (f <= f[i] * 3.16)]
            if ahead.size and np.mean(ahead < -12.0) > 0.6:
                onset_i = i
                break
    f_onset = float(f[onset_i]) if onset_i is not None \
        else float(f[f.size // 2])

    inb = (f >= f_onset / 10.0) & (f <= f_onset / 2.0)
    plateau = float(np.median(s[inb])) if inb.sum() >= 3 \
        else float(np.median(s[: max(4, f.size // 8)]))

    beyond = (f > f_onset / 2.0) & (sm < plateau / 2.0)
    f_3db = float(f[beyond][0]) if beyond.any() else f_onset

    # peaking on lightly-smoothed data — the wide kernel used for slope
    # detection flattens the (narrow) closed-loop peak
    k2 = max(3, f.size // 60)
    sm2 = 10.0 ** (np.convolve(10.0 * np.log10(s), np.ones(k2) / k2,
                               mode="same") / 10.0)
    near = (f > f_onset / 3.0) & (f < 3.0 * f_3db)
    peaking = max(0.0, float(10.0 * np.log10(np.max(sm2[near]) / plateau))) \
        if near.any() else 0.0

    # peaking -> zeta by inverting the 2nd-order template numerically
    zg = np.geomspace(0.2, 8.0, 200)
    fg = np.geomspace(1e-2, 1e2, 400)
    pk = np.array([20.0 * np.log10(np.max(np.abs(_type2_h(fg, 1.0, z))))
                   for z in zg])
    zeta = float(np.interp(-peaking, -pk, zg))     # pk decreases with zeta
    # template f_3db/f_ugb ratio at this zeta -> UGB estimate
    hh = np.abs(_type2_h(fg, 1.0, zeta))
    idx = np.nonzero(hh < np.sqrt(0.5))[0]
    ratio = float(fg[idx[0]]) if idx.size else 1.5
    f_ugb = f_3db / ratio

    skirt = f >= 3.0 * f_3db
    if skirt.sum() >= 6:
        lee = fit_leeson(f[skirt], _ldbc(s[skirt]))
    else:
        lee = fit_leeson(f[f.size // 2:], _ldbc(s[f.size // 2:]))
    k3, k2, floor = lee.k

    h = _type2_h(f, f_ugb, zeta)
    template = (plateau * np.abs(h) ** 2
                + (k3 / f**3 + k2 / f**2) * np.abs(1.0 - h) ** 2
                + max(floor, 1e-40))
    resid_db = float(np.sqrt(np.mean((_ldbc(template) - _ldbc(s)) ** 2)))
    return ClosedLoopFit(f_3db=f_3db, f_ugb=float(f_ugb), zeta=zeta,
                         inband_dbchz=float(_ldbc(np.array([plateau]))[0]),
                         peaking_db=peaking, osc=lee,
                         residual_db_rms=resid_db)


# ------------------------------------------------------------ attribution
@dataclass
class BudgetAttribution:
    groups: list[tuple[str, ...]]    # identifiable source groups (by shape)
    factors: dict[tuple[str, ...], float]   # power scale per group
    factors_db: dict[tuple[str, ...], float]
    residual_db_rms: float
    notes: list[str] = field(default_factory=list)

    def worst(self) -> tuple[str, ...]:
        return max(self.factors, key=lambda k: self.factors[k])


def attribute_budget(pll, f_meas: np.ndarray, ldbc_meas: np.ndarray,
                     flag_db: float = 3.0,
                     shape_corr: float = 0.98) -> BudgetAttribution:
    """Explain a measured spectrum as a nonnegative rescale of the budget.

    Sources whose modeled shapes are collinear on the measured grid
    (correlation of log-PSD shape > shape_corr) are NOT separable from a
    single phase-noise curve — reference, divider and sampler kT/C all look
    like "flat through H".  They are therefore clustered into identifiable
    GROUPS first; NNLS then solves min || sum_g a_g * S_g(f) - S_meas(f) ||
    (relative weighting, a_g >= 0) per group.  a_g ~ 1 means the group is
    on budget; a_g >> 1 names the culprit group.  Separating sources inside
    a group needs conditional measurements (change fref, N, bias...).
    """
    ar = pll.analyze()
    f_meas = np.asarray(f_meas, dtype=float)
    s_meas = _sphi(ldbc_meas)
    names = [k for k in ar.pn_breakdown if k != "total"]
    cols = np.stack([np.interp(np.log10(f_meas), np.log10(ar.f),
                               ar.pn_breakdown[k]) for k in names], axis=1)

    # cluster by log-shape correlation (greedy, order by column power)
    logs = np.log10(np.maximum(cols, 1e-40))
    logs = logs - logs.mean(axis=0)
    norm = np.linalg.norm(logs, axis=0)
    order = np.argsort(-cols.sum(axis=0))
    groups: list[list[int]] = []
    for i in order:
        for g in groups:
            j = g[0]
            c = float(logs[:, i] @ logs[:, j] / max(norm[i] * norm[j], 1e-30))
            if c > shape_corr:
                g.append(i)
                break
        else:
            groups.append([i])
    gnames = [tuple(names[i] for i in g) for g in groups]
    a = np.stack([cols[:, g].sum(axis=1) for g in groups], axis=1)

    w = 1.0 / s_meas
    coef, _ = nnls(a * w[:, None], s_meas * w)
    fit = a @ coef
    resid = float(np.sqrt(np.mean((_ldbc(fit) - _ldbc(s_meas)) ** 2)))
    factors = {gn: float(c) for gn, c in zip(gnames, coef)}
    fdb = {gn: float(10.0 * np.log10(max(c, 1e-12)))
           for gn, c in factors.items()}
    notes = [f"{'+'.join(gn)}: {fdb[gn]:+.1f} dB vs budget"
             for gn in gnames if abs(fdb[gn]) > flag_db and factors[gn] > 0]
    if not notes:
        notes = [f"all source groups within +/-{flag_db:.0f} dB of budget"]
    return BudgetAttribution(groups=gnames, factors=factors, factors_db=fdb,
                             residual_db_rms=resid, notes=notes)
