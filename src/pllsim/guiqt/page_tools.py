"""Tool pages: phase-noise unit conversion, Monte Carlo yield, VAMS export."""
from __future__ import annotations

from functools import partial

from PySide6.QtWidgets import (
    QAbstractItemView,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)

from .. import presets
from ..core.fom import pll_jitter_fom, vco_fom
from ..core.jitter import HALF_POWER_DB, convert_phase_noise
from ..guiutil import mc_build_frac_cppll
from ..montecarlo import monte_carlo, plot_mc
from .i18n import L, tr
from .widgets import FigList, MetricRow, Page, float_edit


class UnitsPage(Page):
    """Degrees <-> jitter <-> integrated dBc, at one carrier.

    Three fields that drive each other.  The re-entrancy that usually plagues
    such a form is avoided by construction rather than by a guard flag: Qt's
    `textEdited` fires only for typing, never for `setText`, so writing the
    other two fields cannot bounce back.

    Both dBc conventions are shown, always.  A converter that reported one of
    them would be the very trap it exists to remove -- and the SSB column is
    the one that lines up with `ipn_dbc` on every other page here, so a reader
    can carry a number between them without a silent 3 dB.
    """

    title = "PN units"
    title_zh = "相噪单位换算"

    #: field key -> the convert_phase_noise keyword it supplies
    _SOURCES = {"deg": "deg", "jit": "jitter_fs", "dsb": "ipn_dbc_dsb"}

    def __init__(self):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.addWidget(tr(
            QLabel(),
            "同一个 RMS 相位的三种写法。填任意一个，另外两个立即跟着算。\n"
            "dBc 有两种约定，相差 10log10(2) = 3.0103 dB —— 用错约定，由它"
            "推出的抖动就差 √2 倍，所以两个都列出来。",
            "One RMS phase deviation, three ways of writing it.  Fill in any "
            "one and the other two follow.\ndBc comes in two conventions "
            "10*log10(2) = 3.0103 dB apart; read a figure under the wrong one "
            "and every jitter from it is off by sqrt(2), so both are shown."))

        top = QHBoxLayout()
        self.f0 = float_edit("10e9", width=130)
        top.addWidget(tr(QLabel(), "载波 f0 [Hz]", "carrier f0 [Hz]"))
        top.addWidget(self.f0)
        top.addStretch(1)
        lay.addLayout(top)

        grid = QGridLayout()
        self.deg = float_edit("0.5", width=150)
        self.jit = float_edit("", width=150)
        self.dsb = float_edit("", width=150)
        rows = [
            (self.deg, "RMS 相位 [deg]", "RMS phase [deg]"),
            (self.jit, "RMS 抖动 [fs]", "RMS jitter [fs]"),
            (self.dsb, "IPN [dBc] 双边带", "IPN [dBc] double-sideband"),
        ]
        for r, (w, zh, en) in enumerate(rows):
            grid.addWidget(tr(QLabel(), zh, en), r, 0)
            grid.addWidget(w, r, 1)
        grid.setColumnStretch(2, 1)
        lay.addLayout(grid)

        self.metrics = MetricRow()
        lay.addWidget(self.metrics)
        self.note = QLabel()
        self.note.setWordWrap(True)
        lay.addWidget(self.note)
        lay.addStretch(1)

        self._source = "deg"
        for key in self._SOURCES:
            edit = getattr(self, key)
            edit.textEdited.connect(partial(self._on_edit, key))
        # f0 moves the jitter but not the other two, so it recomputes from
        # whichever field the user last typed in rather than from a fixed one
        self.f0.textEdited.connect(lambda _t: self._recompute())
        self._recompute()

    def _on_edit(self, key: str, _text: str):
        self._source = key
        self._recompute()

    def _recompute(self):
        src = self._source
        try:
            f0 = float(self.f0.text())
            value = float(getattr(self, src).text())
            u = convert_phase_noise(f0, **{self._SOURCES[src]: value})
        except (ValueError, ZeroDivisionError) as exc:
            self.metrics.set_metrics([])
            self._blank_except(src)
            self.note.setText(
                f"<span style='color:#b3261e'>{exc}</span>")
            return

        pairs = {"deg": f"{u.deg:.6g}", "jit": f"{u.jitter_fs:.6g}",
                 "dsb": f"{u.ipn_dbc_dsb:.6g}"}
        for key, text in pairs.items():
            if key != src:
                getattr(self, key).setText(text)

        self.metrics.set_metrics([
            (L("IPN 单边带 [dBc]", "IPN single-sideband [dBc]"),
             f"{u.ipn_dbc_ssb:.4f}"),
            (L("RMS 相位 [rad]", "RMS phase [rad]"), f"{u.rad:.4e}"),
            (L("RMS 抖动 [ps]", "RMS jitter [ps]"), f"{u.jitter_ps:.4g}"),
        ])
        ssb = L("单边带值就是本包各页 <code>ipn_dbc</code> 报的那个数，"
                f"比双边带低 {HALF_POWER_DB:.4f} dB。",
                "The single-sideband value is what <code>ipn_dbc</code> "
                "reports on every other page here — "
                f"{HALF_POWER_DB:.4f} dB below the double-sideband one.")
        if not u.small_angle:
            self.note.setText(
                "<span style='color:#a15c00'>" +
                L(f"{u.deg:.3g}° 已超出小角度近似：载波被明显压低，dBc 与相位"
                  "功率不再是同一句话，这里的换算只能当量级看。",
                  f"{u.deg:.3g}° is outside the small-angle picture: the "
                  "carrier is measurably depressed, so dBc and phase power "
                  "are no longer the same statement and these numbers are "
                  "order-of-magnitude only.") + "</span><br>" + ssb)
        else:
            self.note.setText(f"<span style='color:#666'>{ssb}</span>")

    def _blank_except(self, src: str):
        for key in self._SOURCES:
            if key != src:
                getattr(self, key).setText("")


class MonteCarloPage(Page):
    title = "Monte Carlo"
    title_zh = "蒙特卡洛"

    def __init__(self):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.addWidget(tr(
            QLabel(),
            "对 ex11 小数N CPPLL 逐芯片抽取失配（电荷泵失配、泄漏、DTC "
            "增益/INL、Kvco、闪烁噪声拐点），每颗芯片的校准环路都在跑；多进程。",
            "Per-chip mismatch draws (CP mismatch, leakage, DTC gain/INL, "
            "Kvco, flicker corner) on the ex11 fractional-N CPPLL, with the "
            "calibration loops live on every chip; multiprocess."))
        row = QHBoxLayout()
        self.n_runs = float_edit("40", width=70)
        self.s_gain = float_edit("0.05")
        self.s_inl = float_edit("0.7e-12")
        self.n_cyc = float_edit("150000")
        self.lim_jit = float_edit("250")
        self.lim_cal = float_edit("0.02")
        for zh, en, w in [("芯片数", "chips", self.n_runs),
                          ("DTC 增益 sigma", "DTC gain sigma", self.s_gain),
                          ("INL sigma [s]", "INL sigma [s]", self.s_inl),
                          ("周期/芯片", "cycles/chip", self.n_cyc),
                          ("抖动上限 [fs]", "jitter limit [fs]", self.lim_jit),
                          ("校准残差上限", "cal residual limit", self.lim_cal)]:
            row.addWidget(tr(QLabel(), zh, en))
            row.addWidget(w)
        self.btn = tr(QPushButton(), "运行蒙特卡洛", "Run Monte Carlo")
        row.addWidget(self.btn)
        row.addStretch(1)
        lay.addLayout(row)
        self.metrics = MetricRow()
        lay.addWidget(self.metrics)
        self.summary = QPlainTextEdit()
        self.summary.setReadOnly(True)
        self.summary.setMaximumHeight(180)
        lay.addWidget(self.summary)
        self.figs = FigList()
        lay.addWidget(self.figs, 1)
        self.btn.clicked.connect(self._go)

    def _go(self):
        n_runs = int(float(self.n_runs.text()))
        build = partial(mc_build_frac_cppll,
                        s_gain=float(self.s_gain.text()),
                        s_inl=float(self.s_inl.text()),
                        n_cycles=int(float(self.n_cyc.text())))

        def fn():
            return monte_carlo(build, n_runs=n_runs, seed=42)

        def done(res):
            lim = float(self.lim_jit.text())
            y = res.yield_frac("jitter_fs", lim)
            # calibration yield: how many chips ended with the DTC gain
            # actually corrected, not merely with acceptable jitter.  A chip
            # can pass the jitter limit on a channel that barely exercises the
            # DTC and still ship with the calibration wrong.
            rows = [(L("完成", "ok"), f"{res.n_ok}/{res.n_runs}"),
                    (f"jitter < {lim:.0f} fs", f"{y * 100:.0f} %")]
            y_cal = self._cal_yield(res, float(self.lim_cal.text()))
            rows.append((L("校准进限", "cal within limit"),
                         "-" if y_cal is None else f"{y_cal * 100:.0f} %"))
            self.metrics.set_metrics(rows)
            self.summary.setPlainText(res.summary())
            self.figs.set_figs([plot_mc(res)])
        self.run_async(fn, done, self.btn)

    @staticmethod
    def _cal_yield(res, limit: float):
        """Fraction of chips whose residual DTC gain error is under `limit`.

        The calibrator converges on 1/(1+true_error), so the residual is
        |value * (1 + true_error) - 1|.  Returns None when the run carried no
        calibration trace.
        """
        import numpy as np
        g = res.metrics.get("cal_dtc_gain_final")
        err_true = res.params.get("dtc_gain_err")
        if g is None or err_true is None:
            return None
        resid = np.abs(g * (1.0 + err_true) - 1.0)
        return float(np.mean(resid < limit))


class ExportPage(Page):
    title = "VAMS export"
    title_zh = "VAMS 导出"

    def __init__(self):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.addWidget(tr(
            QLabel(),
            "每个配置导出三层：位真 RTL（导出时用 iverilog 验证）、带黄金 CSV "
            "回放的周期真 wreal/RNM、以及电气级 AMS 网表 —— xrun 命令行写在 "
            "生成的 README 里。",
            "Three layers per config: bit-true RTL (iverilog-verified at "
            "export), cycle-true wreal/RNM with golden-CSV replay, and an "
            "electrical AMS netlist — xrun command lines are written into "
            "the generated README."))
        self.list = QListWidget()
        self.list.addItems(list(presets.ALL_PRESETS))
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.list.setCurrentRow(list(presets.ALL_PRESETS)
                                .index("spll_frac_52m_6p253g"))
        self.list.setMaximumHeight(180)
        lay.addWidget(self.list)
        row = QHBoxLayout()
        self.n_golden = float_edit("4096")
        row.addWidget(tr(QLabel(), "黄金序列长度", "golden length"))
        row.addWidget(self.n_golden)
        self.btn = tr(QPushButton(), "导出到文件夹…", "Export to folder...")
        row.addWidget(self.btn)
        # parity with the web GUI, which has only ever offered a zip: a
        # directory is awkward to move off a build machine
        self.btn_zip = tr(QPushButton(), "导出为 zip…", "Export as zip...")
        row.addWidget(self.btn_zip)
        row.addStretch(1)
        lay.addLayout(row)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        lay.addWidget(self.log, 1)
        self.btn.clicked.connect(self._go)
        self.btn_zip.clicked.connect(self._go_zip)

    def _selection(self):
        return [i.text() for i in self.list.selectedItems()]

    def _export_into(self, outdir, sel, n_golden):
        from ..export import export
        return [export(presets.ALL_PRESETS[nm](), outdir, name=nm,
                       n_golden=n_golden, n_vectors=1024).summary()
                for nm in sel]

    def _go(self):
        sel = self._selection()
        if not sel:
            return
        outdir = QFileDialog.getExistingDirectory(
            self, L("导出目录", "Export directory"))
        if not outdir:
            return
        n_golden = int(float(self.n_golden.text()))

        def done(logs):
            self.log.setPlainText("\n".join(logs)
                                  + L(f"\n\n已写入 {outdir}",
                                      f"\n\nwritten to {outdir}"))
        self.run_async(lambda: self._export_into(outdir, sel, n_golden),
                       done, self.btn, self.btn_zip)

    def _go_zip(self):
        sel = self._selection()
        if not sel:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, L("保存 zip", "Save zip"), "vams_export.zip", "Zip (*.zip)")
        if not path:
            return
        n_golden = int(float(self.n_golden.text()))

        def fn():
            import tempfile
            import zipfile
            from pathlib import Path
            with tempfile.TemporaryDirectory() as tmp:
                logs = self._export_into(tmp, sel, n_golden)
                root = Path(tmp)
                with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
                    for f in sorted(root.rglob("*")):
                        if f.is_file():
                            zf.write(f, f.relative_to(root))
            return logs

        def done(logs):
            self.log.setPlainText("\n".join(logs)
                                  + L(f"\n\n已写入 {path}",
                                      f"\n\nwritten to {path}"))
        self.run_async(fn, done, self.btn, self.btn_zip)


class FomPage(Page):
    """Jitter FoM and VCO FoM, from numbers the caller supplies.

    Power is an input, never a computation.  pllsim models no current or
    supply anywhere, so a FoM this package derived end to end would have a
    fabricated factor in it -- the page says so rather than leaving a reader
    to assume the opposite.
    """

    title = "FoM"
    title_zh = "FoM 计算"

    def __init__(self):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.addWidget(tr(QLabel(),
                         "两个品质因数都把噪声对功耗归一化。功耗由你填 —— "
                         "本包不建模功耗，任何自称算出来的 FoM 都含有编造的因子。",
                         "Both figures normalize noise against the power it "
                         "cost.  Power is yours to supply: pllsim models none, "
                         "so a FoM it derived end to end would carry a "
                         "fabricated factor."))

        # ---------------------------------------------------------- PLL
        lay.addWidget(tr(QLabel(), "<b>PLL 抖动 FoM</b>",
                         "<b>PLL jitter FoM</b>"))
        lay.addWidget(QLabel(
            "<code>FoM = 10·log10[ (σt/1s)² · (P/1mW) ]</code>"))
        g = QGridLayout()
        self.p_jit = float_edit("100", width=130)
        self.p_pwr = float_edit("10", width=130)
        self.p_n = float_edit("", width=130)
        for r, (w, zh, en) in enumerate([
                (self.p_jit, "RMS 抖动 [fs]", "RMS jitter [fs]"),
                (self.p_pwr, "功耗 [mW]", "power [mW]"),
                (self.p_n, "倍频比 N（选填）", "divide ratio N (optional)")]):
            g.addWidget(tr(QLabel(), zh, en), r, 0)
            g.addWidget(w, r, 1)
        g.setColumnStretch(2, 1)
        lay.addLayout(g)
        self.pll_metrics = MetricRow()
        lay.addWidget(self.pll_metrics)
        self.pll_note = QLabel()
        self.pll_note.setWordWrap(True)
        lay.addWidget(self.pll_note)

        # ---------------------------------------------------------- VCO
        lay.addWidget(tr(QLabel(), "<b>VCO FoM</b>", "<b>VCO FoM</b>"))
        lay.addWidget(QLabel(
            "<code>FoM = L(Δf) − 20·log10(f0/Δf) "
            "+ 10·log10(P/1mW)</code>"))
        g2 = QGridLayout()
        self.v_f0 = float_edit("10e9", width=130)
        self.v_off = float_edit("1e6", width=130)
        self.v_l = float_edit("-120", width=130)
        self.v_pwr = float_edit("10", width=130)
        self.v_ftr = float_edit("", width=130)
        for r, (w, zh, en) in enumerate([
                (self.v_f0, "载波 f0 [Hz]", "carrier f0 [Hz]"),
                (self.v_off, "偏移 Δf [Hz]", "offset Δf [Hz]"),
                (self.v_l, "L(Δf) [dBc/Hz] 单边带",
                 "L(Δf) [dBc/Hz] single-sideband"),
                (self.v_pwr, "功耗 [mW]", "power [mW]"),
                (self.v_ftr, "调谐范围 [%]（选填）",
                 "tuning range [%] (optional)")]):
            g2.addWidget(tr(QLabel(), zh, en), r, 0)
            g2.addWidget(w, r, 1)
        g2.setColumnStretch(2, 1)
        lay.addLayout(g2)
        self.vco_metrics = MetricRow()
        lay.addWidget(self.vco_metrics)
        self.vco_note = QLabel()
        self.vco_note.setWordWrap(True)
        lay.addWidget(self.vco_note)
        lay.addStretch(1)

        for w in (self.p_jit, self.p_pwr, self.p_n):
            w.textEdited.connect(lambda _t: self._pll())
        for w in (self.v_f0, self.v_off, self.v_l, self.v_pwr, self.v_ftr):
            w.textEdited.connect(lambda _t: self._vco())
        self._pll()
        self._vco()

    @staticmethod
    def _opt(edit) -> float | None:
        text = edit.text().strip()
        return float(text) if text else None

    def _pll(self):
        try:
            r = pll_jitter_fom(float(self.p_jit.text()) * 1e-15,
                               float(self.p_pwr.text()),
                               n=self._opt(self.p_n))
        except (ValueError, ZeroDivisionError) as exc:
            self.pll_metrics.set_metrics([])
            self.pll_note.setText(f"<span style='color:#b3261e'>{exc}</span>")
            return
        items = [("FoM [dB]", f"{r.fom_db:.2f}")]
        if r.fom_n_db is not None:
            items.append((L("FoM_N [dB]", "FoM_N [dB]"), f"{r.fom_n_db:.2f}"))
        self.pll_metrics.set_metrics(items)
        note = L("抖动减半得 6 dB，功耗减半只得 3 dB —— 这个 2:1 权重正是"
                 "该指标的内容：堆电流换抖动不会让它变好。",
                 "Halving jitter gains 6 dB; halving power gains 3 dB.  That "
                 "2:1 weighting is the content of the figure — spending "
                 "current to buy jitter does not improve it.")
        if r.fom_n_db is not None:
            note += L(" 本包 FoM_N 取 <code>FoM − 10·log10(N)</code>，"
                      "即奖励更高倍频比；文献里也有写成加号的。",
                      " FoM_N here is <code>FoM − 10·log10(N)</code>, which "
                      "rewards a higher ratio; the literature also writes it "
                      "as an addition.")
        self.pll_note.setText(f"<span style='color:#666'>{note}</span>")

    def _vco(self):
        try:
            r = vco_fom(float(self.v_f0.text()), float(self.v_off.text()),
                        float(self.v_pwr.text()),
                        l_dbc_hz=float(self.v_l.text()),
                        ftr_pct=self._opt(self.v_ftr))
        except (ValueError, ZeroDivisionError) as exc:
            self.vco_metrics.set_metrics([])
            self.vco_note.setText(f"<span style='color:#b3261e'>{exc}</span>")
            return
        items = [("FoM [dBc/Hz]", f"{r.fom_dbc_hz:.2f}")]
        if r.fom_t_dbc_hz is not None:
            items.append(("FoM_T [dBc/Hz]", f"{r.fom_t_dbc_hz:.2f}"))
        self.vco_metrics.set_metrics(items)
        self.vco_note.setText(
            "<span style='color:#a15c00'>" +
            L("L(Δf) 按定义是<b>单边带</b>；本包内部存的是双边带 S_φ，"
              f"两者差 {HALF_POWER_DB:.4f} dB，代错就整体偏 3 dB。"
              "另外那个 −20log10(f0/Δf) 假设此处按 20 dB/dec 滚降 —— "
              "在 1/f³ 拐点以内 FoM 会随偏移变化，不同偏移报的数字不可比。",
              "L(Δf) is <b>single sideband</b> by definition; this "
              "package stores double-sideband S_phi, "
              f"{HALF_POWER_DB:.4f} dB away, and the wrong one shifts "
              "everything by 3 dB.  The −20log10(f0/Δf) term also "
              "assumes 20 dB/decade here — inside the 1/f³ corner the FoM "
              "depends on the offset, and figures quoted at different offsets "
              "are not comparable.") + "</span>")
