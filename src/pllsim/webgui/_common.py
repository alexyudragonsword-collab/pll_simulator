"""Shared Streamlit pieces: bilingual labels, config forms, fig display."""
from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import streamlit as st

from pllsim.guiutil import enumerate_fields, fmt_value

GROUP_LABELS = {
    "": ("环路 / 顶层", "Loop / top level"),
    "osc": ("振荡器", "Oscillator"),
    "cp": ("电荷泵", "Charge pump"),
    "sampler": ("采样器", "Sampler"),
    "filt": ("环路滤波器", "Loop filter"),
    "tdc": ("TDC", "TDC"),
    "dlf": ("数字环路滤波器", "Digital loop filter"),
    "frac": ("小数N / DTC / 校准", "Fractional-N / DTC / cal"),
}


def lang() -> str:
    return st.session_state.setdefault("lang", "zh")


def L(zh: str, en: str) -> str:
    return zh if lang() == "zh" else en


def sidebar_lang_toggle():
    with st.sidebar:
        choice = st.radio("语言 / Language", ["中文", "English"],
                          index=0 if lang() == "zh" else 1, horizontal=True)
        st.session_state["lang"] = "zh" if choice == "中文" else "en"


def config_form(cfg, key_prefix: str) -> dict[str, str]:
    """Render editable fields grouped by sub-block; return {path: text}."""
    specs = enumerate_fields(cfg)
    groups: dict[str, list] = {}
    for s in specs:
        head = s.path.split(".")[0] if "." in s.path else ""
        groups.setdefault(head, []).append(s)
    overrides: dict[str, str] = {}
    for head, items in groups.items():
        gzh, gen = GROUP_LABELS.get(head, (head, head))
        with st.expander(L(gzh, gen), expanded=(head == "")):
            cols = st.columns(3)
            for i, s in enumerate(items):
                label = s.label_zh if lang() == "zh" else s.label_en
                if s.unit:
                    label += f" [{s.unit}]"
                txt = cols[i % 3].text_input(
                    label, value=fmt_value(s.value),
                    key=f"{key_prefix}:{s.path}", help=s.path)
                overrides[s.path] = txt
    return overrides


def changed_only(cfg, overrides: dict[str, str]) -> dict[str, str]:
    """Keep only fields the user actually edited (string-compare)."""
    base = {s.path: fmt_value(s.value) for s in enumerate_fields(cfg)}
    return {p: t for p, t in overrides.items()
            if p in base and t.strip() != base[p]}


def show_fig(fig):
    st.pyplot(fig, clear_figure=False)
    plt.close(fig)


def metric_row(items: list[tuple[str, str]]):
    cols = st.columns(len(items))
    for c, (name, val) in zip(cols, items):
        c.metric(name, val)
