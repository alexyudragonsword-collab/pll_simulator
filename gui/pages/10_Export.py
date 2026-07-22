"""Verilog-AMS export: three-layer bundle, zipped for download."""
import io
import sys
import tempfile
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import streamlit as st

from _common import L, sidebar_lang_toggle

st.set_page_config(page_title="VAMS export", layout="wide")
sidebar_lang_toggle()

from pllsim import presets
from pllsim.export import export

st.title(L("Verilog-AMS 导出", "Verilog-AMS export"))
st.caption(L("每配置三层：位真 RTL（iverilog 零容差验证）、cycle-true "
             "wreal/RNM（黄金 CSV 回放）、电气级 AMS 网表 —— Cadence xrun "
             "命令行写在生成的 README 里。",
             "three layers per config: bit-true RTL, cycle-true wreal/RNM "
             "with golden-CSV replay, electrical AMS — xrun lines in the "
             "generated README."))
sel = st.multiselect("presets", list(presets.ALL_PRESETS),
                     default=["spll_frac_52m_6p253g"])
n_golden = int(st.number_input(L("黄金序列长度", "golden length"),
                               1024, 65536, 4096, 1024))

if st.button("Export", type="primary") and sel:
    buf = io.BytesIO()
    logs = []
    with st.spinner(L("导出中…", "exporting...")):
        with tempfile.TemporaryDirectory() as td:
            for nm in sel:
                rep = export(presets.ALL_PRESETS[nm](), td, name=nm,
                             n_golden=n_golden, n_vectors=1024)
                logs.append(rep.summary())
            with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
                for p in Path(td).rglob("*"):
                    if p.is_file():
                        zf.write(p, p.relative_to(td))
    for line in logs:
        st.write("• " + line)
    st.download_button(L("下载 vams_export.zip", "download vams_export.zip"),
                       buf.getvalue(), file_name="vams_export.zip",
                       mime="application/zip")
