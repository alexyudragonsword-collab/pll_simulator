"""Measured phase-noise import: Leeson fit, closed-loop fit, attribution."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import io

import matplotlib.pyplot as plt
import streamlit as st
from _common import L, show_fig, sidebar_lang_toggle

st.set_page_config(page_title="Fit", layout="wide")
sidebar_lang_toggle()

import numpy as np

from pllsim import presets
from pllsim.core.jitter import ldbc_from_sphi
from pllsim.fit import attribute_budget, fit_closed_loop, fit_leeson, load_pn_csv

st.title(L("实测相噪导入与拟合", "Measured phase-noise fitting"))
up = st.file_uploader(L("上传 (offset_hz, dBc/Hz) CSV（E5052/FSWP 导出均可）",
                        "upload an (offset_hz, dBc/Hz) CSV"), type=None)
demo = st.checkbox(L("没有数据？用合成示例（Wu'19 类 SPLL + 0.5 dB 仪器噪声）",
                     "no data? use a synthetic example"), value=up is None)

f = l = None
if up is not None:
    f, l = load_pn_csv(io.StringIO(up.getvalue().decode(errors="ignore")))
elif demo:
    pll = presets.spll_frac_52m_6p253g()
    ar = pll.analyze()
    sel = (ar.f >= 3e3) & (ar.f <= 40e6)
    rng = np.random.default_rng(42)
    f = ar.f[sel]
    l = ldbc_from_sphi(ar.pn_breakdown["total"][sel]) \
        + rng.normal(0, 0.5, int(sel.sum()))

if f is not None and l is not None:
    st.caption(f"{f.size} points, {f[0]:.3g} Hz - {f[-1]:.3g} Hz")
    mode = st.radio(L("拟合模式", "fit mode"),
                    [L("自由振荡 (Leeson)", "free-running (Leeson)"),
                     L("闭环频谱", "locked spectrum"),
                     L("预算归因", "budget attribution")], horizontal=True)
    if st.button("Fit", type="primary"):
        fig, ax = plt.subplots(figsize=(8, 4.5))
        ax.semilogx(f, l, ".", ms=3, alpha=0.5, label="data")
        if mode.startswith(("自由", "free")):
            lee = fit_leeson(f, l)
            st.json({"L(1MHz) 1/f^2": f"{lee.pn_dbchz:.1f} dBc/Hz",
                     "1/f^3 corner": f"{lee.pn_f1f3 / 1e3:.0f} kHz",
                     "floor": f"{lee.pn_floor_dbchz:.1f} dBc/Hz",
                     "residual": f"{lee.residual_db_rms:.2f} dB rms"})
            k3, k2, fl = lee.k
            ax.semilogx(f, 10 * np.log10((k3 / f**3 + k2 / f**2 + fl) / 2),
                        "r", lw=1.8, label="Leeson fit")
        elif mode.startswith(("闭环", "locked")):
            cl = fit_closed_loop(f, l)
            st.json({"in-band": f"{cl.inband_dbchz:.1f} dBc/Hz",
                     "f_3db": f"{cl.f_3db / 1e3:.0f} kHz",
                     "UGB est": f"{cl.f_ugb / 1e3:.0f} kHz",
                     "peaking": f"{cl.peaking_db:.1f} dB",
                     "skirt L(1M) AS SEEN": f"{cl.osc.pn_dbchz:.1f} dBc/Hz",
                     "residual": f"{cl.residual_db_rms:.2f} dB rms"})
            st.caption(L("裙边三元组只是 VCO 上界；总噪声图上读不出 PM——"
                         "这是单条曲线的物理极限（ex16）。",
                         "the skirt triple only upper-bounds the VCO and PM "
                         "is not readable from a total-noise plot — limits "
                         "of one curve (ex16)."))
        else:
            nm = st.session_state.get("att_preset", "spll_frac_52m_6p253g")
            att = attribute_budget(presets.ALL_PRESETS[nm](), f, l)
            st.write(L("按形状可辨识组的 NNLS 因子（1.0 = 在预算内）：",
                       "NNLS factors per shape-identifiable group:"))
            st.dataframe([{"group": "+".join(g),
                           "factor": round(att.factors[g], 2),
                           "dB": round(att.factors_db[g], 1)}
                          for g in att.groups], use_container_width=True)
            st.info("; ".join(att.notes)
                    + f"  (residual {att.residual_db_rms:.2f} dB rms)")
        ax.set_xlabel("offset [Hz]")
        ax.set_ylabel("L(f) [dBc/Hz]")
        ax.legend()
        ax.grid(alpha=0.3, which="both")
        show_fig(fig)
    st.selectbox(L("归因用的预算基准 preset", "budget baseline preset"),
                 list(presets.ALL_PRESETS), key="att_preset",
                 index=list(presets.ALL_PRESETS).index(
                     "spll_frac_52m_6p253g"))
