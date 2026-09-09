"""Four-paper JSSC benchmark anchor: published vs model, re-runnable."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # repo root

import streamlit as st
from _common import L, show_fig, sidebar_lang_toggle

from pllsim import presets
from pllsim.plotting import plot_ipn_pie

st.set_page_config(page_title="Benchmarks", layout="wide")
sidebar_lang_toggle()

st.title(L("文献对标（七篇 JSSC 论文，八个通道，六种架构各有锚点）",
           "Literature benchmarks (seven JSSC papers, eight channels, "
           "one anchor per architecture)"))

ROWS = presets.benchmark_table()
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
        # one row per BENCHMARKS entry, so a paper added to presets shows
        # up here without a second hand-maintained list (the Qt page and
        # this one each carried one, both four rows short by 2026-09)
        rows = []
        for b in presets.BENCHMARKS:
            ar = presets.ALL_PRESETS[b["preset"]]().analyze()
            rows.append({"benchmark": b["paper"],
                         "published [fs]": b["published [fs]"],
                         "linear model [fs]": round(float(ar.jitter_fs), 1)})
    st.dataframe(rows, use_container_width=True)
    st.caption(L("时域数字请跑 examples/ex14（约 23 s）。",
                 "for the time-domain numbers run examples/ex14 (~23 s)."))

st.subheader(L("IPN 分解（线性模型）", "IPN breakdown (linear model)"))
st.caption(L("表格回答“我们的数字和论文对不对得上”；饼图回答“先改哪一个”——"
             "两个不同的问题。份额是积分相位功率占比（各源不相关，加起来正好是"
             "总数）；图例里同时给出每个源自己的 RMS jitter，因为功率份额和抖动"
             "份额不是一回事。",
             "the table answers whether our number matches the paper; the pie "
             "answers which source to attack first — a different question.  "
             "Slices are shares of integrated phase power (the sources are "
             "uncorrelated and sum to the total); each label also carries "
             "that source's own RMS jitter, because a share of power is not "
             "a share of jitter."))
pie_preset = st.selectbox(L("对标预设", "benchmark preset"),
                          [b["preset"] for b in presets.BENCHMARKS],
                          key="pie_preset")
if st.button(L("画 IPN 饼图", "Plot IPN breakdown"), key="pie"):
    with st.spinner("analyze..."):
        ar = presets.ALL_PRESETS[pie_preset]().analyze()
    show_fig(plot_ipn_pie(ar, title=f"{pie_preset} — IPN breakdown"))
    st.dataframe([{"source": k, "share [%]": round(share * 100, 1),
                   "jitter [fs]": round(j, 1)}
                  for k, share, j in ar.ipn_shares()],
                 use_container_width=True)
