"""Four-paper JSSC benchmark anchor: published vs model, re-runnable."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # repo root

import streamlit as st
from _common import L, sidebar_lang_toggle

from pllsim import presets

st.set_page_config(page_title="Benchmarks", layout="wide")
sidebar_lang_toggle()

st.title(L("文献对标（四篇 JSSC）", "Literature benchmarks (four JSSC papers)"))

ROWS = [
    {"paper": "Gao'09 SSPLL 2.21G int-N (10k-100M)",
     "published [fs]": "150", "linear [fs]": 122, "time-domain [fs]": 139},
    {"paper": "Dartizio'23 DTC-BB digital PLL 9.25G frac-N",
     "published [fs]": "77", "linear [fs]": 57, "time-domain [fs]": 77},
    {"paper": "Markulic'16 SSPLL 10.24G int-N",
     "published [fs]": "176", "linear [fs]": 165, "time-domain [fs]": 154},
    {"paper": "Markulic'16 SSPLL 10.24G frac-N",
     "published [fs]": "198 (worst)", "linear [fs]": 199,
     "time-domain [fs]": 155},
    {"paper": "Wu'19 sampling PLL 6.25G frac-N (10k-10M)",
     "published [fs]": "75", "linear [fs]": 77, "time-domain [fs]": 78},
]
st.dataframe(ROWS, use_container_width=True)
st.caption(L("完整方法学与假设清单见 examples/ex10、ex14 与 docs §11.4；"
             "所有未公开电路参数均为标注过的工艺合理假设——验证的是架构一致性。",
             "full methodology in examples/ex10, ex14 and docs 11.4; all "
             "undisclosed parameters are labelled technology-plausible "
             "assumptions — the check is architectural consistency."))

st.subheader(L("现场重跑（线性模型，数秒）",
               "Re-run live (linear models, seconds)"))
if st.button("Re-run linear models", type="primary"):
    # built from the bench_* presets, not from tests/: the test suite is not
    # shipped in the exe, so importing it worked from a checkout and raised
    # ModuleNotFoundError for anyone running the packaged build
    with st.spinner("running..."):
        rows = []
        for name, pll, pub in [
                ("Dartizio'23 (linear under-reads BB loops)",
                 presets.bench_dartizio23_adpllbb_500m_9p2515g(), "77"),
                ("Markulic'16 int-N",
                 presets.bench_markulic16_sspll_40m_10p24g(), "176"),
                ("Markulic'16 frac-N",
                 presets.bench_markulic16_sspll_frac_40m_10p25g(), "198"),
                ("Wu'19", presets.bench_wu19_spll_frac_52m_6p253g(), "75")]:
            ar = pll.analyze()
            rows.append({"benchmark": name, "published [fs]": pub,
                         "linear model [fs]": round(float(ar.jitter_fs), 1)})
    st.dataframe(rows, use_container_width=True)
    st.caption(L("时域数字请跑 examples/ex14（约 23 s）。",
                 "for the time-domain numbers run examples/ex14 (~23 s)."))
