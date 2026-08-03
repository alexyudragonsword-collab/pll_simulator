"""Architecture selector: requirement -> ranked candidates -> workbench."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
import streamlit as st
from _common import L, sidebar_lang_toggle

st.set_page_config(page_title="Selector", layout="wide")
sidebar_lang_toggle()

from pllsim.selector import Requirement, select

st.title(L("架构选型", "Architecture selector"))
c = st.columns(5)
fref = float(c[0].text_input("fref [Hz]", "100e6"))
fout = float(c[1].text_input("fout [Hz]", "8e9"))
jmax = float(c[2].text_input(L("jitter 目标 [fs]", "jitter target [fs]"),
                             "120"))
band = c[3].text_input(L("积分带 [Hz]", "int band [Hz]"), "10e3, 40e6")
mod = c[4].checkbox(L("需要两点调制", "needs two-point TX"), False)

if st.button("Select", type="primary"):
    b = tuple(float(x) for x in band.replace(",", " ").split())
    with st.spinner(L("七架构综合与评估中…", "synthesizing 7 architectures...")):
        rep = select(Requirement(fref=fref, fout=fout, jitter_fs_max=jmax,
                                 int_band=b, modulation=mod))
    st.session_state["sel_rep"] = rep

rep = st.session_state.get("sel_rep")
if rep is not None:
    rows = []
    for cand in sorted(rep.candidates, key=lambda c: c.key):
        rows.append({
            "arch": cand.arch,
            "jitter [fs]": round(cand.jitter_fs, 1)
            if np.isfinite(cand.jitter_fs) else None,
            "verdict": ("PASS" if cand.feasible
                        and cand.jitter_fs <= rep.req.jitter_fs_max
                        else ("fail" if cand.feasible else "excluded")),
            "UGB [kHz]": round(cand.f_ugb / 1e3)
            if np.isfinite(cand.f_ugb) else None,
            "PM [deg]": round(cand.pm_deg)
            if np.isfinite(cand.pm_deg) else None,
            "notes": "; ".join(cand.notes),
        })
    st.dataframe(rows, use_container_width=True)
    if rep.best is not None:
        st.success(L(f"推荐: {rep.best.arch}（{rep.best.jitter_fs:.0f} fs，"
                     f"余量 {rep.req.jitter_fs_max - rep.best.jitter_fs:.0f} fs）",
                     f"recommendation: {rep.best.arch} "
                     f"({rep.best.jitter_fs:.0f} fs)"))
        # The handoff the caption used to describe and ask the user to do by
        # hand.  The candidate is already sized for the stated requirement, so
        # it goes across as-is rather than sending anyone to find the nearest
        # preset and retype fref/fout into it.
        st.subheader(L("在工作台中打开", "Open in the workbench"))
        feasible = [c for c in sorted(rep.candidates, key=lambda c: c.key)
                    if c.feasible and c.pll is not None]
        cols = st.columns(max(len(feasible), 1))
        for col, cand in zip(cols, feasible):
            if col.button(cand.arch, key=f"open_{cand.arch}"):
                st.session_state["wb_handoff"] = cand.pll
                st.session_state["wb_handoff_label"] = cand.arch
                st.switch_page("pages/1_Workbench.py")
    else:
        st.warning(L("没有架构达标：放宽目标、改善振荡器档或提高 fref。",
                     "no architecture meets the target — relax it, improve "
                     "the oscillator class, or raise fref."))
