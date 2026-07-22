"""Second-order effects: Kvco nonlinearity, pushing, doubler, band select."""
import numpy as np
import pytest

from pllsim.arch.cppll import CPPLL, CPPLLConfig
from pllsim.blocks.chargepump import CPConfig
from pllsim.blocks.loopfilter import FilterDesign
from pllsim.blocks.oscillator import OscConfig

BASE = dict(fref=19.2e6, fout=4.8e9,
            cp=CPConfig(icp=1.5e-3, mismatch_pct=2.0, leakage_a=1e-9,
                        t_reset=200e-12),
            filt=FilterDesign(c1=680e-12, r2=20e3, c2=3.3e-12, r3=2e3,
                              c3=2.2e-12),
            ref_pn_dbchz=-162.0)
PN = dict(pn_dbchz=-122.0, pn_foffset=1e6, pn_f1f3=3e5, pn_floor_dbchz=-155.0)


def test_kvco_nonlinearity_shifts_loop_and_still_locks():
    osc = OscConfig(f0=4.6e9, gain=60e6, **PN, nl1=-0.05)
    v = osc.v_for(4.8e9)
    assert osc.kvco_at(v) < 0.7 * osc.gain          # compressed at the edge
    pll = CPPLL(CPPLLConfig(**BASE, osc=osc))
    ar = pll.analyze()
    ar_lin = CPPLL(CPPLLConfig(**BASE,
                               osc=OscConfig(f0=4.6e9, gain=60e6, **PN))).analyze()
    assert ar.loop.f_ugb < 0.75 * ar_lin.loop.f_ugb
    sim = pll.simulate(50_000, seed=1, noise=False, f_start_offset=-20e6)
    assert abs(np.mean(sim.freq_out[-3000:]) - 4.8e9) < 1e3


def test_supply_pushing_spur_matches_analytic():
    osc = OscConfig(f0=4.75e9, gain=60e6, **PN, pushing_hz_v=50e6)
    pll = CPPLL(CPPLLConfig(**BASE, osc=osc))
    ar = pll.analyze()
    f_rip = 3e6
    sim = pll.simulate(150_000, seed=1, supply_ripple=(5e-3, f_rip))
    e_fr = np.interp(np.log10(f_rip), np.log10(ar.f), np.abs(ar.ntfs["err"].h))
    analytic = 20 * np.log10(50e6 * 5e-3 * e_fr / f_rip / 2)
    assert abs(sim.spurs_fft[f_rip] - analytic) < 2.0


def test_doubler_duty_error_spur_scales():
    spurs = []
    for de in (0.001, 0.004):
        osc = OscConfig(f0=4.75e9, gain=60e6, **PN)
        sim = CPPLL(CPPLLConfig(**BASE, osc=osc, ref_doubler_duty_err=de)) \
            .simulate(100_000, seed=1)
        spurs.append(sim.spurs_fft[9.6e6])
    assert abs((spurs[1] - spurs[0]) - 20 * np.log10(4.0)) < 2.0


def test_band_select_finds_band_and_locks():
    osc = OscConfig(f0=4.6e9, gain=30e6, **PN, band_step_hz=150e6, n_bands=32)
    sim = CPPLL(CPPLLConfig(**BASE, osc=osc)).simulate(60_000, seed=1)
    # correct band: f0 offset +200 MHz needs band ~ 15.5 + 200/150
    assert sim.extra["band"] in (16, 17, 18)
    assert len(sim.cal_traces["band_select"]) <= 6   # ~log2(32) trials
    assert abs(np.mean(sim.freq_out[-5000:]) - 4.8e9) < 5e4
