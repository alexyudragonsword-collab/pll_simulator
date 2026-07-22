"""Channel-hop settling: anatomy, FLL stability bound, seed statistics."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import matplotlib.pyplot as plt
import numpy as np
import streamlit as st

from _common import L, metric_row, show_fig, sidebar_lang_toggle

st.set_page_config(page_title="Hop settling", layout="wide")
sidebar_lang_toggle()

from pllsim import presets
from pllsim.settling import fll_stability, hop_settling, hop_statistics

st.title(L("跳频建立时间", "Channel-hop settling"))
c = st.columns(4)
nm = c[0].selectbox("preset", list(presets.ALL_PRESETS))
hop = float(c[1].text_input(L("跳频量 [Hz]（负=向下）", "hop [Hz]"), "-100e6"))
n_cyc = int(c[2].number_input(L("周期数", "cycles"), 50_000, 600_000,
                              200_000, 50_000))
seed = int(c[3].number_input("seed", 0, 9999, 1))

pll0 = presets.ALL_PRESETS[nm]()
if hasattr(pll0.cfg, "fll_i"):
    st_fll = fll_stability(pll0)
    ok = st_fll["margin"] > 1.0
    (st.success if ok else st.error)(
        f"FLL: slew {st_fll['slew_per_window_hz'] / 1e3:.0f} kHz/window, "
        f"i_fll_max {st_fll['i_fll_max_a'] * 1e6:.2f} uA, "
        f"margin {st_fll['margin']:.2f}x"
        + ("" if ok else L("  —— 超界：FLL 将极限环振荡、永不交接！",
                           "  — OVER the bound: limit cycle, never hands off!")))

if st.button("Run hop", type="primary"):
    with st.spinner(L("跳频仿真中…", "hopping...")):
        pll = presets.ALL_PRESETS[nm]()
        r = hop_settling(pll, pll.cfg.fout + hop, n_cycles=n_cyc, seed=seed)
    st.session_state["hop_r"] = r

r = st.session_state.get("hop_r")
if r is not None:
    metric_row([
        ("t_freq", f"{r.t_freq_s * 1e6:.1f} us"
         if np.isfinite(r.t_freq_s) else L("未建立", "not settled")),
        ("t_phase", f"{r.t_phase_s * 1e6:.1f} us"
         if np.isfinite(r.t_phase_s) else L("未建立", "not settled")),
        ("FLL", f"{r.fll_engaged_s * 1e6:.1f} us"
         if r.fll_engaged_s else "-"),
        ("jitter", f"{r.jitter_fs:.0f} fs" if r.jitter_fs else "-"),
    ])
    sim = r.sim
    fig, ax = plt.subplots(figsize=(9, 4))
    ax.plot(sim.t * 1e6, (sim.freq_out - r.f_to) / 1e6, lw=0.7)
    if "fll_engaged" in sim.cal_traces:
        eng = sim.cal_traces["fll_engaged"] > 0.5
        ax.fill_between(sim.t * 1e6, *ax.get_ylim(), where=eng, alpha=0.15,
                        color="C1", label="FLL engaged")
    if np.isfinite(r.t_phase_s):
        ax.axvline(r.t_phase_s * 1e6, color="r", ls="--", lw=1,
                   label=f"phase settled {r.t_phase_s * 1e6:.0f} us")
    ax.set_xlabel("t [us]")
    ax.set_ylabel("freq error [MHz]")
    ax.legend(fontsize=8)
    ax.grid(alpha=0.3)
    show_fig(fig)

st.subheader(L("种子分布（建立时间是良率量）",
               "Seed distribution (settling is a yield quantity)"))
n_seeds = int(st.number_input("seeds", 5, 50, 12))
if st.button("Run statistics"):
    with st.spinner(L(f"{n_seeds} 次跳频中…", f"{n_seeds} hops...")):
        stats = hop_statistics(lambda: presets.ALL_PRESETS[nm](),
                               presets.ALL_PRESETS[nm]().cfg.fout + hop,
                               seeds=range(n_seeds), n_cycles=n_cyc)
    metric_row([("p50", f"{stats['p50_s'] * 1e6:.0f} us"),
                ("p95", f"{stats['p95_s'] * 1e6:.0f} us"),
                (L("最差", "worst"), f"{stats['worst_s'] * 1e6:.0f} us"),
                (L("未建立", "failed"), f"{stats['fail_frac'] * 100:.0f} %")])
    tp = stats["t_phase_s"]
    fig, ax = plt.subplots(figsize=(7, 3.5))
    ax.hist(tp[np.isfinite(tp)] * 1e6, bins=12, alpha=0.8)
    ax.set_xlabel("t_phase [us]")
    ax.set_ylabel("hops")
    ax.grid(alpha=0.3)
    show_fig(fig)
