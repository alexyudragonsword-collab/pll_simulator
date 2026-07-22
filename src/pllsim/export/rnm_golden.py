"""Golden engines replicating the exported RNM semantics exactly.

Differences vs the arch simulate() methods (documented, deliberate):
  * noise off, reference jitter off (goldens are deterministic)
  * loop filter uses the impulse update only (the RNM model does too;
    Python simulate() switches to the pulse-aware update during acquisition)
  * no band-select / supply-ripple / doubler side features
Each engine returns a dict of per-cycle numpy arrays (the golden CSV
columns).  test_export_golden.py asserts locked-state agreement with the
full simulate().
"""
from __future__ import annotations

import numpy as np

from ..arch.adpll import ADPLLConfig
from ..arch.cppll import CPPLLConfig
from ..arch.ilcm import ILCMConfig
from ..arch.mdll import MDLLConfig
from ..arch.spll import SPLLConfig
from ..arch.sspll import SSPLLConfig
from ..blocks.dtc import DTC
from ..blocks.loopfilter import LoopFilter
from ..core.deltasigma import Efm1, Mash11, Mash111

TWOPI = 2.0 * np.pi


def _mash(order: int, bits: int):
    return {1: Efm1, 2: Mash11, 3: Mash111}[order](bits)


def golden_cppll(cfg: CPPLLConfig, n: int) -> dict[str, np.ndarray]:
    tref = 1.0 / cfg.fref
    lf = LoopFilter(cfg.filt, tref)
    lf.reset(cfg.osc.v_for(cfg.fout))
    mash = _mash(cfg.frac.mash_order, cfg.frac.bits) if cfg.frac else None
    frac_word = cfg.frac.frac_word if cfg.frac else 0
    dtc = DTC(cfg.frac.dtc, np.random.default_rng(0), noise=False) \
        if (cfg.frac and cfg.frac.dtc) else None
    n_int = int(cfg.fout // cfg.fref) if cfg.frac else int(round(cfg.n_div))
    up = cfg.cp.icp * (1.0 + 0.005 * cfg.cp.mismatch_pct)
    dn = cfg.cp.icp * (1.0 - 0.005 * cfg.cp.mismatch_pct)

    t_div = 0.0
    fv = cfg.osc.freq_law(lf.vctrl)
    cols = {k: np.zeros(n) for k in
            ("dt", "dq", "vctrl", "fv", "residual", "dtc_delay")}
    for i in range(n):
        t_ref = i * tref
        residual = mash.residual_ui() if mash else 0.0
        d_dtc = dtc.delay(residual / cfg.fout) if dtc else 0.0
        t_ref += d_dtc
        dt = t_div - t_ref
        dt_eff = min(max(dt, -0.45 * tref), 0.45 * tref)
        dq = (up - dn) * cfg.cp.t_reset \
            + (up if dt_eff > 0 else dn) * dt_eff + cfg.cp.leakage_a * tref
        lf.update_impulse(dq)
        fv = max(cfg.osc.freq_law(lf.vctrl), 0.05 * cfg.osc.f0)
        n_next = (n_int + mash.step(frac_word)) if mash else n_int
        t_div += n_next / fv
        cols["dt"][i] = dt
        cols["dq"][i] = dq
        cols["vctrl"][i] = lf.vctrl
        cols["fv"][i] = fv
        cols["residual"][i] = residual
        cols["dtc_delay"][i] = d_dtc
    return cols


def golden_sspll(cfg: SSPLLConfig, n: int) -> dict[str, np.ndarray]:
    tref = 1.0 / cfg.fref
    lf = LoopFilter(cfg.filt, tref)
    lf.reset(cfg.osc.v_for(cfg.fout))
    s = cfg.sampler
    mash = _mash(1, cfg.frac.bits) if cfg.frac else None
    frac_word = cfg.frac.frac_word if cfg.frac else 0
    dtc = DTC(cfg.frac.dtc, np.random.default_rng(0), noise=False) \
        if cfg.frac else None
    phi_frac = 0.0
    prev_extra = 0.0
    fv = cfg.osc.freq_law(lf.vctrl)
    cols = {k: np.zeros(n) for k in ("perr", "vs", "dq", "vctrl", "fv")}
    for i in range(n):
        extra = 0.0
        if mash is not None:
            residual = mash.residual_ui()
            t_target = (1.0 + residual) / cfg.fout - cfg.frac.dtc.range_s / 2.0
            extra += dtc.delay(t_target)
        dt_period = tref + extra - prev_extra
        prev_extra = extra
        phi_frac = (phi_frac + TWOPI * fv * dt_period) % TWOPI
        perr = ((phi_frac + np.pi) % TWOPI) - np.pi
        vs = s.amp_v * np.sin(perr) + s.pedestal_v
        dq = -s.gm * vs * s.pulse_width          # inverting gm (see arch/sspll)
        if mash is not None:
            mash.step(frac_word)
        lf.update_impulse(dq)
        fv = max(cfg.osc.freq_law(lf.vctrl), 0.05 * cfg.osc.f0)
        cols["perr"][i] = perr
        cols["vs"][i] = vs
        cols["dq"][i] = dq
        cols["vctrl"][i] = lf.vctrl
        cols["fv"][i] = fv
    return cols


def golden_spll(cfg: SPLLConfig, n: int) -> dict[str, np.ndarray]:
    tref = 1.0 / cfg.fref
    lf = LoopFilter(cfg.filt, tref)
    lf.reset(cfg.osc.v_for(cfg.fout))
    s = cfg.sampler
    frac = cfg.frac is not None
    mash = _mash(1, cfg.frac.bits) if frac else None
    frac_word = cfg.frac.frac_word if frac else 0
    dtc = DTC(cfg.frac.dtc, np.random.default_rng(0), noise=False) \
        if frac else None
    n_int = int(cfg.fout // cfg.fref) if frac else int(round(cfg.n_div))
    t_div = 0.0
    fv = cfg.osc.freq_law(lf.vctrl)
    cols = {k: np.zeros(n) for k in ("perr", "dq", "vctrl", "fv")}
    for i in range(n):
        d_dtc = 0.0
        if mash is not None:
            residual = mash.residual_ui()
            t_target = -residual / cfg.fout - cfg.frac.dtc.range_s / 2.0
            d_dtc = dtc.delay(t_target)
        perr = TWOPI * cfg.fref * (t_div + d_dtc - i * tref)
        perr = ((perr + np.pi) % TWOPI) - np.pi
        vs = s.amp_v * np.sin(perr) + s.pedestal_v
        dq = s.gm * vs * s.pulse_width
        lf.update_impulse(dq)
        fv = max(cfg.osc.freq_law(lf.vctrl), 0.05 * cfg.osc.f0)
        n_next = (n_int + mash.step(frac_word)) if mash else n_int
        t_div += n_next / fv
        cols["perr"][i] = perr
        cols["dq"][i] = dq
        cols["vctrl"][i] = lf.vctrl
        cols["fv"][i] = fv
    return cols


def golden_adpll_tdc(cfg: ADPLLConfig, n: int) -> dict[str, np.ndarray]:
    tref = 1.0 / cfg.fref
    fcw = cfg.fcw
    kdco_hat = cfg.osc.gain * (1.0 + cfg.kdco_est_error)
    otw_center = (cfg.fout - cfg.osc.f0) / cfg.osc.gain
    cpp_nom = (1.0 / cfg.fout) / cfg.tdc.t_res
    t_lsb_true = cfg.tdc.t_res * (1.0 + cfg.tdc.gain_error)
    code_max = (1 << cfg.tdc.n_bits) - 1
    acc = 0.0
    iir = [0.0] * len(cfg.dlf.iir_lambdas)
    qerr = 0.0
    phi_v = 0.0
    r_acc = 0.0
    fv = cfg.osc.f0 + cfg.osc.gain * otw_center
    cols = {k: np.zeros(n) for k in ("e_ui", "otw_q", "fv")}
    for i in range(n):
        phi_v += fv * tref
        r_acc += fcw
        count = np.floor(phi_v)
        frac_ui = phi_v - count
        code = min(max(int(frac_ui * (1.0 / fv) / t_lsb_true), 0), code_max)
        e_ui = r_acc - (count + code / cpp_nom)
        acc += cfg.dlf.rho * e_ui
        x = cfg.dlf.alpha * e_ui + acc
        for k, lam in enumerate(cfg.dlf.iir_lambdas):
            iir[k] += lam * (x - iir[k])
            x = iir[k]
        otw = x * cfg.fref / kdco_hat + otw_center
        if cfg.dco_dither_order > 0:
            otw_q = np.floor(otw + qerr)
            qerr = otw + qerr - otw_q
        else:
            otw_q = np.round(otw)
        fv = cfg.osc.f0 + cfg.osc.gain * otw_q
        cols["e_ui"][i] = e_ui
        cols["otw_q"][i] = otw_q
        cols["fv"][i] = fv
    return cols


def golden_adpll_bbpd(cfg: ADPLLConfig, n: int) -> dict[str, np.ndarray]:
    tref = 1.0 / cfg.fref
    mash = _mash(cfg.frac.mash_order, cfg.frac.bits)
    frac_word = cfg.frac.frac_word
    n_int = int(cfg.fout // cfg.fref)
    otw_center = (cfg.fout - cfg.osc.f0) / cfg.osc.gain
    dtc = DTC(cfg.frac.dtc, np.random.default_rng(0), noise=False) \
        if cfg.frac.dtc else None
    acc = 0.0
    qerr = 0.0
    t_div = 0.0
    fv = cfg.osc.f0 + cfg.osc.gain * otw_center
    cols = {k: np.zeros(n) for k in ("e", "otw_q", "fv", "residual")}
    for i in range(n):
        t_ref = i * tref
        residual = mash.residual_ui()
        if dtc is not None:
            t_ref += dtc.delay(residual / cfg.fout)
        e = 1.0 if (t_div - t_ref) >= 0 else -1.0
        acc += cfg.dlf.rho * e
        otw = cfg.dlf.alpha * e + acc + otw_center
        if cfg.dco_dither_order > 0:
            otw_q = np.floor(otw + qerr)
            qerr = otw + qerr - otw_q
        else:
            otw_q = np.round(otw)
        fv = cfg.osc.f0 + cfg.osc.gain * otw_q
        n_next = n_int + mash.step(frac_word)
        t_div += n_next / fv
        cols["e"][i] = e
        cols["otw_q"][i] = otw_q
        cols["fv"][i] = fv
        cols["residual"][i] = residual
    return cols


def golden_ilcm(cfg: ILCMConfig, n: int, f_free_error: float = 1e6
                ) -> dict[str, np.ndarray]:
    tref = 1.0 / cfg.fref
    b = cfg.beta
    e = 0.0
    f_corr = 0.0
    mu = cfg.ftl_mu * cfg.ftl_f_lsb
    cols = {k: np.zeros(n) for k in ("e", "f_corr")}
    for i in range(n):
        f_free = cfg.osc.f0 + f_free_error + f_corr
        dphi = TWOPI * (f_free - cfg.fout) * tref
        e_pre = e + dphi
        e_wrap = ((e_pre + np.pi) % TWOPI) - np.pi
        e = (1.0 - b) * e_wrap
        if cfg.ftl:
            drift = e_pre - e
            if drift != 0.0:
                f_corr -= mu * np.sign(drift)
        cols["e"][i] = e
        cols["f_corr"][i] = f_corr
    return cols


def golden_mdll(cfg: MDLLConfig, n: int, f_free_error: float = 1e6
                ) -> dict[str, np.ndarray]:
    tref = 1.0 / cfg.fref
    e = 0.0
    tune = 0.0
    cols = {k: np.zeros(n) for k in ("e_pre", "tune")}
    for i in range(n):
        f_free = cfg.osc.f0 + cfg.osc.gain * tune + f_free_error
        dphi = TWOPI * (f_free - cfg.fout) * tref
        e_pre = e + dphi
        if e_pre != 0.0:
            tune -= cfg.tune_ki_lsb * np.sign(e_pre)
        e = 0.0                       # edge replacement, noise-free inj
        cols["e_pre"][i] = e_pre
        cols["tune"][i] = tune
    return cols


GOLDEN_ENGINES = {
    "cppll": golden_cppll,
    "sspll": golden_sspll,
    "spll": golden_spll,
    "adpll_tdc": golden_adpll_tdc,
    "adpll_bbpd": golden_adpll_bbpd,
    "ilcm": golden_ilcm,
    "mdll": golden_mdll,
}


def write_golden_csv(path, cols: dict[str, np.ndarray]):
    from pathlib import Path
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    names = list(cols)
    n = len(next(iter(cols.values())))
    with open(path, "w") as f:
        f.write("cycle," + ",".join(names) + "\n")
        for i in range(n):
            f.write(str(i) + "," +
                    ",".join(f"{cols[k][i]:.17g}" for k in names) + "\n")
    return path
