"""The IPN decomposition a pie chart is only honest if it sums to the whole.

A pie asserts something the curve plot does not: that the slices *are* the
total.  These check the assertion rather than assuming it, on every
benchmark preset, and check that the per-source jitters recombine in
quadrature -- which is the same statement in the units an RF designer
reads.
"""
import math

import pytest

from pllsim import presets
from pllsim.plotting import plot_ipn_pie

BENCH = [b["preset"] for b in presets.BENCHMARKS]


@pytest.mark.parametrize("name", BENCH)
def test_shares_sum_to_one_on_every_benchmark(name):
    """`total` is the sum of the uncorrelated sources, so the shares are a
    partition.  Mutation: drop one source from pn_breakdown and this fails.
    """
    ar = presets.ALL_PRESETS[name]().analyze()
    rows = ar.ipn_shares()
    assert len(rows) == len(ar.pn_breakdown) - 1     # every source, no total
    assert sum(s for _k, s, _j in rows) == pytest.approx(1.0, abs=1e-9)


@pytest.mark.parametrize("name", BENCH)
def test_per_source_jitter_recombines_in_quadrature(name):
    """The same partition, stated in fs: uncorrelated contributors add in
    power, so sqrt(sum of squares) must return the reported total jitter.
    A share converted with the wrong exponent passes the sum-to-one test
    above and fails this one.
    """
    ar = presets.ALL_PRESETS[name]().analyze()
    quad = math.sqrt(sum(j * j for _k, _s, j in ar.ipn_shares()))
    assert quad == pytest.approx(ar.jitter_fs, rel=1e-6)


def test_shares_are_sorted_and_agree_with_dominant_source():
    ar = presets.bench_wu19_spll_frac_52m_6p253g().analyze()
    rows = ar.ipn_shares()
    shares = [s for _k, s, _j in rows]
    assert shares == sorted(shares, reverse=True)
    assert rows[0][0] == ar.dominant_source()


def test_a_worse_source_takes_a_bigger_slice():
    """The decorative-parameter check, in pie form: degrading one source has
    to move its own slice, not just the total.
    """
    pll = presets.bench_markulic16_sspll_40m_10p24g()
    before = dict((k, s) for k, s, _j in pll.analyze().ipn_shares())
    pll.cfg.osc.pn_dbchz += 20.0            # a far worse VCO
    after = dict((k, s) for k, s, _j in pll.analyze().ipn_shares())
    assert after["vco"] > before["vco"] * 2, (before["vco"], after["vco"])
    assert after["ref"] < before["ref"]      # everything else is diluted


def test_the_pie_pools_small_slices_and_says_how_many():
    """A pie with nine wedges is unreadable, but a pool that does not say
    what it pooled is worse than the clutter."""
    ar = presets.bench_wu19_spll_frac_52m_6p253g().analyze()
    fig = plot_ipn_pie(ar, min_share=0.05)
    labels = [t.get_text() for t in fig.axes[0].get_legend().get_texts()]
    pooled = [ln for ln in labels if ln.startswith("other (")]
    assert len(pooled) == 1, labels
    n_pooled = int(pooled[0].split("(")[1].split(")")[0])
    assert n_pooled == sum(1 for _k, s, _j in ar.ipn_shares() if s < 0.05)
    assert len(fig.axes[0].patches) == len(labels)
    # every wedge names its own jitter, because a share of power does not
    # rank the same way to the eye as a share of jitter
    assert all("fs)" in ln for ln in labels), labels


def test_the_pie_survives_an_architecture_with_few_sources():
    ar = presets.ilcm_250m_12g().analyze()
    fig = plot_ipn_pie(ar)
    assert len(fig.axes[0].patches) >= 1
