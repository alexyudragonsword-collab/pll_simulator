"""ADPLL: loop metrics, cross-domain PSD, KDCO/TDC calibration, BB mode."""
import numpy as np
import pytest

from pllsim import presets
from pllsim.arch.adpll import ADPLL, ADPLLConfig, DLFConfig
from pllsim.arch.cppll import FracConfig
from pllsim.blocks.dtc import DTCConfig
from pllsim.blocks.oscillator import OscConfig
from pllsim.blocks.tdc import TDCConfig
from pllsim.calibration.gain_cal import KdcoCal, TdcPeriodCal
from pllsim.calibration.lms import SignSignLMS
from pllsim.validation import compare_domains  # noqa: I001

DCO = OscConfig(f0=10.0e9, gain=20e3, pn_dbchz=-112.0, pn_foffset=1e6,
                pn_f1f3=4e5, pn_floor_dbchz=-150.0)
FREF = 100e6
FOUT = 100.503 * FREF


def make_tdc_cfg(**kw):
    d = dict(fref=FREF, fout=FOUT, osc=DCO,
             dlf=DLFConfig(alpha=2**-4, rho=2**-11, iir_lambdas=(0.5,)),
             tdc=TDCConfig(t_res=0.5e-12, n_bits=8),
             ref_pn_dbchz=-158.0)
    d.update(kw)
    return ADPLLConfig(**d)


def test_zdomain_loop_metrics():
    ar = ADPLL(make_tdc_cfg()).analyze()
    # alpha*fref/(2*pi) first-order estimate ~1 MHz; IIR+delay reduce PM.
    # Bounds are a factor 2 either side of that estimate, and the PM window
    # is what a type-II loop with one IIR stage can reach at all -- outside
    # it the DLF coefficients are wrong, not the model
    assert 0.5e6 < ar.loop.f_ugb < 2.5e6
    assert 40 < ar.loop.pm_deg < 80
    assert ar.loop.f_3db < FREF / 2          # first crossing, not an alias image
    # a -112 dBc/Hz DCO at 10 GHz integrates to ~100 fs over 1k-100M; the
    # factor-2 window covers TDC quantization on top, and a 3x miss either
    # way is a noise-source unit error, the class of defect this pins
    assert 40 < ar.jitter_fs < 200


def test_cross_domain_psd():
    """3 dB: TDC quantization is deterministic/tonal, not exactly white."""
    c = compare_domains(ADPLL(make_tdc_cfg()), n_cycles=150_000, seed=1)
    assert c.skipped == [], c.skipped
    assert c.worst_db < 3.0, [f"{b.f_lo:.3g}-{b.f_hi:.3g}: {b.err_db:+.2f}"
                              for b in c.bands]


def test_kdco_fcal_and_tdc_period_cal():
    cfg = make_tdc_cfg(kdco_est_error=0.30,
                       tdc=TDCConfig(t_res=0.5e-12, n_bits=8, gain_error=0.05))
    kcal = KdcoCal(kdco_init=DCO.gain * 1.3, amp_lsb=8, meas_n=1024, rounds=4)
    tcal = TdcPeriodCal(cpp_init=(1 / FOUT) / 0.5e-12)
    sim = ADPLL(cfg).simulate(120_000, seed=1, kdco_cal=kcal, tdc_cal=tcal)
    # 2 %: the FCAL resolves Kdco to amp_lsb*gain over meas_n cycles and
    # averages four rounds; the seeded 30 % error must shrink by 15x, and a
    # calibrator that read the wrong sign or the wrong gain lands >10 %
    assert abs(kcal.value - DCO.gain) / DCO.gain < 0.02
    true_cpp = (1 / FOUT) / (0.5e-12 * 1.05)
    # 1 %: the period calibrator averages the TDC count over its window,
    # and the seeded 5 % TDC gain error is what it must take out
    assert abs(tcal.value - true_cpp) / true_cpp < 0.01
    assert sim.jitter_fs < 200


def test_bbpd_mode_locks_and_dtc_cal_converges():
    eps = 0.08
    cal = SignSignLMS(init=1.0, mu=1e-5, gear_shift_n=80_000, mu_final=1e-6)
    cfg = ADPLLConfig(
        fref=FREF, fout=FOUT, osc=DCO,
        dlf=DLFConfig(alpha=2.0, rho=2**-6),
        mode="dtc_bbpd",
        frac=FracConfig(frac=0.503, mash_order=2,
                        dtc=DTCConfig(t_res=250e-15, n_bits=12,
                                      jitter_rms_s=50e-15),
                        dtc_cal=cal),
        bb_jitter_rms_s=200e-15, ref_pn_dbchz=-158.0)
    pll = ADPLL(cfg)
    ar = pll.analyze()
    assert any("BBPD linearized" in n for n in ar.notes)
    sim = pll.simulate(150_000, seed=3, dtc_gain_init_error=eps)
    assert abs(cal.value - 1 / (1 + eps)) < 0.01
    assert abs(np.mean(sim.freq_out[-20_000:]) - FOUT) < 1e5
    assert sim.jitter_fs < 300


def test_cross_domain_psd_bbpd():
    """The BBPD mode's first PSD-band test.

    The BBPD linear gain is a describing-function approximation; measured at
    this stock point the time domain sits +3.3 dB above the model in-band --
    inside the +2..4 dB the docs have always stated for this limit, and the
    reason the registry flags it rather than the tolerance hiding it.  4.5 dB
    = the 3.0 dB architecture baseline + the linearization allowance; the
    flag assertion keeps the widened tolerance tied to its cause.
    """
    from pllsim import presets
    c = compare_domains(presets.ALL_PRESETS["adpll_bb_100m_10g"](),
                        n_cycles=150_000, seed=1)
    assert "bbpd-linearization" in c.flags
    assert c.skipped == [], c.skipped
    assert c.worst_db < 4.5, [f"{b.f_lo:.3g}-{b.f_hi:.3g}: {b.err_db:+.2f}"
                              for b in c.bands]


# ------------------------------------------------------- divider noise (bb)

def _bb(div=None, fc=None):
    pll = presets.ALL_PRESETS["adpll_bb_100m_10g"]()
    pll.cfg.div_pn_dbchz, pll.cfg.div_pn_fc = div, fc
    pll.cfg.__post_init__()
    return pll


def test_tdc_mode_refuses_a_divider_noise_term():
    """The TDC path has no feedback divider; a value there would be read
    and ignored -- the class of parameter this project keeps finding."""
    pll = presets.ALL_PRESETS["adpll_100m_10g"]()
    pll.cfg.div_pn_dbchz, pll.cfg.div_pn_fc = -160.0, 100e3
    with pytest.raises(ValueError, match="no feedback divider"):
        pll.cfg.__post_init__()


def test_divider_noise_needs_both_numbers():
    with pytest.raises(ValueError, match="set both or neither"):
        _bb(div=-160.0, fc=None)


def test_unset_divider_noise_is_said_not_assumed():
    ar = _bb().analyze()
    assert any("divider phase noise not modelled" in n for n in ar.notes), ar.notes
    assert "divider" not in ar.pn_breakdown


def test_divider_noise_enters_the_linear_model_through_the_ratio():
    """A -140 dBc/Hz divider floor at the PD, multiplied by N=100.5 (40 dB),
    is a -100 dBc/Hz in-band floor at 10 GHz: it must dominate."""
    quiet = _bb().analyze()
    loud = _bb(div=-140.0, fc=100e3).analyze()
    assert "divider" in loud.pn_breakdown
    assert not any("not modelled" in n for n in loud.notes)
    assert loud.jitter_fs > 1.5 * quiet.jitter_fs, (quiet.jitter_fs, loud.jitter_fs)


def test_divider_noise_enters_the_time_domain_too():
    """Same knob, same direction in simulate(): the sampled divider edge
    jitter is added at the PD every cycle."""
    quiet = _bb().simulate(60_000, seed=3)
    loud = _bb(div=-140.0, fc=100e3).simulate(60_000, seed=3)
    assert loud.jitter_fs > 1.5 * quiet.jitter_fs, (quiet.jitter_fs, loud.jitter_fs)
