"""Background-calibration tracking under an accelerated gain ramp."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


import matplotlib.pyplot as plt
import streamlit as st
from _common import L, metric_row, show_fig, sidebar_lang_toggle

st.set_page_config(page_title="Drift tracking", layout="wide")
sidebar_lang_toggle()

from pllsim import presets
from pllsim.guiutil import drift_axes, drift_run, frac_presets

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
    with st.spinner(L("斜坡仿真中…", "ramping...")):
        run = drift_run(presets.ALL_PRESETS[nm](), eps_tot, n_ramp, ramp_start, seed=3)
    metric_row([
        (L("峰值滞后", "peak lag"), f"{run.peak_lag * 100:.2f} %"),
        ("jitter", f"{run.sim.jitter_fs:.0f} fs" if run.sim.jitter_fs else "-"),
        (L("滞后杂散", "lag spur"),
         f"{run.lag_spur_dbc:.1f} dBc" if run.lag_spur_dbc is not None else "-"),
    ])
    fig, ax = plt.subplots(figsize=(9, 4))
    drift_axes(run, ax)
    ax.set_xlabel(L("斜坡开始后时间 [ms]", "time from ramp start [ms]"))
    show_fig(fig)
    st.caption(L("两个机制叠加：EMA 误差去直流在斜坡中使相关器部分失明（即使远低于"
                 "转换率墙也 ~1%），rate>mu 后转换率极限叠加；每 1% 滞后 = 带内杂散 "
                 "20log10(lag)。真实温度斜坡比墙低 ~5 个数量级（ex20）。",
                 "two stacked mechanisms: EMA error-centering blinds the "
                 "correlator during ramps (~1% even below the wall); the "
                 "slew limit adds beyond rate ~ mu.  Real thermal ramps sit "
                 "~5 orders below the wall (ex20)."))
