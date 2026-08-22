"""Background-calibration tracking under an accelerated gain ramp."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from typing import Any

import matplotlib.pyplot as plt
import numpy as np
import streamlit as st
from _common import L, metric_row, show_fig, sidebar_lang_toggle

st.set_page_config(page_title="Drift tracking", layout="wide")
sidebar_lang_toggle()

from pllsim import presets
from pllsim.core.dtcspurs import dtc_spur_table
from pllsim.guiutil import frac_presets

FRAC = frac_presets()

st.title(L("温漂下的后台校准", "Background calibration under drift"))
c = st.columns(4)
nm = c[0].selectbox("preset", FRAC)
eps_tot = float(c[1].text_input(L("总增益漂移", "total gain drift"), "0.03"))
n_ramp = int(c[2].number_input(L("斜坡周期数", "ramp cycles"), 20_000,
                               400_000, 60_000, 10_000))
ramp_start = int(c[3].number_input(L("斜坡起点", "ramp start"), 40_000,
                                   200_000, 80_000, 10_000))

pll0 = presets.ALL_PRESETS[nm]()
mu_final = pll0.cfg.frac.dtc_cal.mu_final or pll0.cfg.frac.dtc_cal.mu
rate = eps_tot / n_ramp
st.caption(f"rate = {rate:.2e} /cycle = {rate / mu_final:.2f} x mu_final "
           f"({mu_final:.1e}) — "
           + L("超过 1x 即符号-符号转换率墙", "the sign-sign slew wall is 1x"))

if st.button("Run ramp", type="primary"):
    n = ramp_start + n_ramp
    pll = presets.ALL_PRESETS[nm]()
    pll.cfg.frac.dtc_cal.gear_shift_n = min(
        pll.cfg.frac.dtc_cal.gear_shift_n or 40_000, ramp_start // 2)
    drift = np.zeros(n)
    drift[ramp_start:] = eps_tot * np.arange(n_ramp) / n_ramp
    with st.spinner(L("斜坡仿真中…", "ramping...")):
        drift_kw: dict[str, Any] = {"dtc_gain_drift": drift}
        sim = pll.simulate(n, seed=3, **drift_kw)
    g = sim.cal_traces["dtc_gain"]
    lag = np.abs(g * (1.0 + drift) - 1.0)
    c2 = pll.cfg
    if type(pll).__name__ == "SPLL":
        tof = lambda r: -r / c2.fout - c2.frac.dtc.range_s / 2.0
    elif type(pll).__name__ == "SSPLL":
        tof = lambda r: (1.0 + r) / c2.fout - c2.frac.dtc.range_s / 2.0
    else:
        tof = lambda r: r / c2.fout
    tab = dtc_spur_table(c2.frac, tof, c2.fref, c2.fout,
                         gain_eps=float(lag[-1]))
    metric_row([
        (L("峰值滞后", "peak lag"), f"{lag[-1] * 100:.2f} %"),
        ("jitter", f"{sim.jitter_fs:.0f} fs" if sim.jitter_fs else "-"),
        (L("滞后杂散", "lag spur"),
         f"{max(tab.values()):.1f} dBc" if tab else "-"),
    ])
    fig, ax = plt.subplots(figsize=(9, 4))
    t_ms = (np.arange(n) - ramp_start) / pll.cfg.fref * 1e3
    ax.plot(t_ms, lag * 100, lw=0.9, label="tracking lag")
    ax.plot(t_ms, drift * 100, "--", lw=0.9, label="true drift")
    ax.set_xlabel(L("斜坡开始后时间 [ms]", "time from ramp start [ms]"))
    ax.set_ylabel("[%]")
    ax.legend()
    ax.grid(alpha=0.3)
    show_fig(fig)
    st.caption(L("两个机制叠加：EMA 误差去直流在斜坡中使相关器部分失明（即使远低于"
                 "转换率墙也 ~1%），rate>mu 后转换率极限叠加；每 1% 滞后 = 带内杂散 "
                 "20log10(lag)。真实温度斜坡比墙低 ~5 个数量级（ex20）。",
                 "two stacked mechanisms: EMA error-centering blinds the "
                 "correlator during ramps (~1% even below the wall); the "
                 "slew limit adds beyond rate ~ mu.  Real thermal ramps sit "
                 "~5 orders below the wall (ex20)."))
