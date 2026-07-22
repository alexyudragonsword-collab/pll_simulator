"""Monte Carlo yield: per-chip mismatch draws with live calibration."""
import sys
from functools import partial
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import streamlit as st

from _common import L, metric_row, show_fig, sidebar_lang_toggle

st.set_page_config(page_title="Monte Carlo", layout="wide")
sidebar_lang_toggle()

from pllsim.guiutil import mc_build_frac_cppll
from pllsim.montecarlo import monte_carlo, plot_mc

st.title(L("Monte Carlo 良率", "Monte Carlo yield"))
st.caption(L("ex11 的小数N CPPLL：逐芯片抽样（CP 失配、泄漏、DTC 增益/INL、"
             "Kvco、闪烁拐角），每颗芯片校准环路真实运行，多进程并行。",
             "the ex11 fractional-N CPPLL: per-chip draws with the "
             "calibration loops live, multiprocess."))
c = st.columns(4)
n_runs = int(c[0].number_input(L("芯片数", "chips"), 8, 300, 40, 8))
s_gain = float(c[1].text_input(L("DTC 增益误差 σ", "DTC gain sigma"), "0.05"))
s_inl = float(c[2].text_input(L("INL σ [s]", "INL sigma [s]"), "0.7e-12"))
n_cyc = int(c[3].number_input(L("周期/芯片", "cycles/chip"), 50_000,
                              300_000, 150_000, 25_000))
c2 = st.columns(3)
lim_jit = float(c2[0].text_input(L("jitter 限 [fs]", "jitter limit [fs]"),
                                 "250"))
lim_cal = float(c2[1].text_input(L("校准误差限", "cal error limit"), "0.01"))
st.caption(L(f"预计耗时 ~{n_runs * n_cyc / 4e6:.0f} s（多核）",
             f"expect ~{n_runs * n_cyc / 4e6:.0f} s (multicore)"))

if st.button("Run Monte Carlo", type="primary"):
    build = partial(mc_build_frac_cppll, s_gain=s_gain, s_inl=s_inl,
                    n_cycles=n_cyc)
    with st.spinner(L(f"{n_runs} 颗芯片仿真中…", f"{n_runs} chips...")):
        res = monte_carlo(build, n_runs=n_runs, seed=42)
    st.session_state["mc_res"] = res

res = st.session_state.get("mc_res")
if res is not None:
    y_jit = res.yield_frac("jitter_fs", lim_jit)
    cal = res.metrics.get("cal_dtc_gain_final")
    y_cal = None
    if cal is not None:
        import numpy as np
        g = res.metrics["cal_dtc_gain_final"]
        err = np.abs(g * (1.0 + res.params["dtc_gain_err"]) - 1.0)
        y_cal = float(np.mean(err < lim_cal))
    metric_row([
        (L("完成", "ok"), f"{res.n_ok}/{res.n_runs}"),
        (f"jitter < {lim_jit:.0f} fs", f"{y_jit * 100:.0f} %"),
        (L("校准进限", "cal within limit"),
         f"{y_cal * 100:.0f} %" if y_cal is not None else "-"),
    ])
    st.text(res.summary())
    show_fig(plot_mc(res))
