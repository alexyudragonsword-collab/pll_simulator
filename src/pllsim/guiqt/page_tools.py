"""Tool pages: Monte Carlo yield and the Verilog-AMS export."""
from __future__ import annotations

from functools import partial

from PySide6.QtWidgets import (
    QAbstractItemView,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)

from .. import presets
from ..guiutil import mc_build_frac_cppll
from ..montecarlo import monte_carlo, plot_mc
from .widgets import FigList, MetricRow, Page, float_edit


class MonteCarloPage(Page):
    title = "Monte Carlo"

    def __init__(self):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(
            "Per-chip mismatch draws (CP mismatch, leakage, DTC gain/INL, "
            "Kvco, flicker corner) on the ex11 fractional-N CPPLL, with the "
            "calibration loops live on every chip; multiprocess."))
        row = QHBoxLayout()
        self.n_runs = float_edit("40", width=70)
        self.s_gain = float_edit("0.05")
        self.s_inl = float_edit("0.7e-12")
        self.n_cyc = float_edit("150000")
        self.lim_jit = float_edit("250")
        for lab, w in [("chips", self.n_runs), ("DTC gain sigma", self.s_gain),
                       ("INL sigma [s]", self.s_inl),
                       ("cycles/chip", self.n_cyc),
                       ("jitter limit [fs]", self.lim_jit)]:
            row.addWidget(QLabel(lab))
            row.addWidget(w)
        self.btn = QPushButton("Run Monte Carlo")
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
            self.metrics.set_metrics([
                ("ok", f"{res.n_ok}/{res.n_runs}"),
                (f"jitter < {lim:.0f} fs", f"{y * 100:.0f} %")])
            self.summary.setPlainText(res.summary())
            self.figs.set_figs([plot_mc(res)])
        self.run_async(fn, done, self.btn)


class ExportPage(Page):
    title = "VAMS export"

    def __init__(self):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(
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
        row.addWidget(QLabel("golden length"))
        row.addWidget(self.n_golden)
        self.btn = QPushButton("Export to folder...")
        row.addWidget(self.btn)
        row.addStretch(1)
        lay.addLayout(row)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        lay.addWidget(self.log, 1)
        self.btn.clicked.connect(self._go)

    def _go(self):
        sel = [i.text() for i in self.list.selectedItems()]
        if not sel:
            return
        outdir = QFileDialog.getExistingDirectory(self, "Export directory")
        if not outdir:
            return
        n_golden = int(float(self.n_golden.text()))

        def fn():
            from ..export import export
            logs = []
            for nm in sel:
                rep = export(presets.ALL_PRESETS[nm](), outdir, name=nm,
                             n_golden=n_golden, n_vectors=1024)
                logs.append(rep.summary())
            return logs

        def done(logs):
            self.log.setPlainText("\n".join(logs)
                                  + f"\n\nwritten to {outdir}")
        self.run_async(fn, done, self.btn)
