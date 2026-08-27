"""SSPLL: metrics, FLL acquisition/false-lock, cross-domain PSD."""
import numpy as np
import pytest

from pllsim.arch.sspll import SSPLL, SSPLLConfig
from pllsim.blocks.loopfilter import FilterDesign
from pllsim.blocks.oscillator import OscConfig
from pllsim.blocks.sampler import SamplerConfig
from pllsim.validation import compare_domains  # noqa: I001


@pytest.fixture(scope="module")
def pll():
    return SSPLL(SSPLLConfig(
        fref=19.2e6, fout=4.8e9,
        osc=OscConfig(f0=4.75e9, gain=60e6, pn_dbchz=-122.0, pn_foffset=1e6,
                      pn_f1f3=3e5, pn_floor_dbchz=-155.0),
        sampler=SamplerConfig(amp_v=0.4, c_samp=60e-15, gm=1e-3,
                              pulse_width=150e-12, pedestal_v=1e-3),
        filt=FilterDesign(c1=680e-12, r2=20e3, c2=2.2e-12, r3=2e3, c3=1e-12),
        ref_pn_dbchz=-162.0,
        fll_i=1e-6, fll_engage=2e6, fll_release=400e3))


def test_no_n_penalty_on_cp_noise(pll):
    """SSPLL beats an equivalent CPPLL (ex01 config lands ~260 fs)."""
    ar = pll.analyze()
    assert 80 < ar.jitter_fs < 220
    assert 0.6e6 < ar.loop.f_ugb < 2.5e6
    assert ar.loop.pm_deg > 50


def test_fll_acquires_and_hands_off(pll):
    sim = pll.simulate(300_000, seed=1, f_start_offset=-25e6)
    eng = sim.cal_traces["fll_engaged"]
    handoff = np.where(np.diff(eng) < 0)[0]
    assert handoff.size >= 1
    assert sim.lock_time_s is not None
    assert abs(np.mean(sim.freq_out[-20_000:]) - 4.8e9) < 5e4
    # FLL quiet after handoff (no chatter)
    assert eng[handoff[0] + 1000:].sum() == 0


def test_false_lock_without_fll(pll):
    sim = pll.simulate(50_000, seed=1, f_start_offset=-25e6, fll_enable=False)
    ferr = np.mean(sim.freq_out[-5000:]) - 4.8e9
    # parks at an integer multiple of fref away, not at the target
    assert abs(ferr) > 5e6
    assert abs(ferr / 19.2e6 - round(ferr / 19.2e6)) < 0.05


def test_cross_domain_psd(pll):
    """3 dB: UGB/fref ~ 1/16 here, discrete-loop peaking deviation is larger
    than in the CPPLL case (1/20)."""
    c = compare_domains(pll, n_cycles=200_000, seed=3)
    assert c.skipped == [], c.skipped
    assert c.worst_db < 3.0, [f"{b.f_lo:.3g}-{b.f_hi:.3g}: {b.err_db:+.2f}"
                              for b in c.bands]
