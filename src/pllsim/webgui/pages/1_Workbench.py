"""Architecture workbench: preset -> edit every parameter -> analyze/simulate."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
import streamlit as st
from _common import (
    L,
    changed_only,
    config_form,
    metric_row,
    show_fig,
    sidebar_lang_toggle,
)

st.set_page_config(page_title="Workbench", layout="wide")
sidebar_lang_toggle()

from pllsim import presets
from pllsim.guiutil import make_pll, osc_bank_report, simulate_kwargs
from pllsim.plotting import plot_pn_breakdown

st.title(L("架构工作台", "Architecture workbench"))

names = list(presets.ALL_PRESETS)
handoff = st.session_state.get("wb_handoff")
if handoff is not None:
    label = st.session_state.get("wb_handoff_label", "selector")
    c1, c2 = st.columns([4, 1])
    c1.info(L(f"正在编辑来自选型器的候选：{label}（不是 preset）",
              f"editing a candidate handed over by the selector: {label} "
              "(not a preset)"))
    if c2.button(L("回到 preset", "back to presets")):
        st.session_state.pop("wb_handoff", None)
        st.rerun()

default = st.session_state.get("workbench_preset", names[0])
preset = st.selectbox(L("preset（每次运行取全新实例）",
                        "preset (fresh instance per run)"), names,
                      index=names.index(default) if default in names else 0,
                      disabled=handoff is not None)
st.session_state["workbench_preset"] = preset

base = handoff if handoff is not None else presets.ALL_PRESETS[preset]()


def build(overrides):
    """A PLL for the current selection, whether preset or handed over."""
    if handoff is None:
        return make_pll(preset, overrides)
    from pllsim.guiutil import apply_overrides
    apply_overrides(handoff.cfg, overrides)
    return handoff
st.caption(f"{type(base).__name__}: "
           f"fref = {base.cfg.fref / 1e6:g} MHz -> "
           f"fout = {base.cfg.fout / 1e9:.6g} GHz")

# filled in after the form runs, but rendered here — a bank that cannot reach
# the target is the first thing to know, not a footnote under 30 text boxes
bank_slot = st.container()

overrides_all = config_form(base.cfg, key_prefix=preset)
overrides = changed_only(presets.ALL_PRESETS[preset]().cfg, overrides_all)
if overrides:
    st.info(L("已修改: ", "edited: ") + ", ".join(overrides))

# coarse-band sizing, shown only once the varactor has a range: with an
# unlimited control voltage one band reaches everything and the bank is inert
try:
    bank = osc_bank_report(build(overrides).cfg)
except Exception:                      # a half-typed override; the run reports it
    bank = []
if bank:
    with bank_slot:
        st.markdown("**" + L("粗调频段组 (osc.v_min / v_max)",
                             "Coarse band bank (osc.v_min / v_max)") + "**")
        metric_row([(L(zh, en), val) for en, zh, val in bank])

col_a, col_s = st.columns(2)

# ------------------------------------------------------------- analyze
with col_a:
    st.subheader("analyze() — " + L("线性模型", "linear model"))
    if st.button("Run analyze", type="primary"):
        with st.spinner("analyze..."):
            pll = build(overrides)
            st.session_state["wb_ar"] = pll.analyze()
    ar = st.session_state.get("wb_ar")
    if ar is not None:
        metric_row([
            ("jitter", f"{ar.jitter_fs:.1f} fs"),
            ("IPN", f"{ar.ipn_dbc:.1f} dBc"),
            ("UGB", f"{ar.loop.f_ugb / 1e3:.0f} kHz"
             if np.isfinite(ar.loop.f_ugb) else "-"),
            ("PM", f"{ar.loop.pm_deg:.0f} deg"
             if np.isfinite(ar.loop.pm_deg) else "-"),
        ])
        show_fig(plot_pn_breakdown(ar, None))
        if ar.spurs_analytic:
            st.write(L("解析杂散 [dBc]:", "analytic spurs [dBc]:"))
            st.json({k: round(float(v), 1)
                     for k, v in ar.spurs_analytic.items()})
        for n in ar.notes:
            st.caption("note: " + n)

# ------------------------------------------------------------ simulate
with col_s:
    st.subheader("simulate() — " + L("时域行为级", "time-domain behavioral"))
    c1, c2, c3 = st.columns(3)
    n_cycles = int(c1.number_input(L("参考周期数", "ref cycles"),
                                   10_000, 2_000_000, 150_000, 10_000))
    seed = int(c2.number_input("seed", 0, 9999, 1))
    f_off = float(c3.number_input(L("起始频偏 [MHz]", "start offset [MHz]"),
                                  -500.0, 500.0, 0.0)) * 1e6
    c4, c5, c6 = st.columns(3)
    noise = c4.checkbox(L("噪声", "noise"), True)
    cal = c5.checkbox(L("校准", "calibration"), True)
    dtc_err = float(c6.number_input(L("DTC 增益误差", "DTC gain error"),
                                    -0.5, 0.5, 0.0, 0.01))
    if st.button("Run simulate", type="primary"):
        with st.spinner(L("时域仿真中…", "simulating...")):
            pll = build(overrides)
            kw = simulate_kwargs(pll, noise=noise, calibration=cal, seed=seed,
                                 f_start_offset=f_off,
                                 dtc_gain_init_error=dtc_err)
            st.session_state["wb_sim"] = pll.simulate(n_cycles, **kw)
            st.session_state["wb_ar_overlay"] = make_pll(
                preset, overrides).analyze()
    sim = st.session_state.get("wb_sim")
    if sim is not None:
        metric_row([
            ("jitter", f"{sim.jitter_fs:.1f} fs" if sim.jitter_fs else "-"),
            ("lock", f"{sim.lock_time_s * 1e6:.1f} us"
             if sim.lock_time_s is not None else "-"),
            ("f_end", f"{sim.freq_out[-1] / 1e9:.6f} GHz"),
        ])
        for note in sim.notes:      # e.g. "still settling" — the jitter above
            st.warning(note)        # then includes a calibration transient
        show_fig(plot_pn_breakdown(st.session_state["wb_ar_overlay"], sim))
        import matplotlib.pyplot as plt
        fig, (a1, a2) = plt.subplots(2, 1, figsize=(8, 5), sharex=True)
        a1.plot(sim.t * 1e6, (sim.freq_out - sim.f0) / 1e6, lw=0.7)
        a1.set_ylabel("f err [MHz]")
        a1.grid(alpha=0.3)
        a2.plot(sim.t * 1e6, sim.ctrl, lw=0.7, color="C1")
        a2.set_ylabel("vctrl / OTW")
        a2.set_xlabel("t [us]")
        a2.grid(alpha=0.3)
        show_fig(fig)
        for k, tr in sim.cal_traces.items():
            fig, ax = plt.subplots(figsize=(8, 2.2))
            ax.plot(sim.t * 1e6, tr, lw=0.8)
            ax.set_ylabel(k)
            ax.set_xlabel("t [us]")
            ax.grid(alpha=0.3)
            show_fig(fig)
        if sim.spurs_fft:
            st.write(L("FFT 提取杂散 [dBc]:", "FFT-extracted spurs [dBc]:"))
            st.json({f"{f / 1e3:.1f} kHz": (round(float(v), 1)
                     if np.isfinite(v) else "below noise")
                     for f, v in sim.spurs_fft.items()})
