"""pllsim.fit: CSV import, Leeson fit, closed-loop estimators, attribution."""
import io

import numpy as np

from pllsim import presets
from pllsim.blocks.oscillator import OscConfig
from pllsim.core.jitter import ldbc_from_sphi
from pllsim.fit import (attribute_budget, fit_closed_loop, fit_leeson,
                        load_pn_csv)


def test_load_pn_csv_formats():
    raw = ("# instrument header\n"
           "Offset Frequency (Hz); Phase Noise (dBc/Hz)\n"
           "1e3; -95.2\n1e4, -105.0\n1e5\t-115.5\n1e6 -125.0\n")
    f, l = load_pn_csv(io.StringIO(raw))
    assert f.tolist() == [1e3, 1e4, 1e5, 1e6]
    assert l[0] == -95.2 and l[-1] == -125.0


def test_fit_leeson_roundtrip():
    osc = OscConfig(f0=6e9, gain=60e6, pn_dbchz=-121.0, pn_foffset=1e6,
                    pn_f1f3=3e5, pn_floor_dbchz=-150.0)
    f = np.geomspace(1e3, 100e6, 100)
    rng = np.random.default_rng(0)
    l = ldbc_from_sphi(osc.leeson().psd(f)) + rng.normal(0, 0.5, f.size)
    lee = fit_leeson(f, l)
    assert abs(lee.pn_dbchz - (-121.0)) < 1.0
    assert 0.7 * 3e5 < lee.pn_f1f3 < 1.4 * 3e5
    assert abs(lee.pn_floor_dbchz - (-150.0)) < 1.0
    assert lee.residual_db_rms < 1.0


def test_fit_closed_loop_plateau_and_corner():
    pll = presets.sspll_19p2m_4p8g()
    ar = pll.analyze()
    sel = (ar.f >= 1e3) & (ar.f <= 100e6)
    rng = np.random.default_rng(1)
    l = ldbc_from_sphi(ar.pn_breakdown["total"][sel]) \
        + rng.normal(0, 0.5, int(sel.sum()))
    cl = fit_closed_loop(ar.f[sel], l)
    i200k = np.searchsorted(ar.f, 2e5)
    true_ib = ldbc_from_sphi(ar.pn_breakdown["total"][i200k])
    assert abs(cl.inband_dbchz - true_ib) < 2.0
    # corner within a factor of 2 of the true UGB (f_3db > UGB by design)
    assert 0.5 * ar.loop.f_ugb < cl.f_ugb < 2.0 * ar.loop.f_ugb
    assert ar.loop.f_ugb < cl.f_3db < 3.0 * ar.loop.f_ugb


def test_attribute_budget_flags_vco_group():
    sick = presets.spll_frac_52m_6p253g()
    sick.cfg.osc.pn_dbchz = -114.0          # VCO 4 dB hot
    ar = sick.analyze()
    sel = (ar.f >= 3e3) & (ar.f <= 40e6)
    rng = np.random.default_rng(2)
    l = ldbc_from_sphi(ar.pn_breakdown["total"][sel]) \
        + rng.normal(0, 0.3, int(sel.sum()))
    att = attribute_budget(presets.spll_frac_52m_6p253g(), ar.f[sel], l)
    vco_g = next(g for g in att.groups if "vco" in g)
    assert 1.8 < att.factors[vco_g] < 3.5      # truth: x2.51 (+4 dB)
    assert att.residual_db_rms < 1.0
    # groups exist: flat-through-H sources are clustered, not separated
    assert any(len(g) > 1 for g in att.groups)
