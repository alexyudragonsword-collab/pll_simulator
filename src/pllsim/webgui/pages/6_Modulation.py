"""Two-point GMSK modulation: EVM vs direct-path mismatch."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


import matplotlib.pyplot as plt
import streamlit as st
from _common import L, metric_row, show_fig, sidebar_lang_toggle

st.set_page_config(page_title="Modulation", layout="wide")
sidebar_lang_toggle()

from pllsim import presets
from pllsim.guiutil import modulation_axes, modulation_run
from pllsim.modulation import two_point_presets

ARCHS = two_point_presets()

st.title(L("两点 GMSK 调制与 EVM", "Two-point GMSK modulation and EVM"))
c = st.columns(4)
arch = c[0].selectbox(L("架构（引擎已接注入点）",
                        "architecture (injection wired)"), ARCHS)
rb = float(c[1].text_input("bit rate [b/s]", "2.5e6"))
dp_err = float(c[2].number_input(L("直通路增益误差", "direct-path error"),
                                 -0.2, 0.2, 0.0, 0.01))
n_cyc = int(c[3].number_input(L("周期数", "cycles"), 60_000, 400_000,
                              140_000, 20_000))
nm = arch
fref = presets.ALL_PRESETS[nm]().cfg.fref   # not a hardcoded copy
sps = fref / rb
if sps < 8:
    st.warning(L(f"{sps:.1f} 采样/符号 < 8：对照连续理想的离散化底会抬高读数"
                 "（引擎每参考周期一步）；结论只看失配敏感度。",
                 f"{sps:.1f} samples/symbol < 8: the engine's per-ref-cycle "
                 "grid floors the comparison — trust the mismatch trend."))

if st.button("Run", type="primary"):
    with st.spinner(L("调制仿真中…", "modulating...")):
        run = modulation_run(presets.ALL_PRESETS[nm](), rb, dp_err, n_cyc, seed=2)
    e = run.evm
    metric_row([("EVM", f"{e['evm_pct']:.2f} %"),
                ("EVM", f"{e['evm_db']:.1f} dB"),
                (L("相位误差", "phase err"),
                 f"{e['phase_err_rms_deg']:.2f} deg rms")])
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(11, 4))
    modulation_axes(run, a1, a2)
    show_fig(fig)
    st.caption(L("失配 1% 即 EVM 三倍类（ex17）——两点校准的量化依据。",
                 "1% mismatch triples the EVM class (ex17) — the spec for "
                 "two-point calibration."))
