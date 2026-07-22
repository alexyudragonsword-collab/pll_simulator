"""Loop filter: exact discrete update vs ODE solver; transimpedance vs closed form."""
import numpy as np
from scipy.integrate import solve_ivp

from pllsim.blocks.loopfilter import FilterDesign, LoopFilter


def test_impulse_update_vs_ode_2nd_order():
    d = FilterDesign(c1=400e-12, r2=10e3, c2=20e-12)
    tref = 1 / 50e6
    lf = LoopFilter(d, tref)
    rng = np.random.default_rng(3)
    dqs = rng.normal(0, 1e-12, 60)

    # reference: ODE with impulses as instantaneous state jumps
    x = np.zeros(2)
    for dq in dqs:
        x = x + lf.b * dq
        sol = solve_ivp(lambda t, y: lf.a @ y, (0, tref), x, rtol=1e-11, atol=1e-16)
        x = sol.y[:, -1]
        lf.update_impulse(dq)
    assert np.allclose(lf.x, x, rtol=1e-6, atol=1e-12)


def test_pulse_update_vs_ode_3rd_order():
    d = FilterDesign(c1=200e-12, r2=20e3, c2=10e-12, r3=5e3, c3=5e-12)
    tref = 1 / 100e6
    lf = LoopFilter(d, tref)
    i_cp, t_on = 300e-6, 2e-9

    x = np.zeros(3)
    for _ in range(20):
        sol = solve_ivp(lambda t, y: lf.a @ y + lf.b * i_cp, (0, t_on), x,
                        rtol=1e-11, atol=1e-16)
        x = sol.y[:, -1]
        sol = solve_ivp(lambda t, y: lf.a @ y, (0, tref - t_on), x,
                        rtol=1e-11, atol=1e-16)
        x = sol.y[:, -1]
        lf.update_pulse(i_cp, t_on)
    assert np.allclose(lf.x, x, rtol=1e-6, atol=1e-12)


def test_transimpedance_closed_form_2nd_order():
    c1, r2, c2 = 400e-12, 10e3, 20e-12
    lf = LoopFilter(FilterDesign(c1=c1, r2=r2, c2=c2), 1e-8)
    f = np.logspace(3, 8, 50)
    s = 2j * np.pi * f
    z_ref = (1 + s * r2 * c1) / (s * (c1 + c2) * (1 + s * r2 * c1 * c2 / (c1 + c2)))
    z = lf.transimpedance(f)
    assert np.allclose(z, z_ref, rtol=1e-8)


def test_charge_conservation_integrator():
    """DC behavior: total injected charge ends up on C1+C2 (type-II integrator)."""
    d = FilterDesign(c1=100e-12, r2=10e3, c2=5e-12)
    lf = LoopFilter(d, 1e-8)
    for _ in range(3000):
        lf.update_impulse(1e-13)
    for _ in range(200):        # let charge equalize across R2 (tau ~ 48 ns)
        lf.update_impulse(0.0)
    v_final = 3000 * 1e-13 / (d.c1 + d.c2)
    assert abs(lf.vctrl - v_final) / v_final < 1e-6
