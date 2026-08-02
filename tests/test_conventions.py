"""The conventions analyze() and simulate() must agree on.

Each test here isolates ONE noise source or spur mechanism by making it
dominant, so a factor-of-2 in that single contributor cannot hide inside a
budget where something else dominates.  The architecture-level cross-domain
tests (test_cppll.py etc.) compare totals with 2.5-3 dB tolerances, which is
exactly wide enough to miss a 3 dB error in one term -- that is how the
sampler gm path stayed 3 dB low.
"""
from dataclasses import replace

import numpy as np
import pytest

from pllsim import presets
from pllsim.core.jitter import integrate_pn


def _dominance_and_ratio(make, source, boost_field, boost, n_cycles=400_000):
    """(share of that source in analyze, sim/analyze jitter ratio)."""
    p = make()
    setattr_path(p.cfg, boost_field, boost)
    ar = p.analyze()
    tot = integrate_pn(ar.f, ar.pn_breakdown["total"], *ar.int_band)
    share = integrate_pn(ar.f, ar.pn_breakdown[source], *ar.int_band) / tot
    q = make()
    setattr_path(q.cfg, boost_field, boost)
    sim = q.simulate(n_cycles, seed=5)
    return share, sim.jitter_fs / ar.jitter_fs


def setattr_path(cfg, dotted: str, value):
    obj = cfg
    parts = dotted.split(".")
    for p in parts[:-1]:
        obj = getattr(obj, p)
    # the block configs are frozen-ish dataclasses used by value; rebuild
    parent = cfg
    for p in parts[:-2]:
        parent = getattr(parent, p)
    if len(parts) == 1:
        setattr(cfg, parts[0], value)
    else:
        setattr(parent, parts[-2], replace(obj, **{parts[-1]: value}))


@pytest.mark.parametrize("preset,source", [
    ("sspll_19p2m_4p8g", "gm"),
    ("spll_100m_8g", "gm"),
])
def test_sampler_gm_noise_agrees_across_domains(preset, source):
    """The gm stage injects a charge once per cycle, not a duty-cycled current.

    A sampled sequence carries the 2x alias factor into the one-sided PSD
    (same as SampledKTC); a duty-scaled continuous source does not.  Getting
    that wrong put analyze() 3 dB under the time domain.
    """
    share, ratio = _dominance_and_ratio(
        presets.ALL_PRESETS[preset], source, "sampler.gm_noise_a2hz", 1e-19)
    assert share > 0.9, f"gm only {100 * share:.0f}% of the budget; test is blind"
    assert 0.85 < ratio < 1.15, f"gm noise off by {20 * np.log10(ratio):.1f} dB"


def test_charge_pump_noise_agrees_across_domains():
    """The reference the sampler path is compared against.

    White term only: `ChargePump.charge` injects a white charge and nothing
    else, while `noise_source()` also carries a 1/f corner, so a run with the
    default corner reads ~2 dB low for a reason that has nothing to do with
    the sampled-injection convention under test here.
    """
    def make():
        p = presets.cppll_19p2m_4p8g()
        p.cfg.cp = replace(p.cfg.cp, flicker_corner=0.0)
        return p
    share, ratio = _dominance_and_ratio(make, "cp", "cp.noise_a2hz", 1e-19)
    assert share > 0.9
    assert 0.85 < ratio < 1.15


def test_reference_spur_is_the_narrowband_fm_sideband():
    """L_spur = 20log10(beta/2) with beta = Kvco*V1/fref, V1 the PEAK ripple.

    The charge dq delivered once per reference period has a fundamental of
    peak amplitude 2*dq*fref in current, so V1 = 2*dq*fref*|Z(fref)|.  Nothing
    in the time domain can check this -- the engines step once per reference
    cycle, so a tone at fref folds to DC -- which is why it is pinned here.
    """
    p = presets.cppll_19p2m_4p8g()
    c = p.cfg
    c.cp = replace(c.cp, mismatch_pct=3.0, leakage_a=2e-9)
    ar = p.analyze()
    got = ar.spurs_analytic["ref_spur"]

    dq = abs(c.cp.icp * 0.01 * c.cp.mismatch_pct * c.cp.t_reset) \
        + abs(c.cp.leakage_a / c.fref)
    from pllsim.blocks.loopfilter import LoopFilter
    z = abs(LoopFilter(c.filt, 1.0 / c.fref).transimpedance(np.array([c.fref]))[0])
    v1 = 2.0 * dq * c.fref * z
    beta = c.osc.gain * v1 / c.fref
    expect = 20.0 * np.log10(beta / 2.0)
    assert abs(got - expect) < 1.0, f"{got:.1f} dBc vs textbook {expect:.1f} dBc"


@pytest.mark.parametrize("preset", ["cppll_frac_38p4m_6g", "adpll_bb_100m_10g",
                                    "sspll_frac_19p2m_4p806g",
                                    "spll_frac_52m_6p253g"])
def test_dtc_jitter_reaches_the_linear_budget(preset):
    """DTC random jitter is injected in the time domain by every frac engine,
    so it has to appear in every frac analyze() too."""
    lo = presets.ALL_PRESETS[preset]()
    lo.cfg.frac.dtc = replace(lo.cfg.frac.dtc, jitter_rms_s=0.0)
    hi = presets.ALL_PRESETS[preset]()
    hi.cfg.frac.dtc = replace(hi.cfg.frac.dtc, jitter_rms_s=1e-12)
    j_lo, j_hi = lo.analyze().jitter_fs, hi.analyze().jitter_fs
    assert j_hi > 1.01 * j_lo, (
        f"{preset}: 1 ps of DTC jitter moved analyze() from {j_lo:.1f} to "
        f"{j_hi:.1f} fs — the budget is blind to it")
    assert "dtc_jitter" in hi.analyze().pn_breakdown


def test_bbpd_sigma_includes_dtc_jitter():
    """The BBPD's linearized gain is set by the jitter at its input, so DTC
    jitter must move the predicted loop bandwidth, not just the noise."""
    lo = presets.adpll_bb_100m_10g()
    lo.cfg.frac.dtc = replace(lo.cfg.frac.dtc, jitter_rms_s=0.0)
    hi = presets.adpll_bb_100m_10g()
    hi.cfg.frac.dtc = replace(hi.cfg.frac.dtc, jitter_rms_s=500e-15)
    assert hi.analyze().loop.f_ugb < 0.97 * lo.analyze().loop.f_ugb
