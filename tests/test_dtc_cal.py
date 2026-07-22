"""Fractional-N + DTC calibration behavior."""
import numpy as np
import pytest

from pllsim.arch.cppll import CPPLL, CPPLLConfig, FracConfig, frac_spur_offsets
from pllsim.blocks.chargepump import CPConfig
from pllsim.blocks.dtc import DTCConfig
from pllsim.blocks.loopfilter import FilterDesign
from pllsim.blocks.oscillator import OscConfig
from pllsim.calibration.lms import LMSGainCal, LUTCal, SignSignLMS

FREF = 38.4e6
FOUT = (156 + 0.2525) * FREF
BASE = dict(
    fref=FREF, fout=FOUT,
    osc=OscConfig(f0=5.95e9, gain=80e6, pn_dbchz=-120.0, pn_foffset=1e6,
                  pn_f1f3=3e5, pn_floor_dbchz=-152.0),
    cp=CPConfig(icp=1.5e-3, mismatch_pct=1.0, leakage_a=1e-9, t_reset=150e-12),
    filt=FilterDesign(c1=470e-12, r2=15e3, c2=3.3e-12, r3=1.5e3, c3=2.2e-12),
    ref_pn_dbchz=-160.0,
)
DTC = dict(t_res=250e-15, n_bits=12, jitter_rms_s=30e-15)


def test_frac_spur_offsets():
    offs = frac_spur_offsets(0.2525, FREF)
    assert any(abs(o - 0.2525 * FREF) < 1 for o in offs)     # primary
    assert any(abs(o - 0.01 * FREF) < 1 for o in offs)       # 4*frac folds to 0.01


def test_gain_cal_converges_and_recovers_jitter():
    eps = 0.10
    # uncalibrated
    cfg_u = CPPLLConfig(**BASE, frac=FracConfig(frac=0.2525, mash_order=2,
                                                dtc=DTCConfig(**DTC)))
    sim_u = CPPLL(cfg_u).simulate(120_000, seed=2, dtc_gain_init_error=eps)
    # calibrated
    cal = SignSignLMS(init=1.0, mu=5e-6, gear_shift_n=70_000, mu_final=5e-7)
    cfg_c = CPPLLConfig(**BASE, frac=FracConfig(frac=0.2525, mash_order=2,
                                                dtc=DTCConfig(**DTC), dtc_cal=cal))
    sim_c = CPPLL(cfg_c).simulate(120_000, seed=2, dtc_gain_init_error=eps)

    assert abs(cal.value - 1 / (1 + eps)) < 0.01     # gain estimate within 1%
    assert sim_c.jitter_fs < sim_u.jitter_fs / 2.0   # >6 dB phase-power recovery
    assert sim_c.jitter_fs < 250.0                   # near integer-N baseline


def test_full_lms_also_converges():
    eps = -0.08
    cal = LMSGainCal(init=1.0, mu=2e-4, gear_shift_n=60_000, mu_final=2e-5)
    cfg = CPPLLConfig(**BASE, frac=FracConfig(frac=0.2525, mash_order=2,
                                              dtc=DTCConfig(**DTC), dtc_cal=cal))
    CPPLL(cfg).simulate(100_000, seed=5, dtc_gain_init_error=eps)
    assert abs(cal.value - 1 / (1 + eps)) < 0.015


def test_lut_cal_reduces_inl_jitter():
    inl = dict(inl_sin=(2e-12, 3.0, 0.7))
    mk_gain = lambda: SignSignLMS(init=1.0, mu=5e-6, gear_shift_n=100_000,
                                  mu_final=5e-7)
    cfg_off = CPPLLConfig(**BASE, frac=FracConfig(
        frac=0.2525, mash_order=2, dtc=DTCConfig(**DTC, **inl), dtc_cal=mk_gain()))
    sim_off = CPPLL(cfg_off).simulate(200_000, seed=2, dtc_gain_init_error=0.02)

    lut = LUTCal(k=32, lo=-2.0, hi=2.0, mu=1e-16)
    cfg_on = CPPLLConfig(**BASE, frac=FracConfig(
        frac=0.2525, mash_order=2, dtc=DTCConfig(**DTC, **inl),
        dtc_cal=mk_gain(), dtc_lut_cal=lut))
    sim_on = CPPLL(cfg_on).simulate(200_000, seed=2, dtc_gain_init_error=0.02)

    assert sim_on.jitter_fs < 0.8 * sim_off.jitter_fs   # >20% jitter reduction
    # LUT stays bounded (no runaway in sparsely visited bins)
    assert np.max(np.abs(lut.lut)) < 5e-12
