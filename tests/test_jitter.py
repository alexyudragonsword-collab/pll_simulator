"""Jitter integration against closed forms; PSD convention lock-down."""
import numpy as np

from pllsim.core.jitter import (
    integrate_pn,
    ipn_dbc,
    ldbc_from_sphi,
    rms_jitter_fs,
    sphi_from_ldbc,
)


def test_convention_roundtrip():
    l = -100.0
    s = sphi_from_ldbc(l)
    assert np.isclose(s, 2e-10)
    assert np.isclose(ldbc_from_sphi(s), l)


def test_flat_pn_jitter_textbook():
    """Flat L = -100 dBc/Hz from 1 kHz to 10 MHz at 1 GHz carrier.

    sigma_phi^2 = 2*10^-10 * (1e7 - 1e3) rad^2 -> sigma_t = sigma_phi/(2pi f0)
    """
    f = np.logspace(2, 8, 2000)
    s = np.full(f.shape, sphi_from_ldbc(-100.0))
    f0 = 1e9
    sig_phi = np.sqrt(2e-10 * (1e7 - 1e3))
    expect_fs = sig_phi / (2 * np.pi * f0) * 1e15
    got = rms_jitter_fs(f, s, f0, 1e3, 1e7)
    assert abs(got - expect_fs) / expect_fs < 1e-3


def test_one_over_f2_closed_form():
    """S_phi = k2/f^2: integral over [f1,f2] = k2*(1/f1 - 1/f2)."""
    k2 = 1e-2
    f = np.logspace(3, 8, 4000)
    s = k2 / f**2
    p = integrate_pn(f, s, 1e4, 1e7)
    expect = k2 * (1e-4 - 1e-7)
    assert abs(p - expect) / expect < 1e-3


def test_ipn_dbc():
    f = np.logspace(3, 7, 1000)
    s = np.full(f.shape, sphi_from_ldbc(-120.0))
    # IPN = 10log10( (1/2)*S*(f2-f1) ) = -120 + 10log10(1e6 - 1e3)
    expect = -120.0 + 10 * np.log10(1e6 - 1e3)
    assert abs(ipn_dbc(f, s, 1e3, 1e6) - expect) < 0.05
