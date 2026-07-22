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
                          design_sspll_filter, sweep_bandwidth)

st.title(L("环路综合", "Loop synthesis"))
tab_cp, tab_ss, tab_dlf, tab_sweep = st.tabs(
    ["CP filter", "SSPLL filter", "ADPLL DLF",
     L("带宽扫描", "BW sweep")])

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
    nm = st.selectbox("preset", ["sspll_19p2m_4p8g", "cppll_19p2m_4p8g"])
    lo = float(st.text_input("UGB from [Hz]", "2e5"))
    hi = float(st.text_input("UGB to [Hz]", "3e6"))
    npts = int(st.number_input("points", 4, 20, 8))
    if st.button("Sweep", key="sw"):
        import numpy as np
        ugbs = np.geomspace(lo, hi, npts)

        def mk(f_ugb, name=nm):
            pll = presets.ALL_PRESETS[name]()
            c = pll.cfg
            if name.startswith("sspll"):
                s = c.sampler
                c.filt = design_sspll_filter(
                    s.amp_v * s.gm * s.pulse_width, c.osc.gain, f_ugb,
                    60.0, c.fref)
            else:
                c.filt = design_cp_filter(
                    cppll_kdet(c.cp.icp, c.n_div), c.osc.gain, f_ugb,
                    58.0, c.fref)
            return pll

        with st.spinner("sweeping..."):
            res = sweep_bandwidth(mk, ugbs)
        fig, ax = plt.subplots(figsize=(7, 4))
        ax.semilogx(res["f_ugb"], res["jitter_fs"], "o-")
        ax.set_xlabel("UGB [Hz]")
        ax.set_ylabel("jitter [fs]")
        ax.grid(alpha=0.3, which="both")
        show_fig(fig)
