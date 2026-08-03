"""Analysis pages: spur prediction, measured-PN fitting, benchmarks."""
from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from .. import presets
from ..core.jitter import ldbc_from_sphi
from ..fit import attribute_budget, fit_closed_loop, fit_leeson, load_pn_csv
from ..guiutil import frac_presets, make_pll
from ..plotting import plot_spur_spectrum
from .i18n import tr
from .widgets import FigList, Page, float_edit, table_from_rows

FRAC_PRESETS = frac_presets()


class SpursPage(Page):
    title = "Spur prediction"
    title_zh = "杂散预测"

    def __init__(self):
        super().__init__()
        lay = QVBoxLayout(self)
        row = QHBoxLayout()
        self.preset = QComboBox()
        self.preset.addItems(FRAC_PRESETS)
        row.addWidget(tr(QLabel(), "预设", "preset"))
        row.addWidget(self.preset)
        self.inl_amp = float_edit("50e-15")
        self.inl_cyc = float_edit("1.0")
        self.gain_eps = float_edit("0.002")
        for zh, en, w in [("正弦 INL 幅度 [s]", "sine INL amp [s]", self.inl_amp),
                          ("INL 周期数", "INL cycles", self.inl_cyc),
                          ("增益残差", "gain residual", self.gain_eps)]:
            row.addWidget(tr(QLabel(), zh, en))
            row.addWidget(w)
        self.btn = tr(QPushButton(), "预测", "Predict")
        self.btn_sweep = tr(QPushButton(), "最差通道扫描", "Worst-channel sweep")
        self.btn_meas = tr(QPushButton(), "仿真并画谱",
                           "Simulate + plot spectrum")
        row.addWidget(self.btn)
        row.addWidget(self.btn_sweep)
        row.addWidget(self.btn_meas)
        row.addStretch(1)
        lay.addLayout(row)
        self._body = QVBoxLayout()
        lay.addLayout(self._body)
        self.figs = FigList()
        lay.addWidget(self.figs, 1)
        self.btn.clicked.connect(self._go)
        self.btn_sweep.clicked.connect(self._go_sweep)
        self.btn_meas.clicked.connect(self._go_measure)

    def _go_measure(self):
        """The table is the prediction; this is the measured periodogram of
        the same config, which is the comparison ex15 is built on."""
        def fn():
            pll = self._cfg_pll()
            return pll.simulate(150_000, seed=2), self._cfg_pll().analyze()

        def done(res):
            sim, ar = res
            self.figs.set_figs([plot_spur_spectrum(sim, ar=ar)])
        self.run_async(fn, done, self.btn_meas)

    def _cfg_pll(self, frac=None):
        pll = make_pll(self.preset.currentText())
        if frac is not None:
            pll.cfg.fout = (int(pll.cfg.fout / pll.cfg.fref) + frac) \
                * pll.cfg.fref
            pll.cfg.frac.frac = frac
        amp = float(self.inl_amp.text())
        pll.cfg.frac.dtc.inl_sin = (amp, float(self.inl_cyc.text()), 0.3) \
            if amp else ()
        pll.cfg.frac.dtc.gain_error_residual = float(self.gain_eps.text())
        return pll

    def _go(self):
        def fn():
            ar = self._cfg_pll().analyze()
            return sorted(((k, float(v)) for k, v in
                           ar.spurs_analytic.items()
                           if k.startswith("frac_spur")),
                          key=lambda kv: -kv[1])

        def done(tab):
            while self._body.count():
                w = self._body.takeAt(0).widget()
                if w is not None:
                    w.deleteLater()
            self._body.addWidget(table_from_rows(
                [{"offset": k.split("@")[1], "spur [dBc]": f"{v:.1f}"}
                 for k, v in tab]))
        self.run_async(fn, done, self.btn, self.btn_sweep)

    def _go_sweep(self):
        def fn():
            fracs = [0.0013, 0.0053, 0.0161, 0.0503, 0.1253, 0.2503,
                     0.3753, 0.4703]
            worst, fref = [], None
            for fr in fracs:
                pll = self._cfg_pll(frac=fr)
                fref = pll.cfg.fref
                ar = pll.analyze()
                t = [v for k, v in ar.spurs_analytic.items()
                     if k.startswith("frac_spur")]
                worst.append(max(t) if t else np.nan)
            return fracs, worst, fref

        def done(res):
            fracs, worst, fref = res
            fig, ax = plt.subplots(figsize=(7, 4))
            ax.semilogx([f * fref for f in fracs], worst, "o-")
            ax.set_xlabel("fractional beat frac*fref [Hz]")
            ax.set_ylabel("worst spur [dBc]")
            ax.set_title("worst channel is near the integer boundary")
            ax.grid(alpha=0.3, which="both")
            self.figs.set_figs([fig])
        self.run_async(fn, done, self.btn, self.btn_sweep)


class FitPage(Page):
    title = "Measured-PN fitting"
    title_zh = "实测相噪拟合"

    def __init__(self):
        super().__init__()
        lay = QVBoxLayout(self)
        row = QHBoxLayout()
        self.btn_open = tr(QPushButton(), "打开 CSV…", "Open CSV...")
        self.btn_demo = tr(QPushButton(), "载入合成示例",
                           "Load synthetic demo")
        self.mode = QComboBox()
        self.mode.addItems(["free-running (Leeson)", "locked spectrum",
                            "budget attribution"])
        self.baseline = QComboBox()
        self.baseline.addItems(list(presets.ALL_PRESETS))
        self.baseline.setCurrentText("spll_frac_52m_6p253g")
        self.btn_fit = tr(QPushButton(), "拟合", "Fit")
        row.addWidget(self.btn_open)
        row.addWidget(self.btn_demo)
        row.addWidget(tr(QLabel(), "模式", "mode"))
        row.addWidget(self.mode)
        row.addWidget(tr(QLabel(), "预算基准", "budget baseline"))
        row.addWidget(self.baseline)
        row.addWidget(self.btn_fit)
        row.addStretch(1)
        lay.addLayout(row)
        self.status = tr(QLabel(), "未载入数据", "no data loaded")
        lay.addWidget(self.status)
        self._body = QVBoxLayout()
        lay.addLayout(self._body)
        self.figs = FigList()
        lay.addWidget(self.figs, 1)
        self._data = None
        self.btn_open.clicked.connect(self._open)
        self.btn_demo.clicked.connect(self._demo)
        self.btn_fit.clicked.connect(self._go)

    def _open(self):
        path, _ = QFileDialog.getOpenFileName(self, "Phase-noise CSV")
        if path:
            f, l = load_pn_csv(path)
            self._data = (f, l)
            self.status.setText(f"{Path(path).name}: {f.size} points, "
                                f"{f[0]:.3g}-{f[-1]:.3g} Hz")

    def _demo(self):
        pll = presets.spll_frac_52m_6p253g()
        ar = pll.analyze()
        sel = (ar.f >= 3e3) & (ar.f <= 40e6)
        rng = np.random.default_rng(42)
        f = ar.f[sel]
        l = ldbc_from_sphi(ar.pn_breakdown["total"][sel]) \
            + rng.normal(0, 0.5, int(sel.sum()))
        self._data = (f, l)
        self.status.setText(f"synthetic demo (Wu'19-class SPLL + 0.5 dB "
                            f"instrument noise): {f.size} points")

    def _go(self):
        if self._data is None:
            self._demo()
        f, l = self._data
        mode = self.mode.currentText()
        base = self.baseline.currentText()

        def fn():
            if mode.startswith("free"):
                return ("leeson", fit_leeson(f, l))
            if mode.startswith("locked"):
                return ("closed", fit_closed_loop(f, l))
            return ("attr", attribute_budget(presets.ALL_PRESETS[base](),
                                             f, l))

        def done(res):
            kind, r = res
            while self._body.count():
                w = self._body.takeAt(0).widget()
                if w is not None:
                    w.deleteLater()
            fig, ax = plt.subplots(figsize=(8, 4.2))
            ax.semilogx(f, l, ".", ms=3, alpha=0.5, label="data")
            if kind == "leeson":
                rows = [{"parameter": "L(1MHz) 1/f^2",
                         "value": f"{r.pn_dbchz:.1f} dBc/Hz"},
                        {"parameter": "1/f^3 corner",
                         "value": f"{r.pn_f1f3 / 1e3:.0f} kHz"},
                        {"parameter": "floor",
                         "value": f"{r.pn_floor_dbchz:.1f} dBc/Hz"},
                        {"parameter": "residual",
                         "value": f"{r.residual_db_rms:.2f} dB rms"}]
                k3, k2, fl = r.k
                ax.semilogx(f, 10 * np.log10(
                    (k3 / f**3 + k2 / f**2 + fl) / 2), "r", lw=1.8,
                    label="Leeson fit")
            elif kind == "closed":
                rows = [{"parameter": "in-band",
                         "value": f"{r.inband_dbchz:.1f} dBc/Hz"},
                        {"parameter": "f_3db",
                         "value": f"{r.f_3db / 1e3:.0f} kHz"},
                        {"parameter": "UGB est",
                         "value": f"{r.f_ugb / 1e3:.0f} kHz"},
                        {"parameter": "peaking",
                         "value": f"{r.peaking_db:.1f} dB"},
                        {"parameter": "skirt L(1M) AS SEEN (VCO bound)",
                         "value": f"{r.osc.pn_dbchz:.1f} dBc/Hz"}]
            else:
                rows = [{"group": "+".join(g),
                         "factor": f"{r.factors[g]:.2f}",
                         "dB": f"{r.factors_db[g]:+.1f}"}
                        for g in r.groups]
            self._body.addWidget(table_from_rows(rows))
            ax.set_xlabel("offset [Hz]")
            ax.set_ylabel("L(f) [dBc/Hz]")
            ax.legend()
            ax.grid(alpha=0.3, which="both")
            self.figs.set_figs([fig])
        self.run_async(fn, done, self.btn_fit)


class BenchmarksPage(Page):
    title = "Benchmarks"
    title_zh = "文献对标"

    # published vs the linear model, for the re-run button.  Built from the
    # bench_* presets rather than from tests/, because a packaged build ships
    # no test suite and importing one there is a guaranteed ImportError.
    LIVE = [("Dartizio'23 (linear under-reads BB loops)",
             "bench_dartizio23_adpllbb_500m_9p2515g", "77"),
            ("Markulic'16 int-N", "bench_markulic16_sspll_40m_10p24g", "176"),
            ("Markulic'16 frac-N",
             "bench_markulic16_sspll_frac_40m_10p25g", "198"),
            ("Wu'19", "bench_wu19_spll_frac_52m_6p253g", "75")]

    def __init__(self):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.addWidget(tr(
            QLabel(),
            "四篇 JSSC 论文、五个通道 —— 所有未公开的电路参数都是标注过的工艺"
            "合理假设；验证的是架构一致性（examples/ex10、ex14，docs 11.4）。",
            "Four JSSC papers, five channels — all undisclosed parameters are "
            "labelled technology-plausible assumptions; the check is "
            "architectural consistency (examples/ex10, ex14, docs 11.4)."))
        lay.addWidget(table_from_rows(presets.benchmark_table()))
        row = QHBoxLayout()
        self.btn = tr(QPushButton(), "现场重跑（线性模型，数秒）",
                      "Re-run live (linear models, seconds)")
        row.addWidget(self.btn)
        row.addStretch(1)
        lay.addLayout(row)
        self._body = QVBoxLayout()
        lay.addLayout(self._body)
        lay.addStretch(1)
        self.btn.clicked.connect(self._go)

    def _go(self):
        def fn():
            return [{"benchmark": label,
                     "published [fs]": pub,
                     "linear model [fs]": round(
                         float(getattr(presets, mk)().analyze().jitter_fs), 1)}
                    for label, mk, pub in self.LIVE]

        def done(rows):
            while self._body.count():
                w = self._body.takeAt(0).widget()
                if w is not None:
                    w.deleteLater()
            self._body.addWidget(table_from_rows(rows))
            self._body.addWidget(tr(
                QLabel(),
                "时域数字请跑 examples/ex14（约 23 s）。",
                "for the time-domain numbers run examples/ex14 (~23 s)."))
        self.run_async(fn, done, self.btn)
