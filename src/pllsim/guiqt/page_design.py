"""Design pages: loop synthesis and the architecture selector."""
from __future__ import annotations

import matplotlib.pyplot as plt
import numpy as np
from PySide6.QtWidgets import (QCheckBox, QFormLayout, QHBoxLayout, QLabel,
                               QPushButton, QTabWidget, QVBoxLayout, QWidget)

from .. import presets
from ..selector import Requirement, select
from ..synth import (cppll_kdet, design_adpll_dlf, design_cp_filter,
                     design_spll_filter, design_sspll_filter, sweep_bandwidth)
from .widgets import (FigList, Page, float_edit, in_scroll, table_from_rows)


def _filt_rows(filt):
    return [{"component": c, "value": f"{getattr(filt, c):.4g}"}
            for c in ("c1", "r2", "c2", "r3", "c3")]


class SynthesisPage(Page):
    title = "Loop synthesis"

    def __init__(self):
        super().__init__()
        lay = QVBoxLayout(self)
        note = QLabel("ILCM / MDLL are absent by design: they have no loop "
                      "filter — bandwidth comes from per-cycle edge "
                      "realignment, and the only tunable loop is the "
                      "frequency-tracking gain.")
        note.setWordWrap(True)
        lay.addWidget(note)
        tabs = QTabWidget()
        lay.addWidget(tabs)

        # ---- CP filter
        cp = QWidget()
        f = QFormLayout(cp)
        self.cp_icp = float_edit("1.5e-3")
        self.cp_n = float_edit("250")
        self.cp_kvco = float_edit("60e6")
        self.cp_ugb = float_edit("1e6")
        self.cp_pm = float_edit("58")
        self.cp_fref = float_edit("19.2e6")
        for lab, w in [("Icp [A]", self.cp_icp), ("N", self.cp_n),
                       ("Kvco [Hz/V]", self.cp_kvco), ("UGB [Hz]", self.cp_ugb),
                       ("PM [deg]", self.cp_pm), ("fref [Hz]", self.cp_fref)]:
            f.addRow(lab, w)
        self.cp_btn = QPushButton("Synthesize")
        f.addRow(self.cp_btn)
        self.cp_out = QVBoxLayout()
        f.addRow(self.cp_out)
        self.cp_btn.clicked.connect(self._go_cp)
        tabs.addTab(cp, "CP filter")

        # ---- SSPLL filter
        ss = QWidget()
        f2 = QFormLayout(ss)
        self.ss_amp = float_edit("0.4")
        self.ss_gm = float_edit("1e-3")
        self.ss_pw = float_edit("150e-12")
        self.ss_kvco = float_edit("60e6")
        self.ss_ugb = float_edit("1e6")
        self.ss_pm = float_edit("60")
        self.ss_fref = float_edit("19.2e6")
        for lab, w in [("amp [V]", self.ss_amp), ("gm [S]", self.ss_gm),
                       ("pulse [s]", self.ss_pw), ("Kvco [Hz/V]", self.ss_kvco),
                       ("UGB [Hz]", self.ss_ugb), ("PM [deg]", self.ss_pm),
                       ("fref [Hz]", self.ss_fref)]:
            f2.addRow(lab, w)
        self.ss_btn = QPushButton("Synthesize (exact discrete loop)")
        f2.addRow(self.ss_btn)
        self.ss_out = QVBoxLayout()
        f2.addRow(self.ss_out)
        self.ss_btn.clicked.connect(self._go_ss)
        tabs.addTab(ss, "SSPLL filter")

        # ---- SPLL filter: the SSPLL loop with the detector gain referred
        # through the divider, so N is an input rather than folded into k_q
        sp = QWidget()
        f2b = QFormLayout(sp)
        self.sp_amp = float_edit("0.8")
        self.sp_gm = float_edit("10e-3")
        self.sp_pw = float_edit("1e-9")
        self.sp_n = float_edit("80")
        self.sp_kvco = float_edit("60e6")
        self.sp_ugb = float_edit("3e5")
        self.sp_pm = float_edit("60")
        self.sp_fref = float_edit("100e6")
        for lab, w in [("amp [V]", self.sp_amp), ("gm [S]", self.sp_gm),
                       ("pulse [s]", self.sp_pw), ("N (fout/fref)", self.sp_n),
                       ("Kvco [Hz/V]", self.sp_kvco),
                       ("UGB [Hz]", self.sp_ugb), ("PM [deg]", self.sp_pm),
                       ("fref [Hz]", self.sp_fref)]:
            f2b.addRow(lab, w)
        self.sp_btn = QPushButton("Synthesize (exact discrete loop)")
        f2b.addRow(self.sp_btn)
        self.sp_out = QVBoxLayout()
        f2b.addRow(self.sp_out)
        self.sp_btn.clicked.connect(self._go_sp)
        tabs.addTab(sp, "SPLL filter")

        # ---- ADPLL DLF
        dl = QWidget()
        f3 = QFormLayout(dl)
        self.dl_fref = float_edit("100e6")
        self.dl_ugb = float_edit("1e6")
        self.dl_pm = float_edit("55")
        for lab, w in [("fref [Hz]", self.dl_fref), ("UGB [Hz]", self.dl_ugb),
                       ("PM [deg]", self.dl_pm)]:
            f3.addRow(lab, w)
        self.dl_btn = QPushButton("Synthesize")
        f3.addRow(self.dl_btn)
        self.dl_out = QLabel("")
        f3.addRow(self.dl_out)
        self.dl_btn.clicked.connect(self._go_dl)
        tabs.addTab(dl, "ADPLL DLF")

        # ---- bandwidth sweep
        sw = QWidget()
        f4 = QFormLayout(sw)
        self.sw_lo = float_edit("2e5")
        self.sw_hi = float_edit("3e6")
        self.sw_n = float_edit("8")
        for lab, w in [("UGB from [Hz]", self.sw_lo),
                       ("UGB to [Hz]", self.sw_hi), ("points", self.sw_n)]:
            f4.addRow(lab, w)
        self.sw_btn = QPushButton("Sweep sspll_19p2m_4p8g")
        f4.addRow(self.sw_btn)
        self.sw_figs = FigList()
        f4.addRow(self.sw_figs)
        self.sw_btn.clicked.connect(self._go_sw)
        tabs.addTab(in_scroll(sw), "Bandwidth sweep")

    @staticmethod
    def _set(layout, widget):
        while layout.count():
            w = layout.takeAt(0).widget()
            if w is not None:
                w.deleteLater()
        layout.addWidget(widget)

    def _go_cp(self):
        def fn():
            return design_cp_filter(
                cppll_kdet(float(self.cp_icp.text()),
                           float(self.cp_n.text())),
                float(self.cp_kvco.text()), float(self.cp_ugb.text()),
                float(self.cp_pm.text()), float(self.cp_fref.text()))
        self.run_async(fn, lambda filt: self._set(
            self.cp_out, table_from_rows(_filt_rows(filt))), self.cp_btn)

    def _go_ss(self):
        def fn():
            return design_sspll_filter(
                float(self.ss_amp.text()) * float(self.ss_gm.text())
                * float(self.ss_pw.text()),
                float(self.ss_kvco.text()), float(self.ss_ugb.text()),
                float(self.ss_pm.text()), float(self.ss_fref.text()))
        self.run_async(fn, lambda filt: self._set(
            self.ss_out, table_from_rows(_filt_rows(filt))), self.ss_btn)

    def _go_sp(self):
        def fn():
            return design_spll_filter(
                float(self.sp_amp.text()), float(self.sp_gm.text()),
                float(self.sp_pw.text()), float(self.sp_n.text()),
                float(self.sp_kvco.text()), float(self.sp_ugb.text()),
                float(self.sp_pm.text()), float(self.sp_fref.text()))
        self.run_async(fn, lambda filt: self._set(
            self.sp_out, table_from_rows(_filt_rows(filt))), self.sp_btn)

    def _go_dl(self):
        def fn():
            return design_adpll_dlf(float(self.dl_fref.text()),
                                    float(self.dl_ugb.text()),
                                    float(self.dl_pm.text()))
        self.run_async(fn, lambda ar: self.dl_out.setText(
            f"alpha = {ar[0]:.6g}    rho = {ar[1]:.6g}"), self.dl_btn)

    def _go_sw(self):
        def fn():
            ugbs = np.geomspace(float(self.sw_lo.text()),
                                float(self.sw_hi.text()),
                                int(float(self.sw_n.text())))

            def mk(f_ugb):
                pll = presets.ALL_PRESETS["sspll_19p2m_4p8g"]()
                c = pll.cfg
                s = c.sampler
                c.filt = design_sspll_filter(
                    s.amp_v * s.gm * s.pulse_width, c.osc.gain, f_ugb,
                    60.0, c.fref)
                return pll
            return sweep_bandwidth(mk, ugbs)

        def done(res):
            fig, ax = plt.subplots(figsize=(7, 4))
            ax.semilogx(res["f_ugb"], res["jitter_fs"], "o-")
            ax.set_xlabel("UGB [Hz]")
            ax.set_ylabel("jitter [fs]")
            ax.grid(alpha=0.3, which="both")
            self.sw_figs.set_figs([fig])
        self.run_async(fn, done, self.sw_btn)


class SelectorPage(Page):
    title = "Architecture selector"

    def __init__(self):
        super().__init__()
        lay = QVBoxLayout(self)
        row = QHBoxLayout()
        self.fref = float_edit("100e6")
        self.fout = float_edit("8e9")
        self.jmax = float_edit("120")
        self.band = float_edit("10e3, 40e6", width=140)
        self.mod = QCheckBox("needs two-point TX")
        for lab, w in [("fref [Hz]", self.fref), ("fout [Hz]", self.fout),
                       ("jitter target [fs]", self.jmax),
                       ("int band [Hz]", self.band)]:
            row.addWidget(QLabel(lab))
            row.addWidget(w)
        row.addWidget(self.mod)
        self.btn = QPushButton("Select")
        row.addWidget(self.btn)
        row.addStretch(1)
        lay.addLayout(row)
        self.verdict = QLabel("")
        lay.addWidget(self.verdict)
        self._body = QVBoxLayout()
        lay.addLayout(self._body, 1)
        self.btn.clicked.connect(self._go)

    def _go(self):
        def fn():
            b = tuple(float(x) for x in
                      self.band.text().replace(",", " ").split())
            return select(Requirement(
                fref=float(self.fref.text()), fout=float(self.fout.text()),
                jitter_fs_max=float(self.jmax.text()), int_band=b,
                modulation=self.mod.isChecked()))

        def done(rep):
            while self._body.count():
                w = self._body.takeAt(0).widget()
                if w is not None:
                    w.deleteLater()
            rows = []
            for c in sorted(rep.candidates, key=lambda c: c.key):
                rows.append({
                    "arch": c.arch,
                    "jitter [fs]": f"{c.jitter_fs:.0f}"
                    if np.isfinite(c.jitter_fs) else "-",
                    "verdict": ("PASS" if c.feasible
                                and c.jitter_fs <= rep.req.jitter_fs_max
                                else ("fail" if c.feasible else "excluded")),
                    "UGB [kHz]": f"{c.f_ugb / 1e3:.0f}"
                    if np.isfinite(c.f_ugb) else "-",
                    "PM [deg]": f"{c.pm_deg:.0f}"
                    if np.isfinite(c.pm_deg) else "-",
                    "notes": "; ".join(c.notes),
                })
            self._body.addWidget(table_from_rows(rows))
            b = rep.best
            self.verdict.setText(
                f"recommendation: <b>{b.arch}</b> ({b.jitter_fs:.0f} fs, "
                f"{rep.req.jitter_fs_max - b.jitter_fs:.0f} fs margin)"
                if b is not None else
                "no architecture meets the target — relax it, improve the "
                "oscillator class, or raise fref")
        self.run_async(fn, done, self.btn)
