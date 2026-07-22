"""pllsim GUI entry point:  streamlit run gui/Home.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import streamlit as st

from _common import L, sidebar_lang_toggle

st.set_page_config(page_title="pllsim", page_icon=":satellite:",
                   layout="wide")
sidebar_lang_toggle()

st.title("pllsim — " + L("PLL 系统级仿真工作台", "system-level PLL workbench"))

st.markdown(L(
    """
左侧页面覆盖工程的全部能力：

| 页面 | 功能 | 对应模块 |
|---|---|---|
| **架构工作台** | preset → 全参数编辑 → analyze()/simulate()，相噪分解、瞬态、校准轨迹 | `arch/*`, `plotting` |
| **环路综合** | UGB/PM 目标 → 滤波器/DLF 元件值，带宽扫描 | `synth` |
| **架构选型** | 需求表单 → 七架构排序 + 一键载入工作台 | `selector` |
| **杂散预测** | DTC INL/增益残差 → 确定性小数杂散表 + 最差通道扫描 | `core.dtcspurs` |
| **实测拟合** | 上传相噪 CSV → Leeson/闭环拟合、预算归因 | `fit` |
| **两点调制** | GMSK EVM 对直通路失配曲线 | `modulation` |
| **跳频建立** | 建立时间解剖、FLL 稳定性边界、种子分布 | `settling` |
| **温漂跟踪** | 增益斜坡下的后台 LMS 跟踪墙 | 引擎 `dtc_gain_drift` |
| **Monte Carlo** | 逐芯片失配抽样良率 | `montecarlo` |
| **VAMS 导出** | RTL/RNM/AMS 三层导出打包下载 | `export` |
| **文献对标** | 四篇 JSSC 对标汇总与重跑 | ex10/ex14 |

从 **架构工作台** 开始，或先用 **架构选型** 找到起点。
""",
    """
The pages on the left cover every capability of the project:

| Page | What it does | Module |
|---|---|---|
| **Workbench** | preset -> full parameter editing -> analyze()/simulate() | `arch/*` |
| **Synthesis** | UGB/PM targets -> filter/DLF component values, BW sweep | `synth` |
| **Selector** | requirement form -> 7-architecture ranking -> load into workbench | `selector` |
| **Spur prediction** | DTC INL/gain residual -> deterministic fractional-spur table | `core.dtcspurs` |
| **Measurement fit** | upload a PN CSV -> Leeson/closed-loop fits, budget attribution | `fit` |
| **Two-point mod** | GMSK EVM vs direct-path mismatch | `modulation` |
| **Hop settling** | settling anatomy, FLL stability bound, seed statistics | `settling` |
| **Drift tracking** | background-LMS tracking walls under gain ramps | engines |
| **Monte Carlo** | per-chip mismatch yield | `montecarlo` |
| **VAMS export** | three-layer export bundle download | `export` |
| **Benchmarks** | four-paper JSSC anchor, re-runnable | ex10/ex14 |

Start at the **Workbench**, or let the **Selector** pick your starting point.
"""))

try:
    from importlib.metadata import version
    st.caption(f"pllsim v{version('pllsim')}")
except Exception:
    pass
