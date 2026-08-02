"""dtcspurs: deterministic fractional-spur prediction (INL/quant/gain)."""
import numpy as np

from pllsim import presets
from pllsim.arch.cppll import frac_spur_offsets
from pllsim.core.dtcspurs import dtc_error_sequence, dtc_spur_table


def _wu():
    pll = presets.spll_frac_52m_6p253g()
    pll.cfg.frac.dtc.gain_error_residual = 0.0
    return pll


def _target_of(cfg):
    d = cfg.frac.dtc
    return lambda r: -r / cfg.fout - d.range_s / 2.0


def test_error_sequence_bounded_and_zero_mean():
    pll = _wu()
    c = pll.cfg
    err = dtc_error_sequence(c.frac, _target_of(c), 1 << 12)
    assert abs(err.mean()) < 1e-20
    # pure quantization: bounded by half an LSB around the removed mean
    assert np.max(np.abs(err)) <= c.frac.dtc.t_res


def test_spur_offsets_match_folding():
    pll = _wu()
    c = pll.cfg
    tab = dtc_spur_table(c.frac, _target_of(c), c.fref, c.fout,
                         gain_eps=0.01)
    expected = frac_spur_offsets(c.frac.frac, c.fref, kmax=6)
    for off in tab:
        assert any(abs(off - e) < 1.0 for e in expected)


def test_gain_residual_scales_20db_per_decade():
    pll = _wu()
    c = pll.cfg
    # k=1 tone folds to 13.0156 MHz for frac=0.2503
    t1 = dtc_spur_table(c.frac, _target_of(c), c.fref, c.fout, gain_eps=0.01)
    t2 = dtc_spur_table(c.frac, _target_of(c), c.fref, c.fout, gain_eps=0.1)
    k = round(0.2503 * 52e6, 3)
    assert 18.0 < t2[k] - t1[k] < 22.0


def test_prediction_matches_noise_free_sim():
    """The gold check: 500 fs sine INL, prediction vs deterministic sim."""
    pll = _wu()
    pll.cfg.frac.dtc.inl_sin = (500e-15, 1.0, 0.3)
    ar = pll.analyze()
    pred = {round(float(k.split("@")[1][:-2])): v
            for k, v in ar.spurs_analytic.items()
            if k.startswith("frac_spur")}
    sim = pll.simulate(120_000, seed=5, noise=False, calibration=False)
    meas = {round(f): v for f, v in sim.spurs_fft.items() if np.isfinite(v)}
    # the two strongest tones must agree within 3 dB
    strongest = sorted(pred, key=lambda o: -pred[o])[:2]
    for off in strongest:
        assert off in meas
        assert abs(pred[off] - meas[off]) < 3.0, \
            f"@{off}: pred {pred[off]:.1f} vs sim {meas[off]:.1f}"


def test_all_frac_archs_carry_spur_table():
    for nm in ("cppll_frac_38p4m_6g", "sspll_frac_19p2m_4p806g",
               "spll_frac_52m_6p253g", "adpll_bb_100m_10g"):
        ar = presets.ALL_PRESETS[nm]().analyze()
        tab = [k for k in ar.spurs_analytic if k.startswith("frac_spur")]
        assert tab, f"{nm}: no frac_spur entries in spurs_analytic"
