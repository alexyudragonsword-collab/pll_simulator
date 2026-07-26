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


# --- control-voltage range ------------------------------------------------

def test_an_unlimited_varactor_makes_the_band_bank_inert():
    """The reason the range had to exist, stated as a measurement.

    Without a control-voltage range one band reaches any frequency, so a coarse
    band bank changes nothing: configuring 33 bands leaves the analysis
    bit-identical and a band search always succeeds on whatever band it starts
    in.  A downstream model that configured bands and expected coarse tuning to
    matter would have been modelling it in appearance only.
    """
    flat = OscConfig(f0=4.6e9, gain=30e6, **PN)
    banded = OscConfig(f0=4.6e9, gain=30e6, **PN, band_step_hz=150e6, n_bands=33)
    assert not flat.v_limited and not banded.v_limited
    assert flat.band_range_hz(0) == (-np.inf, np.inf)
    # every band reaches the target, which is what makes the search vacuous
    assert all(banded.band_covers(4.8e9, b) for b in range(banded.n_bands))


def test_a_limited_varactor_gives_each_band_a_finite_reach():
    osc = OscConfig(f0=4.6e9, gain=30e6, **PN, band_step_hz=40e6, n_bands=33,
                    v_min=-1.0, v_max=1.0)
    assert osc.v_limited
    lo, hi = osc.band_range_hz(16)                 # the centre band
    assert lo == pytest.approx(4.6e9 - 30e6)
    assert hi == pytest.approx(4.6e9 + 30e6)
    assert osc.band_covers(4.61e9, 16)
    assert not osc.band_covers(4.8e9, 16)
    # some band reaches it, because the bank is sized so they overlap
    assert any(osc.band_covers(4.8e9, b) for b in range(osc.n_bands))


def test_a_bank_whose_bands_do_not_overlap_is_detectable():
    """The sizing mistake this found, made visible instead of unlockable.

    A band spans 2*gain*v_max and the bank steps by band_step_hz; with 60 MHz of
    span and 150 MHz of pitch there are 90 MHz holes between bands.  A target in
    a hole rails whichever band the search picks, which looks like a broken loop.
    The first version of the test above used exactly those numbers and failed for
    that reason, so the check is now a method rather than a comment.
    """
    holed = OscConfig(f0=4.6e9, gain=30e6, **PN, band_step_hz=150e6, n_bands=33,
                      v_min=-1.0, v_max=1.0)
    assert not holed.band_bank_is_continuous()
    assert holed.band_overlap_hz() == pytest.approx(-90e6)
    assert not any(holed.band_covers(4.8e9, b) for b in range(holed.n_bands))

    good = OscConfig(f0=4.6e9, gain=30e6, **PN, band_step_hz=40e6, n_bands=33,
                     v_min=-1.0, v_max=1.0)
    assert good.band_bank_is_continuous()
    assert good.band_overlap_hz() == pytest.approx(20e6)
    lo, hi = good.bank_range_hz()
    assert lo < 4.8e9 < hi

    # an unbounded varactor has no sizing constraint at all, and says so
    assert OscConfig(f0=4.6e9, gain=30e6, **PN, band_step_hz=150e6,
                     n_bands=33).band_overlap_hz() == float("inf")


def test_the_control_voltage_is_clamped_rather_than_extrapolated():
    """A varactor past its rail stops tuning; it does not keep going."""
    osc = OscConfig(f0=4.6e9, gain=30e6, **PN, v_min=-1.0, v_max=1.0)
    assert osc.freq_law(5.0) == pytest.approx(osc.freq_law(1.0))
    assert osc.freq_law(-5.0) == pytest.approx(osc.freq_law(-1.0))
    # v_for is deliberately NOT clamped: a caller has to be able to see that the
    # target needs a voltage the varactor does not have
    assert osc.v_for(4.7e9) > 1.0


def test_the_range_leaves_an_unbanded_loop_alone():
    """Every existing configuration has no range, so nothing moves."""
    osc = OscConfig(f0=4.75e9, gain=60e6, **PN)
    sim = CPPLL(CPPLLConfig(**BASE, osc=osc)).simulate(20_000, seed=1)
    limited = OscConfig(f0=4.75e9, gain=60e6, **PN, v_min=-5.0, v_max=5.0)
    same = CPPLL(CPPLLConfig(**BASE, osc=limited)).simulate(20_000, seed=1)
    np.testing.assert_allclose(sim.freq_out, same.freq_out)
