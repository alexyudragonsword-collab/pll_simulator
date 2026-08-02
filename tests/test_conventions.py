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


@pytest.mark.parametrize("fc", [0.0, 100e3, 1e6])
def test_charge_pump_noise_agrees_across_domains(fc):
    """The reference the sampler path is compared against — flicker included.

    noise_source() has always carried a 1/f corner into analyze(); the time
    domain injected white charge only, so a default-corner run read ~2 dB low.
    """
    def make():
        p = presets.cppll_19p2m_4p8g()
        p.cfg.cp = replace(p.cfg.cp, flicker_corner=fc)
        return p
    share, ratio = _dominance_and_ratio(make, "cp", "cp.noise_a2hz", 1e-19)
    assert share > 0.9
    assert 0.85 < ratio < 1.15, f"CP off by {20 * np.log10(ratio):.1f} dB"


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


# --------------------------------------------------- kwargs that did nothing
def test_adpll_rejects_kwargs_its_mode_cannot_honour():
    """A silently dropped mod_freq returns a normal-looking SimResult with no
    modulation in it, and the EVM then reads as noise-limited."""
    mod = np.zeros(5_000)
    mod[1000:] = 1e6
    bb = presets.adpll_bb_100m_10g()
    with pytest.raises(TypeError, match="mod_freq"):
        bb.simulate(5_000, mod_freq=mod)
    with pytest.raises(TypeError, match="tdc_cal"):
        presets.adpll_bb_100m_10g().simulate(5_000, tdc_cal=object())
    with pytest.raises(TypeError, match="dtc_gain_init_error"):
        presets.adpll_100m_10g().simulate(5_000, dtc_gain_init_error=0.05)
    # the supported combinations still run
    presets.adpll_100m_10g().simulate(3_000, mod_freq=np.zeros(3_000))
    presets.adpll_bb_100m_10g().simulate(3_000, dtc_gain_init_error=0.02)


def test_fll_stability_says_which_architectures_have_an_fll():
    from pllsim.settling import fll_stability
    assert fll_stability(presets.sspll_19p2m_4p8g())["margin"] > 0
    for nm in ("cppll_19p2m_4p8g", "adpll_100m_10g", "ilcm_250m_12g",
               "mdll_150m_2p4g"):
        with pytest.raises(TypeError, match="no FLL hand-off"):
            fll_stability(presets.ALL_PRESETS[nm]())


def test_unconverged_calibration_is_flagged_not_silently_reported():
    """bench_dartizio23 gear-shifts its DTC LMS at 100k cycles; below that the
    jitter is dominated by an uncalibrated fractional spur."""
    short = presets.bench_dartizio23_adpllbb_500m_9p2515g().simulate(80_000, seed=1)
    assert short.jitter_fs > 1000            # ~20 ps, not the 78 fs headline
    assert any("still settling" in n for n in short.notes), short.notes
    long = presets.bench_dartizio23_adpllbb_500m_9p2515g().simulate(250_000, seed=1)
    assert long.jitter_fs < 150
    assert not any("still settling" in n for n in long.notes)


# ------------------------------------------- knobs that only some engines read
@pytest.mark.parametrize("preset", ["cppll_19p2m_4p8g", "sspll_19p2m_4p8g",
                                    "spll_100m_8g", "adpll_100m_10g",
                                    "mdll_150m_2p4g"])
def test_tuning_nonlinearity_reaches_every_engine_that_has_a_tuning_law(preset):
    """nl1/nl2 live on the shared OscConfig, so an engine that computes
    f0 + gain*ctrl by hand accepts them and ignores them."""
    # a locked loop lands on fout whatever the tuning law is, so the tell is
    # the settled CONTROL value: it has to move to compensate the compression
    p = presets.ALL_PRESETS[preset]()
    base = p.simulate(20_000, seed=1).ctrl[-2000:].mean()
    q = presets.ALL_PRESETS[preset]()
    v = q.cfg.osc.v_for(q.cfg.fout)
    q.cfg.osc = replace(q.cfg.osc, nl1=-0.2 / max(abs(v), 1e-9))
    moved = q.simulate(20_000, seed=1).ctrl[-2000:].mean()
    assert abs(moved - base) > 0.01 * max(abs(base), 1e-9), (
        f"{preset} ignores Kvco nonlinearity: control settled at {base:.6g} "
        f"either way")


def test_ilcm_rejects_tuning_knobs_it_cannot_honour():
    """The ILCM's FTL corrects frequency directly in Hz — there is no v->f law
    for nl1/nl2/v_max to act on, so accepting them would be a silent no-op."""
    from pllsim.arch.ilcm import ILCMConfig
    c = presets.ilcm_250m_12g().cfg
    with pytest.raises(ValueError, match="does not evaluate a tuning law"):
        ILCMConfig(fref=c.fref, fout=c.fout, osc=replace(c.osc, nl1=-0.05))
    with pytest.raises(ValueError, match="does not evaluate a tuning law"):
        ILCMConfig(fref=c.fref, fout=c.fout, osc=replace(c.osc, v_max=1.0))


def test_realignment_architectures_report_the_same_jitter_quantity():
    """ILCM and MDLL both reset accumulated phase once per reference period,
    so both must integrate the oversampled phase or neither does."""
    il = presets.ilcm_250m_12g().simulate(40_000, seed=1)
    md = presets.mdll_150m_2p4g().simulate(40_000, seed=1)
    for sim in (il, md):
        assert sim.spurs_fft, "no spur table: fine_oversample disabled"
        assert any("intra-period" in n for n in sim.notes), sim.notes
    coarse = presets.ilcm_250m_12g().simulate(40_000, seed=1, fine_oversample=0)
    assert any("NOT included" in n for n in coarse.notes)


def test_no_spur_reported_when_there_is_nothing_to_report():
    """-600 dBc from log10(1e-30) reads as 'spurless by design'."""
    for nm in ("ilcm_250m_12g", "mdll_150m_2p4g"):
        assert presets.ALL_PRESETS[nm]().analyze().spurs_analytic == {}
    ar = presets.ilcm_250m_12g().analyze(f_free_error=2e6)
    assert -60 < ar.spurs_analytic["inj_spur_ref_offset"] < 0


def test_adpll_tdc_tabulates_its_fractional_spur():
    """TDC mode takes a fractional FCW natively, so the beat is really there."""
    p = presets.adpll_100m_10g()
    assert p.cfg.fcw % 1.0 > 0
    assert any("fractional FCW" in n for n in p.analyze().notes)
    spurs = [v for v in p.simulate(200_000, seed=1).spurs_fft.values()
             if np.isfinite(v)]
    assert spurs and max(spurs) > -90      # ~-72 dBc at 0.6 MHz


def test_selector_will_not_recommend_an_engine_that_cannot_modulate():
    from pllsim.selector import Requirement, select
    from pllsim.modulation import supports_two_point, two_point_presets
    rep = select(Requirement(fref=40e6, fout=5.0125e9, jitter_fs_max=2000,
                             modulation=True))
    for c in rep.candidates:
        if c.feasible:
            assert supports_two_point(c.pll)
    assert rep.best is not None and supports_two_point(rep.best.pll)
    # and the GUIs read the same predicate rather than their own name list
    assert "adpll_bb_100m_10g" not in two_point_presets()
    assert "adpll_100m_10g" in two_point_presets()
