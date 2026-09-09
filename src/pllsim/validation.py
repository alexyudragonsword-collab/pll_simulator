"""Cross-domain validation: one comparator, one boundary registry.

The project's core contract is that every architecture's linear model and
time-domain engine agree band-averaged within a stated tolerance.  Until this
module existed, the comparison lived as five hand-copied 12-line blocks in
the test files -- five places for the same bug, and no way for a GUI, a sweep
or a script to ask "how far apart are the domains *here*?".

:func:`compare_domains` is that question as a function.  It is deliberately
opinionated about the things the inline copies silently got away with:

* the comparison band is clipped to where both estimates mean something
  (above ~3 resolution bins, below ``NYQ_FRACTION`` of the record rate), and
  every clip is *recorded* in ``clip_reasons`` rather than applied silently;
* bins with too few points land in ``skipped`` instead of vanishing;
* the jitter figures it returns are integrated over the **same band** for
  both domains -- unlike the headline ``ar.jitter_fs`` / ``sim.jitter_fs``
  pair, whose bands differ whenever ``int_band`` reaches past what a record
  sampled at fref can show.

The :data:`BOUNDARIES` registry is the machine-readable list of capability
limits.  Each entry wraps a predicate from :mod:`pllsim.core.boundaries`
(the same functions the engines use to emit runtime warning notes) plus the
one-sentence statement of the limit and the tolerance allowance the sweep
grants when the flag is active.  The cross-domain sweep asserts against these
flags: an out-of-tolerance point with no active flag is a model defect, not
a boundary -- that contract is what keeps the documented limits honest.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Callable

import numpy as np

from .core.boundaries import (
    NYQ_FRACTION,
    conditionally_stable,
    ct_approx_exceeded,
    flicker_floor_hz,
    jitter_band_clipped,
    tuning_law_railed,
    tuning_swing_exceeded,
)
from .core.jitter import rms_jitter_fs

#: Minimum PSD points per bin for the bin mean to be worth comparing.
MIN_POINTS = 3

#: The comparison band starts no lower than this many resolution bins above
#: DC -- below that the Welch estimate is dominated by leakage and detrending.
K_RBW = 3.0


class NotLockedError(ValueError):
    """The simulated loop never locked at this operating point.

    Comparing an unlocked run against a lock-assumed linear model measures
    nothing: the calibration sweep saw +25..48 dB "deviations" on off-plan
    fractional configs that were simply loops wandering unlocked.  Every
    loop architecture's engine has a lock detector and reports
    ``lock_time_s``; ``None`` there means it never fired.  ILCM/MDLL are
    injection-locked per cycle and have no detector -- they are exempt.
    """


@dataclass(frozen=True)
class BandDeviation:
    """One log-spaced bin of the comparison."""

    f_lo: float
    f_hi: float
    n_points: int
    err_db: float
    """10*log10(mean_sim / mean_model) of linear power; NaN when skipped."""


@dataclass(frozen=True)
class DomainComparison:
    """Everything one cross-domain comparison produced, nothing hidden."""

    bands: list[BandDeviation]
    skipped: list[BandDeviation]
    band_used: tuple[float, float]
    clip_reasons: list[str]
    jitter_sim_fs: float
    jitter_model_fs: float
    """Both integrated over ``band_used`` -- the same band, so the pair is
    comparable, unlike the headline result fields whose bands can differ."""
    flags: frozenset[str]
    notes: list[str]
    psd_source: str

    @property
    def worst_db(self) -> float:
        """Largest absolute band deviation; +inf if nothing was comparable."""
        if not self.bands:
            return math.inf
        return max(abs(b.err_db) for b in self.bands)


@dataclass(frozen=True)
class BoundaryContext:
    """What a boundary predicate may look at."""

    pll: Any
    ar: Any
    sim: Any
    band: tuple[float, float]
    n_cycles: int


@dataclass(frozen=True)
class Boundary:
    """One capability limit: predicate, statement, and tolerance allowance.

    ``extra_db`` is how much beyond the architecture's base tolerance the
    sweep accepts while this flag is active.  It is the *same number* the
    documentation quotes for the limit -- set from sweep calibration
    measurements, never from optimism.  0.0 means "flagged for information;
    no widening measured or granted yet".
    """

    code: str
    statement: str
    applies: Callable[[BoundaryContext], bool]
    extra_db: float = 0.0


def _is_ct_arch(pll: Any) -> bool:
    # By name, not import: validation must stay importable from arch code
    # without a cycle.  SSPLL/ADPLL use exact discrete models and are exempt.
    return type(pll).__name__ in ("CPPLL", "SPLL")


def _has_v_law(pll: Any) -> bool:
    # the three analog loops evaluate OscConfig's control-voltage law; the
    # ADPLL/MDLL tune by a digital word and the ILCM in Hz
    return type(pll).__name__ in ("CPPLL", "SSPLL", "SPLL")


def _tuning_flag(pll: Any) -> bool:
    osc = pll.cfg.osc
    v = osc.v_for(pll.cfg.fout)
    return tuning_law_railed(v, osc.v_min, osc.v_max) or \
        tuning_swing_exceeded(v, osc.v_min, osc.v_max)


def _has_flicker(pll: Any) -> bool:
    osc = getattr(pll.cfg, "osc", None)
    return bool(osc is not None and getattr(osc, "pn_f1f3", 0.0) > 0.0)


BOUNDARIES: tuple[Boundary, ...] = (
    Boundary(
        code="ct-approx",
        statement=(
            "CPPLL/SPLL analyze() is a continuous-time approximation; past "
            "UGB > fref/10 the sampled loop's peaking deviates from it, and "
            "the time domain is the reference in that region."),
        applies=lambda c: _is_ct_arch(c.pll) and ct_approx_exceeded(
            c.ar.loop.f_ugb, c.pll.cfg.fref),
        extra_db=5.5,     # measured: worst 7.25 dB at UGB = fref/9.6, the
                          # deepest flagged loop the synthesizer will build
                          # (it refuses past fref/8); 2.5 base + 5.5 covers
    ),
    Boundary(
        code="jitter-band-clip",
        statement=(
            "simulate() integrates jitter only to 0.45*fref (a reference-"
            "edge record shows nothing above it); analyze() integrates the "
            "full int_band.  The two headline jitter numbers cover "
            "different bands whenever int_band reaches past 0.45*fref."),
        applies=lambda c: jitter_band_clipped(
            c.pll.cfg.int_band[1], c.sim.fs),
    ),
    Boundary(
        code="flicker-floor",
        statement=(
            "Synthesized flicker is only faithful above "
            "max(fref/n_settled, fref/65536); a comparison band starting "
            "below that floor compares the model against noise the run "
            "never generated."),
        applies=lambda c: _has_flicker(c.pll) and c.band[0] < flicker_floor_hz(
            c.pll.cfg.fref, c.n_cycles),
    ),
    Boundary(
        code="tuning-swing",
        statement=(
            "The analog loops' control-voltage law is unbounded unless "
            "OscConfig sets v_min/v_max: fout is reached wherever it needs "
            "the varactor to go.  Flagged when fout needs more than "
            "+/-1.5 V of travel from f0 (no single band spans that; the "
            "coarse bank is the physical answer) or, with a range set, lies "
            "outside it (the loop rails and never reaches fout).  The two "
            "domains agree here -- both follow the same law -- so this is a "
            "modelling-range statement, not a comparison tolerance."),
        applies=lambda c: _has_v_law(c.pll) and _tuning_flag(c.pll),
    ),
    Boundary(
        code="conditional-stability",
        statement=(
            "The open loop crosses unity gain more than once; phase margin "
            "at one crossing does not describe the loop and the linear "
            "jitter integral spans a non-small-signal region."),
        applies=lambda c: conditionally_stable(c.ar.loop.n_crossings),
    ),
    Boundary(
        code="bbpd-linearization",
        statement=(
            "The BBPD linear gain is a describing-function approximation; "
            "when the loop is quantization-dominated it over-predicts "
            "in-band noise by 2-4 dB and the time domain is the reference."),
        applies=lambda c: getattr(c.pll.cfg, "mode", "") == "dtc_bbpd",
        extra_db=1.5,     # measured +3.3..3.4 dB at stock vs the 3.0 base
    ),
    Boundary(
        code="dsm-tonal",
        statement=(
            "The linear model budgets the DSM/DTC residual as white noise "
            "(ShapedQuantization); the actual residual is deterministic and "
            "tonal, concentrated at frac-related offsets.  For near-rational "
            "fractions most of that power sits in tones outside (or at the "
            "edge of) the comparison band, so the in-band PSDs legitimately "
            "differ -- the frac_spur table is the deterministic complement "
            "the white budget stands in for."),
        applies=lambda c: getattr(c.pll.cfg, "frac", None) is not None,
        extra_db=1.5,     # cppll_frac measured 3.0 vs the 2.5 base; the
                          # sspll_frac near-rational extreme (6.84 dB) is
                          # pinned as a KnownGap instead of widened here
    ),
)

_BY_CODE = {b.code: b for b in BOUNDARIES}


def boundary(code: str) -> Boundary:
    return _BY_CODE[code]


def active_flags(ctx: BoundaryContext) -> frozenset[str]:
    return frozenset(b.code for b in BOUNDARIES if b.applies(ctx))


# ---------------------------------------------------------------- comparator

def _pick_source(sim: Any, band_hi: float) -> tuple[str, np.ndarray, np.ndarray, float]:
    """Choose the PSD record that can actually cover the requested band.

    The reference-rate Welch PSD is the default: it is segment-averaged, so
    its variance is what the historical tolerances were set against.  The
    fine record (plain periodogram, no averaging) is used only when the band
    reaches past what the reference-rate record can show -- switching to it
    gratuitously would change the variance floor under every caller.
    """
    f_ref = sim.f_psd
    have_ref = f_ref is not None and band_hi <= NYQ_FRACTION * sim.fs
    if have_ref:
        return "ref", sim.f_psd, sim.s_phi_psd, float(sim.fs)
    extra = sim.extra or {}
    if "fine_f" in extra:
        return ("fine", np.asarray(extra["fine_f"]),
                np.asarray(extra["fine_psd"]), float(extra["fine_fs"]))
    if f_ref is None:
        raise ValueError("simulation carries no PSD (record too short?)")
    return "ref", sim.f_psd, sim.s_phi_psd, float(sim.fs)


def compare_domains(pll: Any, *, n_cycles: int, seed: int,
                    n_bins: int = 7,
                    band: tuple[float, float] | None = None,
                    psd_source: str = "auto",
                    min_points: int = MIN_POINTS,
                    sim_kwargs: dict[str, Any] | None = None,
                    ) -> DomainComparison:
    """Run both domains at one operating point and measure the distance.

    ``band`` defaults to ``(f_ugb/10, fref/4)`` -- the band the historical
    per-architecture tests used, chosen to sit above the Welch resolution
    floor and below the region where the sampled record rolls off.  The
    default ``n_bins=7`` likewise reproduces those tests' 8-edge binning.
    """
    ar = pll.analyze()
    sim = pll.simulate(n_cycles, seed=seed, **(sim_kwargs or {}))
    fref = float(pll.cfg.fref)
    if (type(pll).__name__ not in ("ILCM", "MDLL")
            and sim.lock_time_s is None):
        # the detector not firing is necessary but not sufficient: its
        # thresholds are tuned for the design point, and off-plan loops can
        # converge in fact while it stays silent (measured: off-plan frac
        # CPPLLs compare at 2-4 dB with lock_time None).  The tail frequency
        # error separates the two -- a truly unlocked loop wanders ~1e5+ Hz
        # off, a converged one sits within a few hundred
        from .core.boundaries import never_locked, tail_frequency_error
        ferr = tail_frequency_error(sim.freq_out, pll.cfg.fout)
        if never_locked(ferr, fref):
            raise NotLockedError(
                f"{type(pll).__name__} never locked in {n_cycles} cycles "
                f"(tail frequency error {ferr:.3g} Hz) — the domains cannot "
                "be compared; the configuration is outside the "
                "architecture's acquisition envelope (or needs far more "
                "cycles)")
    requested = band or (ar.loop.f_ugb / 10.0, fref / 4.0)

    if psd_source == "auto":
        source, f_s, s_s, fs_s = _pick_source(sim, requested[1])
    elif psd_source == "ref":
        if sim.f_psd is None:
            raise ValueError("no reference-rate PSD on this simulation")
        source, f_s, s_s, fs_s = "ref", sim.f_psd, sim.s_phi_psd, float(sim.fs)
    elif psd_source == "fine":
        extra = sim.extra or {}
        if "fine_f" not in extra:
            raise ValueError("no fine record on this simulation")
        source, f_s, s_s, fs_s = ("fine", np.asarray(extra["fine_f"]),
                                  np.asarray(extra["fine_psd"]),
                                  float(extra["fine_fs"]))
    else:
        raise ValueError(f"psd_source must be auto|ref|fine, got {psd_source!r}")

    clip_reasons: list[str] = []
    lo, hi = float(requested[0]), float(requested[1])
    rbw = float(f_s[0])                       # first bin after the DC drop
    if lo < K_RBW * rbw:
        clip_reasons.append(
            f"band start raised {lo:.3g} -> {K_RBW * rbw:.3g} Hz "
            f"({K_RBW:g}x the {rbw:.3g} Hz resolution bin)")
        lo = K_RBW * rbw
    nyq = NYQ_FRACTION * fs_s
    if hi > nyq:
        clip_reasons.append(
            f"band end lowered {hi:.3g} -> {nyq:.3g} Hz "
            f"(0.45x the {fs_s:.3g} Hz record rate)")
        hi = nyq
    if not lo < hi:
        raise ValueError(
            f"empty comparison band after clipping: {lo:.3g}..{hi:.3g} Hz "
            f"({'; '.join(clip_reasons)})")

    m = (f_s > lo) & (f_s < hi)
    fm, sm = f_s[m], s_s[m]
    if fm.size < min_points:
        raise ValueError(
            f"only {fm.size} PSD points in {lo:.3g}..{hi:.3g} Hz -- record "
            f"too short for this band")
    target = np.interp(np.log10(fm), np.log10(ar.f),
                       ar.pn_breakdown["total"])

    # edges over the *masked data* endpoints, exactly as the historical
    # tests did -- edges over (lo, hi) would shift bin contents slightly and
    # silently re-baseline every tolerance
    edges = np.logspace(np.log10(fm[0]), np.log10(fm[-1]), n_bins + 1)
    bands: list[BandDeviation] = []
    skipped: list[BandDeviation] = []
    for a, b in zip(edges[:-1], edges[1:]):
        mm = (fm >= a) & (fm < b)
        n = int(mm.sum())
        if n < min_points:
            skipped.append(BandDeviation(a, b, n, math.nan))
            continue
        err = 10.0 * math.log10(float(np.mean(sm[mm]) / np.mean(target[mm])))
        bands.append(BandDeviation(a, b, n, err))

    ctx = BoundaryContext(pll=pll, ar=ar, sim=sim, band=(lo, hi),
                          n_cycles=n_cycles)
    return DomainComparison(
        bands=bands,
        skipped=skipped,
        band_used=(lo, hi),
        clip_reasons=clip_reasons,
        jitter_sim_fs=rms_jitter_fs(f_s, s_s, sim.f0, lo, hi),
        jitter_model_fs=rms_jitter_fs(
            ar.f, ar.pn_breakdown["total"], ar.f0, lo, hi),
        flags=active_flags(ctx),
        notes=list(ar.notes) + list(sim.notes),
        psd_source=source,
    )


@dataclass(frozen=True)
class KnownGap:
    """A confirmed cross-domain model gap, pinned so it cannot rot.

    Entries are added when the sweep finds an out-of-tolerance point whose
    cause is a real model limitation too large to fix inline.  ``pinned_db``
    is the measured worst-band deviation at ``point_id``; the sweep
    re-measures it on every run and fails if it drifts by more than
    ``slack_db`` in either direction -- so this register is measured, not
    remembered, without the roadmap generator having to run simulations.
    """

    point_id: str
    code: str
    pinned_db: float
    statement: str
    slack_db: float = 0.75


#: Confirmed by the calibration sweep (120k cycles, seed 1), rendered into
#: docs/roadmap.md by docs/gen_roadmap.py, and re-measured by
#: tests/test_cross_domain_sweep.py on every CI run -- an entry that drifts
#: more than its slack in either direction fails the sweep, so these numbers
#: are measured, not remembered.
CROSS_DOMAIN_GAPS: tuple[KnownGap, ...] = (
    KnownGap("cppll-fref-x0.5", "ct-peaking", 3.87,
             "CPPLL at half the design fref (N doubled, same filter): the "
             "CT model's peaking-region error grows off the designed plan "
             "even at a safe UGB/fref (~1/18)."),
    KnownGap("cppll-ugb-x1.6", "ct-knee", 5.26,
             "CPPLL retuned to 1.6x stock UGB (fref/12.7): inside the CT "
             "knee -- deviation grows before the fref/10 warning fires."),
    KnownGap("cppll-ugb-x1.9", "ct-knee", 6.54,
             "CPPLL at 1.9x stock UGB (fref/10.7): just under the warning "
             "threshold, deviation already 6.5 dB in the fref/8..fref/4 "
             "bands."),
    KnownGap("cppll-pm45", "ct-filter-shape", 3.90,
             "CPPLL re-synthesized at PM 45 (same UGB): the CT error "
             "depends on the filter's shape, not only on UGB/fref."),
    KnownGap("cppll-fine-m8", "engine-pulse-shape", 2.78,
             "CPPLL simulated with fine_oversample=8: the real up/down "
             "doublet replaces the one-net-pulse approximation and shifts "
             "the measured PSD by ~0.7 dB against the CT model."),
    KnownGap("cppll_frac-fref-x0.5", "dsm-tonal", 3.90,
             "Fractional CPPLL at half fref (fraction held, fout moved to "
             "stay consistent): the white DSM-residual budget vs the tonal "
             "truth widens off the designed plan."),
    KnownGap("sspll_frac-stock", "dsm-tonal", 6.84,
             "Fractional SSPLL at its own stock point: frac=0.2503 is "
             "near-rational, so the MASH-1 residual is nearly periodic -- "
             "its power sits in tones at fref/4 harmonics, not in the white "
             "floor the model budgets.  The in-band PSD reads a flat ~6 dB "
             "below the model while the spur table carries the tones."),
    KnownGap("sspll_frac-fref-x0.5", "dsm-tonal", 4.40,
             "Fractional SSPLL at half fref (consistent fraction): the "
             "tonal-residual family, 0.1 dB past its flagged allowance."),
    KnownGap("sspll_frac-fref-x2.0", "dsm-tonal", 9.32,
             "Fractional SSPLL at twice fref: the tonal DSM residual "
             "dominates the shrunken in-band span."),
    KnownGap("sspll_frac-near-int", "dsm-tonal", 6.79,
             "Fractional SSPLL at fraction 0.004: near-rational tonal "
             "residual, same family as the stock 0.2503 point."),
    KnownGap("spll-fref-x0.5", "ct-peaking", 2.08,
             "SPLL at half the design fref: marginally past its 2.0 dB "
             "stock bound, same CT-peaking family as the CPPLL."),
    KnownGap("mdll-fref-x2.0", "zoh-approx", 3.45,
             "MDLL at twice the design fref: the 1-ZOH oscillator NTF "
             "approximation sits at the edge of its 3.5 dB tolerance."),
    # Three adpll_bb off-plan entries (12-16 dB) were pinned here briefly
    # and removed the same day: the numbers measured a sweep-harness bug
    # (fref scaled without keeping cfg.frac.frac consistent, so the loop
    # locked to the configured fraction megahertz away from cfg.fout), not
    # the tool.  With consistent configs those points sit at 3.7-4.7 dB,
    # inside their flagged allowance.
)
