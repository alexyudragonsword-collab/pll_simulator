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
        self.list.setSelectionMode(QAbstractItemView.ExtendedSelection)
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
