"""Fractional-N SSPLL and ILCM timing calibration."""
import numpy as np
import pytest

from pllsim.arch.cppll import FracConfig
from pllsim.arch.ilcm import ILCM, ILCMConfig
from pllsim.arch.sspll import SSPLL, SSPLLConfig
from pllsim.blocks.dtc import DTCConfig
from pllsim.blocks.loopfilter import FilterDesign
from pllsim.blocks.oscillator import OscConfig
from pllsim.blocks.sampler import SamplerConfig
from pllsim.calibration.lms import SignSignLMS

FREF, FRAC = 19.2e6, 0.2503
FOUT = (250 + FRAC) * FREF
BASE = dict(
    fref=FREF, fout=FOUT,
    osc=OscConfig(f0=4.755e9, gain=60e6, pn_dbchz=-122.0, pn_foffset=1e6,
                  pn_f1f3=3e5, pn_floor_dbchz=-155.0),
    sampler=SamplerConfig(amp_v=0.4, c_samp=60e-15, gm=1e-3,
                          pulse_width=150e-12, pedestal_v=1e-3),
    filt=FilterDesign(c1=680e-12, r2=20e3, c2=2.2e-12, r3=2e3, c3=1e-12),
    ref_pn_dbchz=-162.0, fll_i=1e-6, fll_engage=2e6, fll_release=400e3)
DTC = DTCConfig(t_res=250e-15, n_bits=10, jitter_rms_s=30e-15)


def test_mash_order_guard():
    with pytest.raises(ValueError, match="1st-order EFM"):
        SSPLLConfig(**BASE, frac=FracConfig(frac=FRAC, mash_order=3, dtc=DTC))


def test_frac_matches_fout_guard():
    with pytest.raises(ValueError, match="does not match"):
        SSPLLConfig(**BASE, frac=FracConfig(frac=0.5, mash_order=1, dtc=DTC))


def test_perfect_dtc_nearly_free():
    cfg = SSPLLConfig(**BASE, frac=FracConfig(frac=FRAC, mash_order=1, dtc=DTC))
    sim = SSPLL(cfg).simulate(150_000, seed=2)
    assert sim.jitter_fs < 180                     # ~ the integer-N level
    assert abs(np.mean(sim.freq_out[-20_000:]) - FOUT) < 5e4


def test_gain_cal_converges_and_kills_spur():
    eps = 0.08
    cfg_u = SSPLLConfig(**BASE, frac=FracConfig(frac=FRAC, mash_order=1, dtc=DTC))
    sim_u = SSPLL(cfg_u).simulate(150_000, seed=2, dtc_gain_init_error=eps)

    cal = SignSignLMS(init=1.0, mu=5e-6, gear_shift_n=60_000, mu_final=5e-7)
    cfg_c = SSPLLConfig(**BASE, frac=FracConfig(frac=FRAC, mash_order=1,
                                                dtc=DTC, dtc_cal=cal))
    sim_c = SSPLL(cfg_c).simulate(150_000, seed=2, dtc_gain_init_error=eps)

    assert abs(cal.value - 1 / (1 + eps)) < 0.01
    assert sim_c.jitter_fs < sim_u.jitter_fs / 3
    # near-integer folded spur at 4*frac-1 = 0.0012*fref = 23.04 kHz
    spur_u = sim_u.spurs_fft.get(23040.0, 0.0)
    spur_c = sim_c.spurs_fft.get(23040.0, float("nan"))
    assert np.isnan(spur_c) or spur_c < spur_u - 20.0


def test_ilcm_timing_cal():
    base = dict(
        fref=250e6, fout=12e9,
        osc=OscConfig(f0=12e9, gain=1.0, pn_dbchz=-105.0, pn_foffset=1e6,
                      pn_f1f3=5e5, pn_floor_dbchz=-145.0),
        beta=0.6, inj_jitter_rms_s=15e-15, ref_pn_dbchz=-155.0, ftl_f_lsb=20e3)
    s_off = ILCM(ILCMConfig(**base, ftl_det_offset_s=3e-12)).simulate(
        100_000, seed=1, f_free_error=1e6, fine_oversample=4)
    s_cal = ILCM(ILCMConfig(**base, ftl_det_offset_s=3e-12, timing_cal=True,
                            timing_cal_step_s=20e-15)).simulate(
        100_000, seed=1, f_free_error=1e6, fine_oversample=4)
    assert s_off.spurs_fft[250e6] > -40.0          # offset creates a big spur
    spur_c = s_cal.spurs_fft[250e6]
    # NaN = below the local noise floor, i.e. fully killed
    assert np.isnan(spur_c) or spur_c < s_off.spurs_fft[250e6] - 30.0
    assert abs(s_cal.cal_traces["inj_timing"][-1] + 3e-12) < 0.3e-12
