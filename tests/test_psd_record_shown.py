"""The curve the front ends draw is the record the headline jitter came from.

The MDLL disagreed with its own linear model by 8-11 dB on the APK, the
Windows exe and the web page while the cross-domain sweep read 2-3 dB and
stayed green.  Both were right about what they measured: they were measuring
different records.  ``arch.base.attach_fine`` replaces ``jitter_fs`` with the
oversampled record's value and says why in its own docstring -- "the
oversampled record is the honest one: it contains the intra-period ripple
that the reference-rate record drops" -- but ``plot_pn_breakdown`` drew
``sim.f_psd``, the reference-rate record, for every architecture.  For an
MDLL the difference between those two records *is* the jitter mechanism the
architecture exists to have.

So the invariant is not "the MDLL is special".  It is that one SimResult must
not report a number from one record and draw a curve from another, and that
the comparator which gates the contract must read the same record the product
shows.  A test that only pinned the MDLL would let the next architecture
repeat it.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from pllsim import presets
from pllsim.core.jitter import rms_jitter_fs
from pllsim.plotting import data_lines, plot_pn_breakdown

SWEEP = Path(__file__).with_name("test_cross_domain_sweep.py")

# 40k cycles is enough for the record to carry a usable periodogram and short
# enough to keep this file inside the main job; the defect it guards is a
# factor of 2-3 in jitter, nowhere near the run-length noise.
CYCLES = 40_000
SEED = 1

# The architectures whose engines call attach_fine by default, so a plain
# simulate() carries both records and the two can disagree.
FINE_BY_DEFAULT = ["ilcm_250m_12g", "mdll_150m_2p4g"]


def _shown_curve(ar, sim):
    """The (f, S_phi-as-dBc) trace the phase-noise figure draws for the sim."""
    fig = plot_pn_breakdown(ar, sim)
    try:
        ax = fig.axes[0]
        for ln in data_lines(ax):
            # the label carries which record it is, so match the stem
            if str(ln.get_label()).startswith("time-domain sim"):
                return np.asarray(ln.get_xdata()), np.asarray(ln.get_ydata())
        raise AssertionError("the figure draws no time-domain curve")
    finally:
        import matplotlib.pyplot as plt
        plt.close(fig)


@pytest.mark.parametrize("name", FINE_BY_DEFAULT)
def test_the_curve_drawn_is_the_record_the_jitter_came_from(name):
    """Same record, one result object.

    attach_fine having replaced jitter_fs is the library's own statement that
    the fine record is the reported one; the figure has to follow it or the
    printed number and the picture describe different runs.
    """
    pll = getattr(presets, name)()
    ar = pll.analyze()
    sim = pll.simulate(CYCLES, seed=SEED)
    assert "fine_f" in (sim.extra or {}), \
        f"{name} no longer carries a fine record; this test's premise is gone"

    f_shown, _ = _shown_curve(ar, sim)
    _src, f_rep, _s_rep, _fs = sim.reported_psd()
    assert np.array_equal(f_shown, f_rep), \
        f"{name}: the figure draws neither the reported record nor its grid"

    # and it is really the intra-period record, not the reference-rate one:
    # the give-away is reach.  A record sampled once per reference edge stops
    # at fref/2 by construction, which is exactly the region an MDLL's
    # remaining phase lives above.
    assert f_shown[-1] > 0.5 * sim.fs, (
        f"{name}: the drawn curve stops at {f_shown[-1]:.3g} Hz, inside the "
        f"reference-rate record's {0.5 * sim.fs:.3g} Hz reach -- it is the "
        "record edge replacement leaves flat"
    )


@pytest.mark.parametrize("name", FINE_BY_DEFAULT)
def test_integrating_the_drawn_curve_reproduces_the_printed_jitter(name):
    """A designer who integrates the picture must land on the number.

    This is the user-visible form of the same invariant, and the one the bug
    report was phrased in: the frequency-domain view and the time-domain
    number have to be the same run.  5 % because the integration band is
    reconstructed here from the config rather than passed in.
    """
    pll = getattr(presets, name)()
    ar = pll.analyze()
    sim = pll.simulate(CYCLES, seed=SEED)
    f_shown, _ = _shown_curve(ar, sim)
    _src, f_rep, s_rep, fs = sim.reported_psd()
    assert np.array_equal(f_shown, f_rep)

    lo, hi = pll.cfg.int_band
    got = rms_jitter_fs(f_rep, s_rep, sim.f0,
                        max(lo, f_rep[0]), min(hi, 0.45 * fs))
    assert got == pytest.approx(sim.jitter_fs, rel=0.05), (
        f"{name}: integrating the drawn curve gives {got:.1f} fs but the "
        f"result reports {sim.jitter_fs:.1f} fs"
    )


def test_the_sweep_does_not_name_its_own_record():
    """The gate must not get a second opinion about which record to read.

    This is a textual check on purpose.  The defect was not a wrong number,
    it was a per-point `psd_source=` in the grid that quietly disagreed with
    what the front ends drew, and it survived because nothing could see the
    two answers at once.  Any reintroduction is the same bug, whatever value
    it is set to, so the guard is the absence of the knob rather than its
    value -- and it costs no simulation to enforce.

    If a point ever genuinely needs to override, delete this test in the same
    change and say in its body why one record is right for the gate and a
    different one right for the product.
    """
    src = SWEEP.read_text()
    assert "psd_source=" not in src, (
        "test_cross_domain_sweep.py pins psd_source by hand again; the "
        "comparator and plot_pn_breakdown both defer to "
        "SimResult.reported_psd so that the gate reads what ships"
    )
