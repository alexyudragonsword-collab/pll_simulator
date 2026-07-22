"""Loop-metric checks against closed-form 2nd-order type-II formulas."""
import numpy as np

from pllsim.core.freqresp import FreqResponse, default_grid, loop_metrics

TWOPI = 2 * np.pi


def make_type2_gol(f, icp, kvco_hz_v, n, r, c1, c2):
    """CPPLL open loop with series R-C1 shunted by C2."""
    def z(s):
        return (1 + s * r * c1) / (s * (c1 + c2) * (1 + s * r * c1 * c2 / (c1 + c2)))
    zf = FreqResponse.from_callable(f, z)
    return zf * FreqResponse.integrator(f, icp * kvco_hz_v / n)  # (Icp/2pi)*Z*2pi*Kvco/s/N


def test_type2_pm_ugb_against_closed_form():
    icp, kvco, n = 500e-6, 50e6, 250
    r, c1, c2 = 10e3, 400e-12, 20e-12
    f = default_grid(1e2, 1e8, 200)
    gol = make_type2_gol(f, icp, kvco, n, r, c1, c2)
    m = loop_metrics(gol)

    # closed form: wz = 1/(R C1), wp = (C1+C2)/(R C1 C2)
    wz = 1 / (r * c1)
    wp = (c1 + c2) / (r * c1 * c2)
    # numerically solve |G(jw)| = 1 for reference (dense grid brute force)
    wgrid = TWOPI * np.logspace(2, 8, 400000)
    k = icp * kvco / n
    magz = np.sqrt(1 + (wgrid / wz) ** 2) / (
        wgrid * (c1 + c2) * np.sqrt(1 + (wgrid / wp) ** 2))
    mag = k * magz / wgrid
    i = np.argmin(np.abs(np.log(mag)))
    w_ugb_ref = wgrid[i]
    pm_ref = 180 + np.degrees(-np.pi + np.arctan(w_ugb_ref / wz) - np.arctan(w_ugb_ref / wp))

    assert abs(m.f_ugb - w_ugb_ref / TWOPI) / (w_ugb_ref / TWOPI) < 1e-3
    assert abs(m.pm_deg - pm_ref) < 0.1
    assert m.n_crossings == 1


def test_feedback_identity():
    f = default_grid(1e3, 1e8, 60)
    gol = make_type2_gol(f, 200e-6, 30e6, 100, 20e3, 200e-12, 10e-12)
    h = gol.feedback()          # G/(1+G)
    e = 1.0 / (1.0 + gol)       # 1/(1+G)
    assert np.allclose(h.h + e.h, 1.0)


def test_delay_and_zoh():
    f = default_grid(1e3, 1e8, 60)
    td = 3e-9
    d = FreqResponse.delay(f, td)
    assert np.allclose(d.mag(), 1.0)
    ph = np.angle(d.h[10])
    assert np.isclose(ph, -TWOPI * f[10] * td, rtol=1e-9)

    fs = 100e6
    z = FreqResponse.zoh(f, fs)
    assert np.isclose(z.h[0].real, 1.0, atol=1e-6)


def test_zdomain_accumulator():
    f = default_grid(1e3, 1e7, 60)
    fs = 100e6
    acc = FreqResponse.accumulator(f, fs)
    # low-frequency asymptote: 1/(1-z^-1) ~ fs/(j 2 pi f)
    approx = fs / (TWOPI * f[0])
    assert np.isclose(np.abs(acc.h[0]), approx, rtol=1e-3)
