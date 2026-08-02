"""Architecture workbench: preset -> full parameter edit -> analyze/simulate."""
from __future__ import annotations

import matplotlib.pyplot as plt
import numpy as np
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .. import presets
from ..guiutil import make_pll, osc_bank_report, simulate_kwargs
from ..plotting import plot_pn_breakdown
from .widgets import (
    ConfigForm,
    FigList,
    MetricRow,
    Page,
    float_edit,
    in_scroll,
    table_from_rows,
)


class WorkbenchPage(Page):
    title = "Workbench"

    def __init__(self):
        super().__init__()
        lay = QVBoxLayout(self)

        top = QHBoxLayout()
        top.addWidget(QLabel("Preset:"))
        self.preset = QComboBox()
        self.preset.addItems(list(presets.ALL_PRESETS))
        self.preset.currentTextChanged.connect(self._rebuild_form)
        top.addWidget(self.preset)
        self.info = QLabel("")
        top.addWidget(self.info)
        top.addStretch(1)
        lay.addLayout(top)

        split = QSplitter()
        lay.addWidget(split, 1)

        # left: the auto-generated config form
        self._form_host = QWidget()
        self._form_lay = QVBoxLayout(self._form_host)
        self._form_lay.setContentsMargins(0, 0, 0, 0)
        split.addWidget(in_scroll(self._form_host))

        # right: analyze / simulate tabs
        right = QTabWidget()
        split.addWidget(right)
        split.setSizes([380, 780])

        # --- analyze tab
        atab = QWidget()
        alay = QVBoxLayout(atab)
        self.btn_analyze = QPushButton("Run analyze()")
        self.btn_analyze.clicked.connect(self._go_analyze)
        alay.addWidget(self.btn_analyze)
        self.a_metrics = MetricRow()
        alay.addWidget(self.a_metrics)
        self._a_body = QWidget()
        self._a_lay = QVBoxLayout(self._a_body)
        alay.addWidget(in_scroll(self._a_body), 1)
        right.addTab(atab, "Analyze (linear model)")

        # --- simulate tab
        stab = QWidget()
        slay = QVBoxLayout(stab)
        row = QHBoxLayout()
        row.addWidget(QLabel("cycles"))
        self.n_cycles = QSpinBox()
        self.n_cycles.setRange(10_000, 2_000_000)
        self.n_cycles.setSingleStep(10_000)
        self.n_cycles.setValue(150_000)
        row.addWidget(self.n_cycles)
        row.addWidget(QLabel("seed"))
        self.seed = QSpinBox()
        self.seed.setRange(0, 9999)
        self.seed.setValue(1)
        row.addWidget(self.seed)
        row.addWidget(QLabel("start offset [Hz]"))
        self.f_off = float_edit("0")
        row.addWidget(self.f_off)
        self.cb_noise = QCheckBox("noise")
        self.cb_noise.setChecked(True)
        row.addWidget(self.cb_noise)
        self.cb_cal = QCheckBox("calibration")
        self.cb_cal.setChecked(True)
        row.addWidget(self.cb_cal)
        row.addWidget(QLabel("DTC gain err"))
        self.dtc_err = float_edit("0")
        row.addWidget(self.dtc_err)
        row.addStretch(1)
        slay.addLayout(row)
        self.btn_sim = QPushButton("Run simulate()")
        self.btn_sim.clicked.connect(self._go_sim)
        slay.addWidget(self.btn_sim)
        self.s_metrics = MetricRow()
        slay.addWidget(self.s_metrics)
        self._s_body = QWidget()
        self._s_lay = QVBoxLayout(self._s_body)
        slay.addWidget(in_scroll(self._s_body), 1)
        right.addTab(stab, "Simulate (time domain)")

        self._rebuild_form(self.preset.currentText())

    # ------------------------------------------------------------- helpers
    def _rebuild_form(self, name: str):
        while self._form_lay.count():
            w = self._form_lay.takeAt(0).widget()
            if w is not None:
                w.deleteLater()
        pll = presets.ALL_PRESETS[name]()
        self.form = ConfigForm(pll.cfg)
        self._form_lay.addWidget(self.form)
        self.info.setText(f"{type(pll).__name__}: "
                          f"fref {pll.cfg.fref / 1e6:g} MHz -> "
                          f"fout {pll.cfg.fout / 1e9:.6g} GHz")

    def _pll(self):
        return make_pll(self.preset.currentText(), self.form.overrides())

    @staticmethod
    def _clear(lay):
        while lay.count():
            w = lay.takeAt(0).widget()
            if w is not None:
                w.deleteLater()

    # ------------------------------------------------------------- analyze
    def compute_analyze(self):
        return self._pll().analyze()

    def render_analyze(self, ar):
        self.a_metrics.set_metrics([
            ("jitter", f"{ar.jitter_fs:.1f} fs"),
            ("IPN", f"{ar.ipn_dbc:.1f} dBc"),
            ("UGB", f"{ar.loop.f_ugb / 1e3:.0f} kHz"
             if np.isfinite(ar.loop.f_ugb) else "-"),
            ("PM", f"{ar.loop.pm_deg:.0f} deg"
             if np.isfinite(ar.loop.pm_deg) else "-"),
        ])
        self._clear(self._a_lay)
        # coarse-band sizing: only meaningful once the varactor has a range
        try:
            bank = osc_bank_report(self._pll().cfg)
        except Exception:
            bank = []
        if bank:
            self._a_lay.addWidget(QLabel("Coarse band bank "
                                         "(osc.v_min / v_max):"))
            self._a_lay.addWidget(table_from_rows(
                [{"check": en, "value": val} for en, _zh, val in bank]))
        figs = FigList()
        figs.set_figs([plot_pn_breakdown(ar, None)])
        self._a_lay.addWidget(figs)
        spurs = [{"spur": k, "value [dBc]": f"{float(v):.1f}"}
                 for k, v in ar.spurs_analytic.items()
                 if isinstance(v, (int, float))]
        if spurs:
            self._a_lay.addWidget(table_from_rows(spurs))
        for n in ar.notes:
            self._a_lay.addWidget(QLabel("note: " + n))

    def _go_analyze(self):
        self.run_async(self.compute_analyze, self.render_analyze,
                       self.btn_analyze)

    # ------------------------------------------------------------ simulate
    def compute_sim(self):
        pll = self._pll()
        kw = simulate_kwargs(pll, noise=self.cb_noise.isChecked(),
                             calibration=self.cb_cal.isChecked(),
                             seed=int(self.seed.value()),
                             f_start_offset=float(self.f_off.text()),
                             dtc_gain_init_error=float(self.dtc_err.text()))
        sim = pll.simulate(int(self.n_cycles.value()), **kw)
        ar = self._pll().analyze()
        return ar, sim

    def render_sim(self, result):
        ar, sim = result
        self.s_metrics.set_metrics([
            ("jitter", f"{sim.jitter_fs:.1f} fs" if sim.jitter_fs else "-"),
            ("lock", f"{sim.lock_time_s * 1e6:.1f} us"
             if sim.lock_time_s is not None else "-"),
            ("f_end", f"{sim.freq_out[-1] / 1e9:.6f} GHz"),
        ])
        self._clear(self._s_lay)
        for note in sim.notes:      # e.g. "still settling" — the jitter above
            lab = QLabel("! " + note)   # then includes a calibration transient
            lab.setWordWrap(True)
            self._s_lay.addWidget(lab)
        figs = [plot_pn_breakdown(ar, sim)]
        fig, (a1, a2) = plt.subplots(2, 1, figsize=(8, 5), sharex=True)
        a1.plot(sim.t * 1e6, (sim.freq_out - sim.f0) / 1e6, lw=0.7)
        a1.set_ylabel("f err [MHz]")
        a1.grid(alpha=0.3)
        a2.plot(sim.t * 1e6, sim.ctrl, lw=0.7, color="C1")
        a2.set_ylabel("vctrl / OTW")
        a2.set_xlabel("t [us]")
        a2.grid(alpha=0.3)
        figs.append(fig)
        for k, tr in sim.cal_traces.items():
            f2, ax = plt.subplots(figsize=(8, 2.2))
            ax.plot(sim.t * 1e6, tr, lw=0.8)
            ax.set_ylabel(k)
            ax.set_xlabel("t [us]")
            ax.grid(alpha=0.3)
            figs.append(f2)
        w = FigList()
        w.set_figs(figs)
        self._s_lay.addWidget(w)
        rows = [{"offset": f"{f / 1e3:.1f} kHz",
                 "spur [dBc]": f"{v:.1f}" if np.isfinite(v)
                 else "below noise"} for f, v in sim.spurs_fft.items()]
        if rows:
            self._s_lay.addWidget(table_from_rows(rows))

    def _go_sim(self):
        self.run_async(self.compute_sim, self.render_sim, self.btn_sim)
