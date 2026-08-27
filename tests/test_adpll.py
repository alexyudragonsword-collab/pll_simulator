"""ADPLL: loop metrics, cross-domain PSD, KDCO/TDC calibration, BB mode."""
import numpy as np

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
    # alpha*fref/(2*pi) first-order estimate ~1 MHz; IIR+delay reduce PM
    assert 0.5e6 < ar.loop.f_ugb < 2.5e6
    assert 40 < ar.loop.pm_deg < 80
    assert ar.loop.f_3db < FREF / 2          # first crossing, not an alias image
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
    assert abs(kcal.value - DCO.gain) / DCO.gain < 0.02
    true_cpp = (1 / FOUT) / (0.5e-12 * 1.05)
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
