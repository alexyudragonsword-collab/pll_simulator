"""Figures of merit: PLL jitter FoM and VCO FoM."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import streamlit as st
from _common import L, metric_row, sidebar_lang_toggle

st.set_page_config(page_title="FoM", layout="wide")
sidebar_lang_toggle()

from pllsim.core.fom import pll_jitter_fom, vco_fom
from pllsim.core.jitter import HALF_POWER_DB

st.title(L("品质因数计算", "Figures of merit"))
st.caption(L(
    "两个 FoM 都把噪声对功耗归一化。**功耗由你填** —— 本包不建模功耗，"
    "任何自称端到端算出来的 FoM 都含有编造的因子。",
    "Both figures normalize noise against the power it cost. **Power is "
    "yours to supply**: pllsim models none, so a FoM it derived end to end "
    "would carry a fabricated factor."))

# ------------------------------------------------------------------- PLL
st.subheader(L("PLL 抖动 FoM", "PLL jitter FoM"))
st.code("FoM = 10*log10[ (sigma_t/1s)^2 * (P/1mW) ]", language="text")
c = st.columns(3)
jit = c[0].text_input(L("RMS 抖动 [fs]", "RMS jitter [fs]"), "100")
pwr = c[1].text_input(L("功耗 [mW]", "power [mW]"), "10", key="pll_pwr")
n = c[2].text_input(L("倍频比 N（选填）", "divide ratio N (optional)"), "")

try:
    r = pll_jitter_fom(float(jit) * 1e-15, float(pwr),
                       n=float(n) if n.strip() else None)
except (ValueError, ZeroDivisionError) as exc:
    st.error(str(exc))
else:
    items = [("FoM [dB]", f"{r.fom_db:.2f}")]
    if r.fom_n_db is not None:
        items.append(("FoM_N [dB]", f"{r.fom_n_db:.2f}"))
    metric_row(items)
    st.caption(L(
        "抖动减半得 6 dB，功耗减半只得 3 dB —— 这个 2:1 权重正是该指标的内容："
        "堆电流换抖动不会让它变好。",
        "Halving jitter gains 6 dB; halving power gains 3 dB. That 2:1 "
        "weighting is the content of the figure — spending current to buy "
        "jitter does not improve it."))
    if r.fom_n_db is not None:
        st.caption(L(
            "本包 FoM_N 取 `FoM − 10*log10(N)`，即奖励更高倍频比 —— "
            "同样的抖动经由更大的 N 达成更难。文献里也有写成加号的，"
            "所以公式印在这里而不是留给你猜。",
            "FoM_N here is `FoM − 10*log10(N)`, rewarding a higher ratio: "
            "reaching the same jitter through a larger N is harder. The "
            "literature also writes it as an addition, which is why the "
            "formula is printed rather than left to guess."))

# ------------------------------------------------------------------- VCO
st.subheader("VCO FoM")
st.code("FoM = L(df) - 20*log10(f0/df) + 10*log10(P/1mW)", language="text")
c = st.columns(5)
f0 = c[0].text_input(L("载波 f0 [Hz]", "carrier f0 [Hz]"), "10e9")
off = c[1].text_input(L("偏移 df [Hz]", "offset df [Hz]"), "1e6")
ldbc = c[2].text_input(L("L(df) [dBc/Hz] 单边带",
                         "L(df) [dBc/Hz] single-sideband"), "-120")
vpwr = c[3].text_input(L("功耗 [mW]", "power [mW]"), "10", key="vco_pwr")
ftr = c[4].text_input(L("调谐范围 [%]（选填）",
                        "tuning range [%] (optional)"), "")

try:
    v = vco_fom(float(f0), float(off), float(vpwr), l_dbc_hz=float(ldbc),
                ftr_pct=float(ftr) if ftr.strip() else None)
except (ValueError, ZeroDivisionError) as exc:
    st.error(str(exc))
else:
    items = [("FoM [dBc/Hz]", f"{v.fom_dbc_hz:.2f}")]
    if v.fom_t_dbc_hz is not None:
        items.append(("FoM_T [dBc/Hz]", f"{v.fom_t_dbc_hz:.2f}"))
    metric_row(items)
    st.warning(L(
        f"L(df) 按定义是**单边带**；本包内部存的是双边带 S_phi，两者差 "
        f"{HALF_POWER_DB:.4f} dB，代错就整体偏 3 dB。"
        "另外 −20log10(f0/df) 假设此处按 20 dB/dec 滚降 —— 在 1/f³ 拐点以内 "
        "FoM 会随偏移变化，不同偏移报的数字不可比。",
        f"L(df) is **single sideband** by definition; this package stores "
        f"double-sideband S_phi, {HALF_POWER_DB:.4f} dB away, and the wrong "
        "one shifts everything by 3 dB. The -20log10(f0/df) term also assumes "
        "20 dB/decade at this offset — inside the 1/f^3 corner the FoM "
        "depends on where it was measured, and figures quoted at different "
        "offsets are not comparable."))
