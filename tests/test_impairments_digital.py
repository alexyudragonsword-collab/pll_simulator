"""TDC INL, BBPD metastability, injection pulling and named corners."""
import dataclasses
from dataclasses import replace

import numpy as np
import pytest

from pllsim import corners, presets
from pllsim.blocks.tdc import BBPD, TDCConfig, meta_gain_penalty
from pllsim.core.tdcspurs import inl_fourier_coeffs, tdc_inl_spur_table


# ---------------------------------------------------------------- TDC INL
def _tdc(inl, fout=10e9, n_bits=8):
    """A TDC whose range is exactly one output period, so span = 1.

    That is the only geometry in which the INL the loop walks is the INL as
    declared, which is what the closed-form assertions below are written for.
    """
    code_max = (1 << n_bits) - 1
    return TDCConfig(t_res=(1.0 / fout) / code_max, n_bits=n_bits, inl_sin=inl)


def test_integer_cycle_inl_is_a_single_harmonic():
    """A whole number of INL cycles across the range is one Fourier term."""
    ck = inl_fourier_coeffs((2e-12, 3, 0.0), n_harm=8)
    assert ck[2] == pytest.approx(2e-12, rel=1e-3)     # k = 3
    assert np.max(np.delete(ck, 2)) < 1e-15


def test_a_partly_swept_range_spreads_one_cycle_over_every_harmonic():
    """The loop walks one output period, not the whole code range.

    A TDC is built with range > Tosc on purpose, so an INL declared as three
    whole cycles across the range presents 3*span cycles to the loop.  That is
    discontinuous at the wrap, and the wrap is what radiates: the line at k=3
    drops and every other k comes up out of nothing.
    """
    full = inl_fourier_coeffs((2e-12, 3, 0.0), 1.0, n_harm=8)
    part = inl_fourier_coeffs((2e-12, 3, 0.0), 0.78, n_harm=8)
    assert part[2] < 0.6 * full[2], "the declared line must lose energy"
    assert part[1] > 0.2 * full[2], "and the neighbours must gain it"
    # nothing is created: the spread is a redistribution, not a gain
    assert np.sum(part ** 2) < 1.2 * np.sum(full ** 2)


def test_code_span_is_the_period_over_the_range():
    from pllsim.core.tdcspurs import code_span
    assert code_span(_tdc(()), 10e9) == pytest.approx(1.0)
    # the preset's TDC deliberately overshoots one period
    span = code_span(presets.adpll_100m_10g().cfg.tdc, 10e9)
    assert 0.7 < span < 0.85


def test_inl_spur_lands_on_the_beat_harmonic():
    """k cycles of INL put a tone at fold(k*frac)*fref, not at frac*fref."""
    frac, fref = 0.13, 100e6
    tab = tdc_inl_spur_table(_tdc((2e-12, 3, 0.0)), frac, fref, 10e9)
    want = min((3 * frac) % 1.0, 1.0 - (3 * frac) % 1.0) * fref
    assert len(tab) == 1
    off, dbc = next(iter(tab.items()))
    assert off == pytest.approx(want, rel=1e-6)
    # 2*pi*fout*amp/2 with no loop shaping
    assert dbc == pytest.approx(20 * np.log10(np.pi * 10e9 * 2e-12), abs=0.1)


def test_no_inl_spur_on_an_integer_channel():
    """With frac = 0 the TDC sits on one code: its INL is an offset, not a tone."""
    assert tdc_inl_spur_table(_tdc((2e-12, 3, 0.0)), 0.0, 100e6, 10e9) == {}


@pytest.mark.parametrize("amp_ps", [2.0, 6.0])
def test_predicted_inl_spur_matches_the_time_domain(amp_ps):
    """The cross-domain check this mechanism never had.

    Without it the span error above sat in the library reading like a plain
    answer: analyze() said -24.2 dBc where simulate() measured -28.5, and
    nothing compared the two.  A 2-cycle INL on the 0.503 channel folds to
    600 kHz, well inside the loop, and the preset's own quantization sits at
    -104 dBc there -- so what is left is the INL alone.
    """
    p = presets.adpll_100m_10g()
    p.cfg.tdc.inl_sin = (amp_ps * 1e-12, 2, 0.0)
    want = p.analyze().spurs_analytic["frac_spur@600000Hz"]
    got = p.simulate(120000, noise=False, calibration=False, seed=1).spurs_fft
    assert got[600e3] == pytest.approx(want, abs=1.5)


def test_tdc_adpll_now_predicts_its_fractional_spurs():
    """It used to hand back an empty table and point at simulate()."""
    p = presets.adpll_100m_10g()
    p.cfg.fout = 100.503 * p.cfg.fref
    bare = p.analyze()
    assert not any(k.startswith("frac_spur") for k in bare.spurs_analytic)
    assert any("ideal TDC" in n for n in bare.notes)

    p.cfg.tdc = replace(p.cfg.tdc, inl_sin=(1.5e-12, 2, 0.4))
    withinl = p.analyze()
    spurs = {k: v for k, v in withinl.spurs_analytic.items()
             if k.startswith("frac_spur")}
    assert spurs, "a declared INL is a deterministic tone generator"
    assert not any("ideal TDC" in n for n in withinl.notes)


def test_inl_spur_scales_with_the_inl_amplitude():
    def spur(amp):
        p = presets.adpll_100m_10g()
        p.cfg.fout = 100.503 * p.cfg.fref
        p.cfg.tdc = replace(p.cfg.tdc, inl_sin=(amp, 2, 0.0))
        return max(v for k, v in p.analyze().spurs_analytic.items()
                   if k.startswith("frac_spur"))
    assert spur(4e-12) - spur(1e-12) == pytest.approx(20 * np.log10(4), abs=0.3)


# ------------------------------------------------------- BBPD metastability
def test_metastability_costs_gain_in_closed_form():
    """Kbb(W)/Kbb(0) = exp(-W^2/2 sigma^2); a window of sigma is 4.34 dB."""
    assert meta_gain_penalty(0.0, 1e-12) == 1.0
    assert meta_gain_penalty(1e-12, 1e-12) == pytest.approx(np.exp(-0.5))
    assert 20 * np.log10(meta_gain_penalty(1e-12, 1e-12)) == pytest.approx(-4.34, abs=0.02)


def test_metastability_matches_a_measured_characteristic():
    """The closed form against the empirical slope of E[out|dt]."""
    rng = np.random.default_rng(0)
    sigma, w = 1e-12, 0.8e-12
    bb = BBPD(sigma, rng, meta_window_s=w)
    dts = np.array([-0.2e-12, 0.2e-12])
    means = [np.mean([bb.sample(dt) for _ in range(200000)]) for dt in dts]
    slope = (means[1] - means[0]) / (dts[1] - dts[0])
    want = np.sqrt(2 / np.pi) / sigma * meta_gain_penalty(w, sigma)
    assert slope == pytest.approx(want, rel=0.05)


def test_metastability_widens_the_bbpd_loop_noise():
    p = presets.adpll_bb_100m_10g()
    clean = p.analyze()
    p.cfg.bb_meta_window_s = 1.5 * p.cfg.bb_jitter_rms_s
    meta = p.analyze()
    assert meta.jitter_fs > clean.jitter_fs
    assert meta.loop.f_ugb < clean.loop.f_ugb, "lost detector gain lowers the UGB"


def test_metastability_is_reported_from_the_time_domain():
    p = presets.adpll_bb_100m_10g()
    p.cfg.bb_meta_window_s = 2e-12
    sim = p.simulate(20000)
    assert sim.extra["bbpd_metastable_frac"] > 0.0
    assert any("coin flip" in n for n in sim.notes)


# ---------------------------------------------------------- injection pulling
def test_lock_range_helper_is_adler():
    from pllsim.blocks.oscillator import OscConfig
    assert OscConfig.lock_range_from_tank(1e10, 0.002, 8) == pytest.approx(1e10 * 0.002 / 16)


def test_capture_is_reported_as_capture_not_as_a_spur():
    p = presets.cppll_19p2m_4p8g()
    p.cfg.osc.pull_lock_range_hz = 5e6
    p.cfg.osc.pull_offset_hz = 1e6          # inside the lock range
    ar = p.analyze()
    assert "pull_spur" not in ar.spurs_analytic
    assert any("CAPTURED" in n for n in ar.notes)


def test_no_aggressor_means_no_key():
    ar = presets.cppll_19p2m_4p8g().analyze()
    assert "pull_spur" not in ar.spurs_analytic


@pytest.mark.parametrize("name,m_os", [
    ("cppll_19p2m_4p8g", 1), ("sspll_19p2m_4p8g", 1),
    ("spll_100m_8g", 1), ("adpll_100m_10g", None),
    ("adpll_bb_100m_10g", None), ("ilcm_250m_12g", 1),
    ("mdll_150m_2p4g", 16)])
def test_pulling_agrees_across_domains(name, m_os):
    """Pulling is coupling into the tank, so all six engines must carry it.

    m_os picks the record the analytic actually describes.  For the
    injection-locked pair that matters and is not a fudge: the expression is
    the sideband referred through the realignment NTF, which is the phase error
    AT the injection instants.  An oversampled record additionally carries the
    intra-period ramp, worth +4.4 dB on the ILCM at this offset -- the same
    ref-rate-versus-oversampled distinction their jitter already carries.  The
    MDLL needs M large enough to resolve its sawtooth, and its default 4 is not.
    """
    p = getattr(presets, name)()
    off = 0.2 * p.cfg.fref
    p.cfg.osc.pull_lock_range_hz = 0.02 * off     # beta = 0.02: narrowband
    p.cfg.osc.pull_offset_hz = off
    want = p.analyze().spurs_analytic["pull_spur"]
    kw = {} if m_os is None else {"fine_oversample": m_os}
    got = p.simulate(30000, noise=False, **kw).spurs_fft[off]
    assert abs(got - want) < 1.0, f"{name}: sim {got:.2f} vs analytic {want:.2f}"


def test_loop_suppresses_pulling_only_inside_its_bandwidth():
    """In band the loop rejects pulling; out of band it cannot.

    Which is why chasing a pulling spur in the loop filter does not work: past
    the bandwidth the reported sideband is the bare f_L/(2*df), untouched.
    """
    p = presets.cppll_19p2m_4p8g()
    f_ugb = p.analyze().loop.f_ugb
    f_l = 1e4
    p.cfg.osc.pull_lock_range_hz = f_l

    p.cfg.osc.pull_offset_hz = 0.05 * f_ugb
    got_in = p.analyze().spurs_analytic["pull_spur"]
    bare_in = 20 * np.log10(f_l / (0.05 * f_ugb) / 2)
    assert got_in < bare_in - 20, "in band the loop should reject it"

    p.cfg.osc.pull_offset_hz = 20.0 * f_ugb
    got_out = p.analyze().spurs_analytic["pull_spur"]
    bare_out = 20 * np.log10(f_l / (20.0 * f_ugb) / 2)
    assert abs(got_out - bare_out) < 0.5, "out of band the loop does nothing"


# ------------------------------------------------------------------ corners
def test_corner_moves_the_loop_and_does_not_retune_it():
    p = presets.cppll_19p2m_4p8g()
    nom = p.analyze().loop.f_ugb
    slow = corners.apply_corner(p, corners.SS_HOT).analyze().loop.f_ugb
    fast = corners.apply_corner(p, corners.FF_COLD).analyze().loop.f_ugb
    assert slow < nom < fast
    assert fast / slow > 1.8, "the whole point is that the bandwidth moves"


def test_apply_corner_leaves_the_original_alone():
    p = presets.cppll_19p2m_4p8g()
    before = p.cfg.osc.gain, p.cfg.cp.icp, p.cfg.filt.r2
    corners.apply_corner(p, corners.SS_HOT)
    assert (p.cfg.osc.gain, p.cfg.cp.icp, p.cfg.filt.r2) == before


def test_the_supply_axis_moves_the_oscillator_through_its_pushing_figure():
    """`vdd` is named by every standard corner; it has to read somewhere.

    An oscillator states how many Hz it moves per volt, so the corner's
    relative supply needs a nominal to become volts.  Without this the axis is
    a label on `SS_125C_0.9V` that no equation ever touches.
    """
    p = presets.cppll_19p2m_4p8g()
    p.cfg.osc.pushing_hz_v = 5e6            # 5 MHz/V, a plain LC number
    f0 = p.cfg.osc.f0
    low = corners.apply_corner(p, corners.Corner("lo", vdd=0.9)).cfg.osc.f0
    high = corners.apply_corner(p, corners.Corner("hi", vdd=1.1)).cfg.osc.f0
    assert low == pytest.approx(f0 - 0.5e6)
    assert high == pytest.approx(f0 + 0.5e6)

    # a 1.8 V part moves 1.8x further for the same relative sag
    wide = corners.Corner("lo18", vdd=0.9, vdd_nominal_v=1.8)
    assert corners.apply_corner(p, wide).cfg.osc.f0 == pytest.approx(f0 - 0.9e6)


def test_the_supply_axis_does_nothing_without_a_pushing_figure():
    """No pushing number means no claim about supply sensitivity.

    Inventing one would be worse than the axis being inert, so a preset that
    has not characterised it must come back untouched.
    """
    p = presets.cppll_19p2m_4p8g()
    assert p.cfg.osc.pushing_hz_v == 0.0
    got = corners.apply_corner(p, corners.Corner("lo", vdd=0.5)).cfg.osc.f0
    assert got == p.cfg.osc.f0


def _sub_configs(cfg):
    """Every dataclass hanging off `cfg`, one level down and through frac."""
    out = []
    for f in dataclasses.fields(cfg):
        v = getattr(cfg, f.name)
        if dataclasses.is_dataclass(v):
            out.append(v)
            out.extend(x for x in (getattr(v, g.name)
                                   for g in dataclasses.fields(v))
                       if dataclasses.is_dataclass(x))
    return out


@pytest.mark.parametrize("corner", [corners.TT, corners.SS_HOT])
def test_a_corner_copy_shares_no_sub_config_with_the_original(corner):
    """Including TT, which scales nothing and so rebuilds nothing.

    `dataclasses.replace` only rebuilds the level it is handed, so an untouched
    sub-block would stay shared.  `corner_report` runs TT first, so a caller
    that edited that row's config would silently corrupt every later corner.
    """
    p = presets.cppll_19p2m_4p8g()
    q = corners.apply_corner(p, corner)
    assert q.cfg is not p.cfg
    shared = {id(s) for s in _sub_configs(p.cfg)} & \
             {id(s) for s in _sub_configs(q.cfg)}
    assert not shared, "a sub-config is still aliased to the nominal"

    # and the aliasing that matters: editing the copy must not move the original
    before = p.cfg.osc.f0
    q.cfg.osc.f0 *= 2.0
    assert p.cfg.osc.f0 == before


def test_typical_corner_is_a_no_op():
    p = presets.cppll_19p2m_4p8g()
    assert corners.apply_corner(p, corners.TT).analyze().jitter_fs == \
        pytest.approx(p.analyze().jitter_fs)


@pytest.mark.parametrize("name", ["cppll_19p2m_4p8g", "sspll_19p2m_4p8g",
                                  "spll_100m_8g", "adpll_100m_10g",
                                  "adpll_bb_100m_10g", "ilcm_250m_12g",
                                  "mdll_150m_2p4g"])
def test_every_architecture_responds_to_a_corner(name):
    """A corner that changes nothing reads as immunity, not as a gap.

    The injection-locked multipliers set their own bandwidth structurally, so
    component scaling alone leaves them identical -- which is why the corner
    carries an oscillator phase-noise axis as well.
    """
    p = getattr(presets, name)()
    rows = corners.corner_report(p)
    assert len(rows) == 5 and all(r.error is None for r in rows)
    jit = [r.jitter_fs for r in rows]
    ugb = [r.f_ugb_hz for r in rows]
    moved = (max(jit) / min(jit) > 1.03) or (max(ugb) / min(ugb) > 1.03)
    assert moved, f"{name} did not move at any corner"


def test_a_corner_that_will_not_build_is_a_row_not_a_crash():
    """One impossible corner must not abort the sweep -- it is a finding."""
    p = presets.cppll_19p2m_4p8g()
    bad = corners.Corner("impossible", cap=0.0)     # zero capacitors
    rows = corners.corner_report(p, corners=[corners.TT, bad, corners.FF_COLD])
    assert rows[0].error is None and rows[2].error is None
    assert rows[1].error is not None
    assert "FAILED" in corners.corner_table(rows)


def test_worst_case_picks_the_worst_finite_row():
    rows = [corners.CornerRow("a", 100.0, 1e6, 60, 1, []),
            corners.CornerRow("b", 300.0, 1e6, 60, 1, []),
            corners.CornerRow("c", float("nan"), float("nan"), 0, 0, [], "boom")]
    assert corners.worst_case(rows).corner == "b"
