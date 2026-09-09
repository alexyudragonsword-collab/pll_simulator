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
    QSpinBox,
    QVBoxLayout,
)

from .. import presets
from ..core.jitter import ldbc_from_sphi
from ..fit import attribute_budget, fit_closed_loop, fit_leeson, load_pn_csv
from ..guiutil import (
    fine_oversample_note,
    fine_record_mb,
    frac_presets,
    make_pll,
    ref_spur_comparison,
    simulate_kwargs,
    supports_fine,
)
from ..plotting import plot_ipn_pie, plot_spur_spectrum
from .i18n import tr
from .widgets import FigList, Page, clear_layout, float_edit, table_from_rows

FRAC_PRESETS = frac_presets()


class SpursPage(Page):
    title = "Spur prediction"
    title_zh = "杂散预测"

    # a seam, not a setting: the measured spectrum wants a long record, and a
    # test that has to run 150k cycles to check a signature is a test nobody
    # keeps
    MEASURE_CYCLES = 150_000

    def __init__(self):
        super().__init__()
        lay = QVBoxLayout(self)
        row = QHBoxLayout()
        self.preset = QComboBox()
        self.preset.addItems(FRAC_PRESETS)
        self.preset.currentTextChanged.connect(self._fine_hint)
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

        # Reference spur.  This page could only ever show *fractional* spurs,
        # because the reference one lives inside a single reference period and
        # needs an intra-period record to be visible at all.
        row2 = QHBoxLayout()
        row2.addWidget(tr(QLabel(), "参考杂散 —— 周期内细采样 M",
                          "Reference spur -- intra-period samples M"))
        self.fine_os = QSpinBox()
        self.fine_os.setRange(2, 4096)
        self.fine_os.setSingleStep(32)
        self.fine_os.setValue(128)
        self.fine_os.valueChanged.connect(self._fine_hint)
        row2.addWidget(self.fine_os)
        self.btn_ref = tr(QPushButton(), "解析 vs 时域",
                          "Analytic vs time domain")
        self.btn_ref.clicked.connect(self._go_ref)
        row2.addWidget(self.btn_ref)
        self.fine_note = QLabel("")
        self.fine_note.setWordWrap(True)
        row2.addWidget(self.fine_note, 1)
        lay.addLayout(row2)
        self._body = QVBoxLayout()
        lay.addLayout(self._body)
        self.figs = FigList()
        lay.addWidget(self.figs, 1)
        self.btn.clicked.connect(self._go)
        self.btn_sweep.clicked.connect(self._go_sweep)
        self.btn_meas.clicked.connect(self._go_measure)

    def compute_measure(self):
        """The worker body, named so a test can call exactly what runs.

        M goes through simulate_kwargs rather than straight into simulate():
        two of the seven fractional presets in this page's own dropdown are
        ADPLLs, whose engines take no fine_oversample at all, so passing it
        unconditionally raised TypeError the moment either was selected.
        """
        pll = self._cfg_pll()
        kw = simulate_kwargs(pll, seed=2,
                             fine_oversample=int(self.fine_os.value()))
        return (pll.simulate(self.MEASURE_CYCLES, **kw),
                self._cfg_pll().analyze())

    def render_measure(self, res):
        sim, ar = res
        self.figs.set_figs([plot_spur_spectrum(sim, ar=ar)])

    def _go_measure(self):
        """The table is the prediction; this is the measured periodogram of
        the same config, which is the comparison ex15 is built on."""
        self.run_async(self.compute_measure, self.render_measure,
                       self.btn_meas)

    def _fine_hint(self):
        try:
            pll = self._cfg_pll()
        except Exception:            # a half-typed field; the run reports it
            self.fine_note.setText("")
            return
        m = int(self.fine_os.value())
        if not supports_fine(pll):
            # two of this page's own fractional presets are ADPLLs: the
            # control word is a register that holds between edges, so there
            # is no intra-period waveform and M buys nothing
            self.fine_note.setText("this architecture has no intra-period "
                                   "record — M is ignored")
            return
        note = fine_oversample_note(pll, m)
        mb = fine_record_mb(40_000, m)
        self.fine_note.setText(f"record ~{mb:.0f} MB"
                               + (f" — {note}" if note else ""))

    def compute_ref(self):
        """The worker body, named so a test can call exactly what runs."""
        return ref_spur_comparison(self._cfg_pll(), m=int(self.fine_os.value()))

    def render_ref(self, res):
        rows, notes = res
        clear_layout(self._body)
        if rows:
            self._body.addWidget(table_from_rows(rows))
        for n in notes:
            lab = QLabel("note: " + n)
            lab.setWordWrap(True)
            self._body.addWidget(lab)

    def _go_ref(self):
        self.run_async(self.compute_ref, self.render_ref, self.btn_ref)

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
            clear_layout(self._body)
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
        assert self._data is not None
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
            clear_layout(self._body)
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

    # published vs the linear model, for the re-run button.  Built from
    # presets.BENCHMARKS rather than from tests/ (a packaged build ships no
    # test suite) and rather than a local list (this page and the web page
    # each carried one, both four rows short by 2026-09).
    LIVE = [(b["paper"], b["preset"], b["published [fs]"])
            for b in presets.BENCHMARKS]

    def __init__(self):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.addWidget(tr(
            QLabel(),
            "七篇 JSSC 论文、八个通道，六种架构各有锚点 —— 所有未公开的电路参数"
            "都是标注过的工艺合理假设；验证的是架构一致性（examples/ex10、ex14，"
            "docs 11.4）。",
            "Seven JSSC papers, eight channels, one anchor per architecture — "
            "all undisclosed parameters are labelled technology-plausible "
            "assumptions; the check is architectural consistency "
            "(examples/ex10, ex14, docs 11.4)."))
        lay.addWidget(table_from_rows(presets.benchmark_table()))
        row = QHBoxLayout()
        self.btn = tr(QPushButton(), "现场重跑（线性模型，数秒）",
                      "Re-run live (linear models, seconds)")
        row.addWidget(self.btn)
        row.addStretch(1)
        lay.addLayout(row)
        self._body = QVBoxLayout()
        lay.addLayout(self._body)

        # Which source to attack first is a different question from "does
        # our number match the paper", and the table cannot answer it.
        row2 = QHBoxLayout()
        row2.addWidget(tr(QLabel(), "IPN 分解", "IPN breakdown"))
        self.pie_preset = QComboBox()
        self.pie_preset.addItems([b["preset"] for b in presets.BENCHMARKS])
        row2.addWidget(self.pie_preset, 1)
        self.btn_pie = tr(QPushButton(), "画饼图", "Pie chart")
        row2.addWidget(self.btn_pie)
        row2.addStretch(1)
        lay.addLayout(row2)
        self.figs = FigList()
        lay.addWidget(self.figs, 1)
        self.btn.clicked.connect(self._go)
        self.btn_pie.clicked.connect(self._go_pie)

    def compute_pie(self):
        """The worker body, named so a test can call exactly what runs."""
        name = self.pie_preset.currentText()
        return name, presets.ALL_PRESETS[name]().analyze()

    def render_pie(self, res):
        name, ar = res
        self.figs.set_figs([plot_ipn_pie(ar, title=f"{name} — IPN breakdown")])

    def _go_pie(self):
        self.run_async(self.compute_pie, self.render_pie, self.btn_pie)

    def _go(self):
        def fn():
            return [{"benchmark": label,
                     "published [fs]": pub,
                     "linear model [fs]": round(
                         float(getattr(presets, mk)().analyze().jitter_fs), 1)}
                    for label, mk, pub in self.LIVE]

        def done(rows):
            clear_layout(self._body)
            self._body.addWidget(table_from_rows(rows))
            self._body.addWidget(tr(
                QLabel(),
                "时域数字请跑 examples/ex14（约 23 s）。",
                "for the time-domain numbers run examples/ex14 (~23 s)."))
        self.run_async(fn, done, self.btn)
