"""Loop synthesis: component values from UGB/PM targets + BW sweep."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import matplotlib.pyplot as plt
import streamlit as st

from _common import L, show_fig, sidebar_lang_toggle

st.set_page_config(page_title="Synthesis", layout="wide")
sidebar_lang_toggle()

from pllsim import presets
from pllsim.synth import (cppll_kdet, design_adpll_dlf, design_cp_filter,
                          design_spll_filter, design_sspll_filter, retune_loop,
                          sweep_bandwidth, sweepable_presets)

st.title(L("环路综合", "Loop synthesis"))
tab_cp, tab_ss, tab_sp, tab_dlf, tab_sweep = st.tabs(
    ["CP filter", "SSPLL filter", "SPLL filter", "ADPLL DLF",
     L("带宽扫描", "BW sweep")])
st.caption(L("ILCM / MDLL 不在此页：它们没有环路滤波器，带宽由每周期的边沿"
             "重整决定，可调的只有频率跟踪环增益。",
             "ILCM / MDLL are absent by design: they have no loop filter — "
             "bandwidth comes from per-cycle edge realignment, and the only "
             "tunable loop is the frequency-tracking gain."))

with tab_cp:
    c = st.columns(6)
    icp = float(c[0].text_input("Icp [A]", "1.5e-3"))
    n = float(c[1].text_input("N", "250"))
    kvco = float(c[2].text_input("Kvco [Hz/V]", "60e6"))
    ugb = float(c[3].text_input("UGB [Hz]", "1e6"))
    pm = float(c[4].text_input("PM [deg]", "58"))
    fref = float(c[5].text_input("fref [Hz]", "19.2e6"))
    if st.button("Synthesize", key="cp"):
        try:
            filt = design_cp_filter(cppll_kdet(icp, n), kvco, ugb, pm, fref)
            st.json({"c1": f"{filt.c1:.4g} F", "r2": f"{filt.r2:.4g} Ohm",
                     "c2": f"{filt.c2:.4g} F", "r3": f"{filt.r3:.4g} Ohm",
                     "c3": f"{filt.c3:.4g} F"})
        except Exception as e:
            st.error(str(e))

with tab_ss:
    c = st.columns(6)
    amp = float(c[0].text_input("amp [V]", "0.4"))
    gm = float(c[1].text_input("gm [S]", "1e-3"))
    pw = float(c[2].text_input("pulse [s]", "150e-12"))
    kvco2 = float(c[3].text_input("Kvco [Hz/V]", "60e6", key="ss_kv"))
    ugb2 = float(c[4].text_input("UGB [Hz]", "1e6", key="ss_ugb"))
    fref2 = float(c[5].text_input("fref [Hz]", "19.2e6", key="ss_fr"))
    pm2 = float(st.text_input("PM [deg]", "60", key="ss_pm"))
    if st.button("Synthesize", key="ss"):
        try:
            filt = design_sspll_filter(amp * gm * pw, kvco2, ugb2, pm2, fref2)
            st.json({"c1": f"{filt.c1:.4g} F", "r2": f"{filt.r2:.4g} Ohm",
                     "c2": f"{filt.c2:.4g} F", "r3": f"{filt.r3:.4g} Ohm",
                     "c3": f"{filt.c3:.4g} F"})
            st.caption(L("在精确离散环路上求解（含 ZOH/累加）",
                         "solved on the exact discrete loop (ZOH included)"))
        except Exception as e:
            st.error(str(e))

with tab_sp:
    st.caption(L("采参考的采样 PLL：与 SSPLL 同一离散环路，但鉴相增益经分频器"
                 "折算 1/N", "reference-sampling PLL: the SSPLL discrete loop "
                 "with the detector gain referred through the divider (1/N)"))
    c = st.columns(4)
    amp_s = float(c[0].text_input("amp [V]", "0.8", key="sp_amp"))
    gm_s = float(c[1].text_input("gm [S]", "10e-3", key="sp_gm"))
    pw_s = float(c[2].text_input("pulse [s]", "1e-9", key="sp_pw"))
    n_s = float(c[3].text_input("N (fout/fref)", "80", key="sp_n"))
    c2 = st.columns(4)
    kvco_s = float(c2[0].text_input("Kvco [Hz/V]", "60e6", key="sp_kv"))
    ugb_s = float(c2[1].text_input("UGB [Hz]", "3e5", key="sp_ugb"))
    pm_s = float(c2[2].text_input("PM [deg]", "60", key="sp_pm"))
    fref_s = float(c2[3].text_input("fref [Hz]", "100e6", key="sp_fr"))
    if st.button("Synthesize", key="sp"):
        try:
            filt = design_spll_filter(amp_s, gm_s, pw_s, n_s, kvco_s,
                                      ugb_s, pm_s, fref_s)
            st.json({"c1": f"{filt.c1:.4g} F", "r2": f"{filt.r2:.4g} Ohm",
                     "c2": f"{filt.c2:.4g} F", "r3": f"{filt.r3:.4g} Ohm",
                     "c3": f"{filt.c3:.4g} F"})
            st.caption(L("在精确离散环路上求解（含 ZOH/累加）",
                         "solved on the exact discrete loop (ZOH included)"))
        except Exception as e:
            st.error(str(e))

with tab_dlf:
    c = st.columns(3)
    fref3 = float(c[0].text_input("fref [Hz]", "100e6", key="d_fr"))
    ugb3 = float(c[1].text_input("UGB [Hz]", "1e6", key="d_ugb"))
    pm3 = float(c[2].text_input("PM [deg]", "55", key="d_pm"))
    if st.button("Synthesize", key="dlf"):
        try:
            alpha, rho = design_adpll_dlf(fref3, ugb3, pm3)
            st.json({"alpha": f"{alpha:.6g}", "rho": f"{rho:.6g}"})
        except Exception as e:
            st.error(str(e))

with tab_sweep:
    st.caption(L("对 preset 扫 UGB，找 jitter 最优带宽（ex07）",
                 "sweep UGB on a preset for the jitter-optimal BW (ex07)"))
    names = sweepable_presets()
    nm = st.selectbox("preset", names,
                      index=names.index("sspll_19p2m_4p8g")
                      if "sspll_19p2m_4p8g" in names else 0)
    st.caption(L(f"{len(names)}/{len(presets.ALL_PRESETS)} 个 preset 可扫："
                 "ILCM/MDLL 没有可重新综合的环路",
                 f"{len(names)} of {len(presets.ALL_PRESETS)} presets: "
                 "ILCM/MDLL have no loop to re-synthesize"))
    cc = st.columns(4)
    lo = float(cc[0].text_input("UGB from [Hz]", "2e5"))
    hi = float(cc[1].text_input("UGB to [Hz]", "3e6"))
    npts = int(cc[2].number_input("points", 4, 20, 8))
    pm_txt = cc[3].text_input(L("PM [deg]（留空=架构默认）",
                                "PM [deg] (blank = arch default)"), "")
    pm_sw = float(pm_txt) if pm_txt.strip() else None
    if st.button("Sweep", key="sw"):
        import numpy as np
        ugbs = np.geomspace(lo, hi, npts)

        def mk(f_ugb, name=nm):
            # every point is a fresh preset retuned to this UGB at constant PM
            return retune_loop(presets.ALL_PRESETS[name](), f_ugb, pm_sw)

        with st.spinner("sweeping..."):
            res = sweep_bandwidth(mk, ugbs)
        fig, ax = plt.subplots(figsize=(7, 4))
        ax.semilogx(res["f_ugb"], res["jitter_fs"], "o-")
        ax.set_xlabel("UGB [Hz]")
        ax.set_ylabel("jitter [fs]")
        ax.grid(alpha=0.3, which="both")
        show_fig(fig)
