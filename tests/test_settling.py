"""Channel-hop settling and the FLL hand-off stability bound."""
import numpy as np

from pllsim import presets
from pllsim.settling import fll_stability, hop_settling


def test_cppll_hop_settles_freq_then_phase():
    pll = presets.cppll_19p2m_4p8g()
    r = hop_settling(pll, pll.cfg.fout - 100e6, n_cycles=100_000, seed=1)
    assert np.isfinite(r.t_phase_s)
    assert r.t_phase_s < 500e-6              # ~90 us typical
    assert r.t_freq_s <= r.t_phase_s * 1.5   # freq pull-in leads phase


def test_adpll_hop_order_of_magnitude_faster():
    ad = hop_settling(presets.adpll_100m_10g(), 10.0503e9 - 100e6,
                      n_cycles=60_000, seed=1)
    assert ad.t_phase_s < 30e-6              # digital loop: ~9 us


def test_fll_segment_scales_with_hop():
    pll = presets.spll_frac_52m_6p253g()
    r1 = hop_settling(pll, pll.cfg.fout - 20e6, n_cycles=120_000, seed=1)
    pll2 = presets.spll_frac_52m_6p253g()
    r2 = hop_settling(pll2, pll2.cfg.fout - 100e6, n_cycles=120_000, seed=1)
    assert np.isfinite(r1.t_phase_s) and np.isfinite(r2.t_phase_s)
    # charge-budget slew: ~5x the hop needs ~3-7x the FLL time
    ratio = r2.fll_engaged_s / r1.fll_engaged_s
    assert 3.0 < ratio < 7.0


def test_fll_stability_bound():
    # all FLL-assisted presets carry margin > 1 (hand-off guaranteed)
    for nm in ("sspll_19p2m_4p8g", "sspll_frac_19p2m_4p806g",
               "spll_100m_8g", "spll_frac_52m_6p253g"):
        st = fll_stability(presets.ALL_PRESETS[nm]())
        assert st["margin"] > 1.3, f"{nm}: margin {st['margin']:.2f}"
    # 4x the current violates the bound -> the documented limit cycle
    pll = presets.spll_frac_52m_6p253g()
    pll.cfg.fll_i *= 4.0
    assert fll_stability(pll)["margin"] < 1.0


def test_hop_works_on_free_running_architectures():
    """ILCM/MDLL take the start error as f_free_error, not f_start_offset."""
    for nm in ("ilcm_250m_12g", "mdll_150m_2p4g"):
        pll = presets.ALL_PRESETS[nm]()
        r = hop_settling(pll, pll.cfg.fout + 10e6, n_cycles=30_000, seed=1)
        assert r.f_from == pll.cfg.fout + 10e6
        assert 0.0 < r.t_freq_s < 1e-3          # the FTL pulls it in
