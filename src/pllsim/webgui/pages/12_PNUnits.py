"""Phase-noise unit conversion: degrees <-> jitter <-> integrated dBc."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import streamlit as st
from _common import L, metric_row, sidebar_lang_toggle

st.set_page_config(page_title="PN units", layout="wide")
sidebar_lang_toggle()

from pllsim.core.jitter import HALF_POWER_DB, convert_phase_noise

st.title(L("相噪单位换算", "Phase-noise unit conversion"))
st.caption(L(
    "同一个 RMS 相位的三种写法。选一个作为输入，另外两个跟着算。"
    "dBc 有两种约定，相差 10log10(2) = 3.0103 dB —— 用错约定，"
    "由它推出的抖动差 √2 倍，所以两个都列。",
    "One RMS phase deviation, three ways of writing it. Pick which one you "
    "are supplying and the other two follow. dBc comes in two conventions "
    "10*log10(2) = 3.0103 dB apart; read a figure under the wrong one and "
    "every jitter from it is off by sqrt(2), so both are shown."))

# A selector plus one value, rather than three fields that drive each other:
# Streamlit reruns the whole script on any widget change, so three mutually
# writing inputs would need session-state bookkeeping to decide which one the
# user actually touched.  Naming the source is the same information, stated
# once.  The Qt page can afford live three-way binding because Qt's
# `textEdited` fires only for typing -- a genuine toolkit difference, recorded
# in cairn/android-app.md under Parity.
KINDS = {
    "deg": (L("RMS 相位 [deg]", "RMS phase [deg]"), "0.5"),
    "jitter_fs": (L("RMS 抖动 [fs]", "RMS jitter [fs]"), "100"),
    "ipn_dbc_dsb": (L("IPN [dBc] 双边带", "IPN [dBc] double-sideband"), "-40"),
    "ipn_dbc_ssb": (L("IPN [dBc] 单边带", "IPN [dBc] single-sideband"), "-40"),
}

c = st.columns(3)
f0 = c[0].text_input(L("载波 f0 [Hz]", "carrier f0 [Hz]"), "10e9")
kind = c[1].selectbox(L("已知量", "known quantity"), list(KINDS),
                      format_func=lambda k: KINDS[k][0])
value = c[2].text_input(KINDS[kind][0], KINDS[kind][1], key=f"val_{kind}")

try:
    u = convert_phase_noise(float(f0), **{kind: float(value)})
except (ValueError, ZeroDivisionError) as exc:
    st.error(str(exc))
    st.stop()

metric_row([
    (L("RMS 相位 [deg]", "RMS phase [deg]"), f"{u.deg:.6g}"),
    (L("RMS 抖动 [fs]", "RMS jitter [fs]"), f"{u.jitter_fs:.6g}"),
    (L("IPN 双边带 [dBc]", "IPN DSB [dBc]"), f"{u.ipn_dbc_dsb:.4f}"),
    (L("IPN 单边带 [dBc]", "IPN SSB [dBc]"), f"{u.ipn_dbc_ssb:.4f}"),
])
metric_row([
    (L("RMS 相位 [rad]", "RMS phase [rad]"), f"{u.rad:.4e}"),
    (L("RMS 抖动 [ps]", "RMS jitter [ps]"), f"{u.jitter_ps:.4g}"),
    (L("RMS 抖动 [s]", "RMS jitter [s]"), f"{u.jitter_s:.4e}"),
])

if not u.small_angle:
    st.warning(L(
        f"{u.deg:.3g}° 已超出小角度近似：载波被明显压低，dBc 与相位功率"
        "不再是同一句话，这里的换算只能当量级看。",
        f"{u.deg:.3g}° is outside the small-angle picture: the carrier is "
        "measurably depressed, so dBc and phase power are no longer the same "
        "statement and these numbers are order-of-magnitude only."))

st.caption(L(
    f"单边带值就是本包其他页 `ipn_dbc` 报的那个数，比双边带低 "
    f"{HALF_POWER_DB:.4f} dB。载波只影响抖动：度数和 dBc 与 f0 无关，"
    "所以跨载波比较相噪性能要比 dBc 或度数，比 fs 是在比载波高不高。",
    f"The single-sideband value is what `ipn_dbc` reports elsewhere in this "
    f"package — {HALF_POWER_DB:.4f} dB below the double-sideband one. Only "
    "the jitter depends on the carrier: degrees and dBc do not, which is why "
    "comparing sources at different carriers is a comparison of dBc or "
    "degrees, and comparing fs is a comparison of carrier frequency."))
