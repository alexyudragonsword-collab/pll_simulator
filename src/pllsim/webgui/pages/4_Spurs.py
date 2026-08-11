"""Deterministic fractional-spur prediction (DTC quant + INL + gain)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import matplotlib.pyplot as plt
import numpy as np
import streamlit as st
from _common import L, show_fig, sidebar_lang_toggle

st.set_page_config(page_title="Spurs", layout="wide")
sidebar_lang_toggle()

from pllsim.guiutil import (
    fine_oversample_note,
    fine_record_mb,
    frac_presets,
    make_pll,
    ref_spur_comparison,
)
from pllsim.plotting import plot_spur_spectrum

FRAC_PRESETS = frac_presets()

st.title(L("DTC 小数杂散预测", "DTC fractional-spur prediction"))
preset = st.selectbox("preset", FRAC_PRESETS)
c = st.columns(4)
inl_amp = float(c[0].text_input(L("正弦 INL 幅度 [s]", "sine INL amp [s]"),
                                "50e-15"))
inl_cyc = float(c[1].text_input(L("INL 周期数", "INL cycles"), "1.0"))
gain_eps = float(c[2].text_input(L("残余增益误差", "gain residual"), "0.002"))
kmax = int(c[3].number_input("k max", 1, 12, 6))

if st.button(L("预测（经 analyze 的环路 NTF）",
               "Predict (through the loop NTF)"), type="primary",
             key="predict"):
    pll = make_pll(preset)
    pll.cfg.frac.dtc.inl_sin = (inl_amp, inl_cyc, 0.3) if inl_amp else ()
    pll.cfg.frac.dtc.gain_error_residual = gain_eps
    with st.spinner("analyze..."):
        ar = pll.analyze()
    tab = {k: float(v) for k, v in ar.spurs_analytic.items()
           if k.startswith("frac_spur")}
    st.session_state["spur_tab"] = tab

tab = st.session_state.get("spur_tab")
if tab:
    rows = [{"offset": k.split("@")[1], "spur [dBc]": round(v, 1)}
            for k, v in sorted(tab.items(), key=lambda kv: -kv[1])]
    st.dataframe(rows, use_container_width=True)
    st.caption(L("预测与无噪声时域在 0.2 dB 内吻合（ex15 验证）；实测读数在音强"
                 "低于本底后受噪底限制。",
                 "matches the noise-free time domain within 0.2 dB (ex15); "
                 "measured readings floor at the local noise."))

st.subheader(L("时域实测谱（与上表对照）",
               "Measured spectrum (against the table above)"))
st.caption(L("解析表是预测，这里是同一配置跑出来的周期图，杂散位置已标注 —— "
             "ex15 的对照就是这两者。",
             "the table is the prediction; this is the periodogram of the same "
             "config with the detected spurs marked — ex15 compares the two."))
n_meas = int(st.number_input(L("参考周期数", "ref cycles"), 50_000, 500_000,
                             150_000, 50_000))
if st.button(L("仿真并画谱", "Simulate and plot"), key="measure"):
    pll = make_pll(preset)
    pll.cfg.frac.dtc.inl_sin = (inl_amp, inl_cyc, 0.3) if inl_amp else ()
    pll.cfg.frac.dtc.gain_error_residual = gain_eps
    with st.spinner(L("时域仿真中…", "simulating...")):
        sim = pll.simulate(n_meas, seed=2)
    for note in sim.notes:
        st.warning(note)
    show_fig(plot_spur_spectrum(sim, ar=make_pll(preset).analyze()))

st.subheader(L("参考杂散：解析 vs 时域", "Reference spur: analytic vs time domain"))
st.caption(L("这页原来只能看小数杂散。参考杂散整个活在一个参考周期内，每个参考沿"
             "取一个点看不到它 —— 必须用周期内细采样。",
             "this page could only ever show fractional spurs.  The reference "
             "spur lives entirely inside one reference period, so one sample "
             "per reference edge sees none of it — it needs intra-period "
             "sampling."))
cr = st.columns([1, 1, 3])
m_os = int(cr[0].number_input("M", 2, 4096, 128, 32))
n_ref_cyc = int(cr[1].number_input(L("周期数", "cycles"), 5_000, 200_000,
                                   40_000, 5_000))
_p = make_pll(preset)
_hint = fine_oversample_note(_p, m_os)
cr[2].caption(f"record ~{fine_record_mb(n_ref_cyc, m_os):.0f} MB"
              + (f" — {_hint}" if _hint else ""))
if st.button(L("比较参考杂散", "Compare the reference spur"),
             key="ref_spur"):
    pll = make_pll(preset)
    with st.spinner(L("时域仿真中…", "simulating...")):
        rows, notes = ref_spur_comparison(pll, m=m_os, n_cycles=n_ref_cyc)
    if rows:
        st.dataframe(rows, use_container_width=True)
    for n in notes:
        st.info(n)

st.subheader(L("最差通道扫描", "Worst-channel sweep"))
if st.button("Sweep channels", key="sweep"):
    pll0 = make_pll(preset)      # the preset picked above, not a fixed one
    fracs = [0.0013, 0.0053, 0.0161, 0.0503, 0.1253, 0.2503, 0.3753, 0.4703]
    worst = []
    with st.spinner("sweeping..."):
        for fr in fracs:
            pll = make_pll(preset)
            pll.cfg.fout = (int(pll.cfg.fout / pll.cfg.fref) + fr) \
                * pll.cfg.fref
            pll.cfg.frac.frac = fr
            pll.cfg.frac.dtc.inl_sin = (inl_amp, inl_cyc, 0.3)
            pll.cfg.frac.dtc.gain_error_residual = gain_eps
            ar = pll.analyze()
            t = [v for k, v in ar.spurs_analytic.items()
                 if k.startswith("frac_spur")]
            worst.append(max(t) if t else np.nan)
    fig, ax = plt.subplots(figsize=(7, 4))
    beats = [f * pll0.cfg.fref for f in fracs]
    ax.semilogx(beats, worst, "o-")
    ax.axvline(pll0.analyze().loop.f_ugb, color="gray", ls=":", label="UGB")
    ax.set_xlabel("fractional beat frac*fref [Hz]")
    ax.set_ylabel("worst spur [dBc]")
    ax.legend()
    ax.grid(alpha=0.3, which="both")
    ax.set_title(f"{preset}: worst fractional spur vs channel")
    show_fig(fig)
    # naming the preset on the result, not just in the selector above: the
    # sweep used to scan a fixed preset regardless of the selection, and a
    # chart that does not say what it swept cannot show that it was wrong
    st.caption(L(f"扫描对象：{preset}。近整数通道最差：差拍落在环路带宽内，"
                 "|NTF| ~ 1。",
                 f"swept: {preset}. Near-integer channels are worst: the "
                 "beat lands inside the loop BW where |NTF| ~ 1."))
