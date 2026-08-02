"""Golden RNM engines agree with the full simulate() in the locked state."""
import numpy as np

from pllsim import presets
from pllsim.export import rnm_golden as rg


def test_cppll_int_golden_locks_like_simulate():
    pll = presets.cppll_19p2m_4p8g()
    cols = rg.golden_cppll(pll.cfg, 30_000)
    sim = pll.simulate(30_000, noise=False, band_select=False)
    # locked state: same frequency and control voltage
    assert abs(np.mean(cols["fv"][-2000:]) - 4.8e9) < 2e3
    assert abs(np.mean(cols["fv"][-2000:]) - np.mean(sim.freq_out[-2000:])) < 2e3
    assert abs(np.mean(cols["vctrl"][-2000:]) - np.mean(sim.ctrl[-2000:])) < 2e-4


def test_cppll_frac_golden_mash_bittrue():
    pll = presets.cppll_frac_38p4m_6g()
    cfg = pll.cfg
    cols = rg.golden_cppll(cfg, 20_000)
    # residual sequence must be the bit-true MASH residue
    from pllsim.core.deltasigma import Mash11
    m = Mash11(cfg.frac.bits)
    for i in range(20_000):
        assert cols["residual"][i] == m.residual_ui()
        m.step(cfg.frac.frac_word)
    assert abs(np.mean(cols["fv"][-2000:]) - cfg.fout) < 5e3


def test_sspll_and_spll_goldens_lock():
    pll = presets.sspll_19p2m_4p8g()
    cols = rg.golden_sspll(pll.cfg, 30_000)
    assert abs(np.mean(cols["fv"][-2000:]) - 4.8e9) < 2e3
    pll2 = presets.spll_100m_8g()
    cols2 = rg.golden_spll(pll2.cfg, 30_000)
    assert abs(np.mean(cols2["fv"][-2000:]) - 8e9) < 5e3


def test_adpll_goldens_lock():
    pll = presets.adpll_100m_10g()
    cols = rg.golden_adpll_tdc(pll.cfg, 30_000)
    assert abs(np.mean(cols["fv"][-2000:]) - pll.cfg.fout) < 5e4
    sim = pll.simulate(30_000, noise=False)
    assert abs(np.mean(cols["fv"][-2000:]) - np.mean(sim.freq_out[-2000:])) < 5e4

    from pllsim.arch.adpll import ADPLLConfig, DLFConfig
    from pllsim.arch.cppll import FracConfig
    from pllsim.blocks.dtc import DTCConfig
    from pllsim.blocks.oscillator import OscConfig
    cfg = ADPLLConfig(
        fref=100e6, fout=100.503 * 100e6,
        osc=OscConfig(f0=10e9, gain=20e3, pn_dbchz=-112, pn_foffset=1e6,
                      pn_f1f3=4e5, pn_floor_dbchz=-150),
        dlf=DLFConfig(alpha=2.0, rho=2 ** -6), mode="dtc_bbpd",
        frac=FracConfig(frac=0.503, mash_order=2,
                        dtc=DTCConfig(t_res=250e-15, n_bits=12)),
        ref_pn_dbchz=-158.0)
    cols2 = rg.golden_adpll_bbpd(cfg, 40_000)
    assert abs(np.mean(cols2["fv"][-5000:]) - cfg.fout) < 5e5


def test_ilcm_mdll_goldens():
    pll = presets.ilcm_250m_12g()
    cols = rg.golden_ilcm(pll.cfg, 20_000, f_free_error=1e6)
    # FTL walks the drift out: residual phase step small at the end
    assert abs(cols["f_corr"][-1] + 1e6) < 5 * pll.cfg.ftl_f_lsb
    from pllsim.arch.mdll import MDLLConfig
    from pllsim.blocks.oscillator import OscConfig
    mcfg = MDLLConfig(fref=150e6, fout=2.4e9,
                      osc=OscConfig(f0=2.4e9, gain=100e3, pn_dbchz=-95,
                                    pn_foffset=1e6, pn_f1f3=8e5,
                                    pn_floor_dbchz=-140))
    cols2 = rg.golden_mdll(mcfg, 20_000, f_free_error=1e6)
    assert abs(cols2["tune"][-1] * mcfg.osc.gain + 1e6) < 5 * mcfg.tune_ki_lsb * mcfg.osc.gain * 10


def test_csv_roundtrip(tmp_path):
    cols = {"a": np.array([1.5, -2.25]), "b": np.array([0.0, 3.0])}
    p = rg.write_golden_csv(tmp_path / "g.csv", cols)
    lines = p.read_text().splitlines()
    assert lines[0] == "cycle,a,b"
    assert lines[1].startswith("0,1.5,")
