"""Where the two domains stop being comparable: the predicates, in one place.

Every function here answers one question of the form "is this operating point
past a structural limit of the time-domain engine or of the linear model?".
They are pure functions on primitives, deliberately: the engines call them to
decide when to append a warning note, and ``pllsim.validation`` wraps the same
functions into the boundary registry the cross-domain sweep asserts against.
One predicate, two consumers -- so the runtime warning and the test contract
cannot drift apart, which is the failure mode that made this module necessary.

The constants are the measured/derived limits themselves.  Change one only
together with the physics that justifies it; the sweep re-measures the
consequences on every CI run.
"""
from __future__ import annotations

#: analyze() for the CPPLL and SPLL is a continuous-time approximation of a
#: sampled loop.  Past UGB = fref/CT_UGB_RATIO the discrete loop's peaking
#: deviates visibly from the s-domain curve (the synthesizer refuses outright
#: at fref/8, synth.py).  The SSPLL and ADPLL use exact z-domain models and
#: are exempt.
CT_UGB_RATIO = 10.0

#: Usable fraction of a sampled record's rate.  Content between 0.45*fs and
#: the Nyquist edge sits in the estimator's roll-off and alias overlap, so
#: spur reporting, jitter integration and PSD comparison all stop here rather
#: than at fs/2 (same constant as arch/base.py's spur filters).
NYQ_FRACTION = 0.45

#: OscPhaseNoiseGen synthesizes 1/f-FM noise in chunks of this many samples
#: (core/colored.py); the sequence decorrelates across refills, so flicker
#: content below fref/FLICKER_CHUNK is not faithfully generated no matter how
#: long the run is.  The other floor is the record itself: nothing below
#: fref/n_settled exists in a finite record (synth_from_psd zeroes DC).
FLICKER_CHUNK = 1 << 16

#: engine.postprocess discards this fraction of the record before the PSD.
SETTLE_FRAC = 0.25


def ct_approx_exceeded(f_ugb: float, fref: float) -> bool:
    """Linear model past its continuous-time validity (CPPLL/SPLL only)."""
    return f_ugb > fref / CT_UGB_RATIO


def jitter_band_clipped(int_band_hi: float, fs: float) -> bool:
    """simulate() integrates jitter only to NYQ_FRACTION*fs; analyze() does
    the full band.  When this is true the two jitter numbers cover different
    bands and must not be compared directly."""
    return int_band_hi > NYQ_FRACTION * fs


def flicker_floor_hz(fref: float, n_cycles: int) -> float:
    """Lowest offset at which synthesized flicker content is trustworthy."""
    n_settled = max(1, int(n_cycles * (1.0 - SETTLE_FRAC)))
    return max(fref / n_settled, fref / FLICKER_CHUNK)


#: A loop counts as never having reached fout when the mean output frequency
#: over the last LOCK_TAIL_CYCLES sits more than LOCK_FERR_FRACTION*fref away.
#: Measured separation: a truly unlocked or railed loop wanders 1e5..1e9 Hz
#: off, a converged one sits within a few hundred (fref/1000 = 19..250 kHz).
#: Shared by postprocess's runtime note and compare_domains' refusal.
LOCK_FERR_FRACTION = 1e-3
LOCK_TAIL_CYCLES = 5000


def tail_frequency_error(freq_out, fout: float) -> float:
    """|mean of the record's tail - fout| in Hz."""
    import numpy as np
    tail = np.asarray(freq_out[-LOCK_TAIL_CYCLES:], dtype=float)
    return abs(float(np.mean(tail)) - float(fout))


def never_locked(ferr_hz: float, fref: float) -> bool:
    """The output never settled at the configured fout: unlocked, railed
    against a tuning range, or pulled elsewhere.  Every number downstream
    then describes that state, not the design."""
    return ferr_hz > LOCK_FERR_FRACTION * fref


def conditionally_stable(n_crossings: int) -> bool:
    """More than one gain crossover: phase margin read at one crossing does
    not describe the loop, and the linear jitter integral spans a region
    where the loop is not small-signal stable."""
    return n_crossings != 1
