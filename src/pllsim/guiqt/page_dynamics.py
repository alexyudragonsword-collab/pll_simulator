"""Dynamics pages: two-point modulation, hop settling, drift tracking."""
from __future__ import annotations

import matplotlib.pyplot as plt
import numpy as np
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from .. import presets
from ..core.dtcspurs import dtc_spur_table
from ..guiutil import frac_presets
from ..modulation import evm, gmsk_trajectory, prbs, two_point_presets
from ..settling import fll_stability, hop_settling, hop_statistics
from .i18n import tr
from .widgets import FigList, MetricRow, Page, float_edit

FRAC_PRESETS = frac_presets()


class ModulationPage(Page):
    title = "Two-point modulation"
    title_zh = "两点调制"

    def __init__(self):
        super().__init__()
        lay = QVBoxLayout(self)
        row = QHBoxLayout()
        self.arch = QComboBox()
        self.arch.addItems(two_point_presets())
        self.rb = float_edit("2.5e6")
        self.dp = float_edit("0.0")
        self.n_cyc = float_edit("140000")
        for lab, w in [("architecture", self.arch), ("bit rate [b/s]", self.rb),
                       ("direct-path gain error", self.dp),
                       ("cycles", self.n_cyc)]:
            row.addWidget(QLabel(lab))
            row.addWidget(w)
        self.btn = tr(QPushButton(), "运行 GMSK", "Run GMSK")
        row.addWidget(self.btn)
        row.addStretch(1)
        lay.addLayout(row)
        self.note = tr(QLabel(),
                       "引擎网格：匹配 EVM 应在 >= 8 采样/符号下引用（低于此值，"
                       "按参考周期的离散化会给比较设下地板）",
                       "engine grid: quote matched EVM at >= 8 "
                       "samples/symbol (per-ref-cycle discretization "
                       "floors the comparison below that)")
        lay.addWidget(self.note)
        self.metrics = MetricRow()
        lay.addWidget(self.metrics)
        self.figs = FigList()
        lay.addWidget(self.figs, 1)
        self.btn.clicked.connect(self._go)

    def compute(self):
        """The worker body, named so a test can call exactly what runs.

        A closure inside _go is unreachable from a test without driving the
        thread pool, which is why these pages sat at half the coverage of the
        workbench -- and "the button raises the moment it is pressed" is the
        failure this GUI has actually had.
        """
        nm = self.arch.currentText()
        fref = presets.ALL_PRESETS[nm]().cfg.fref   # not a copy
        rb = float(self.rb.text())
        dp = float(self.dp.text())
        n_cyc = int(float(self.n_cyc.text()))
        settle = max(50_000, n_cyc // 3)
        bits = prbs(max(64, int((n_cyc - settle) * rb / fref) - 20), seed=7)
        fdev, _ = gmsk_trajectory(bits, fref, rb)
        mod = np.zeros(n_cyc)
        mod[settle:settle + min(fdev.size, n_cyc - settle)] = \
            fdev[: n_cyc - settle]
        ideal = 2 * np.pi * np.cumsum(mod) / fref
        pll = presets.ALL_PRESETS[nm]()
        sim = pll.simulate(n_cyc, seed=2, mod_freq=mod, mod_dp_gain=1.0 + dp)
        e = evm(sim.phase_err_out[settle + 4000:], ideal[settle + 4000:])
        return e, sim, mod, ideal, settle, fref, rb

    def render(self, res):
        e, sim, mod, ideal, settle, fref, rb = res
        self.metrics.set_metrics([
            ("EVM", f"{e['evm_pct']:.2f} %"),
            ("EVM", f"{e['evm_db']:.1f} dB"),
            ("phase err", f"{e['phase_err_rms_deg']:.2f} deg rms")])
        sps = fref / rb
        fig, (a1, a2) = plt.subplots(1, 2, figsize=(10, 3.8))
        sl = slice(settle + 4000, settle + 4000 + int(40 * sps))
        a1.plot(sim.t[sl] * 1e6, mod[sl] / 1e6)
        a1.set_xlabel("t [us]")
        a1.set_ylabel("freq dev [MHz]")
        a1.grid(alpha=0.3)
        d = sim.phase_err_out[settle + 4000:] - ideal[settle + 4000:]
        x = np.arange(d.size)
        d = d - np.polyval(np.polyfit(x, d, 1), x)
        a2.plot(sim.t[settle + 4000:] * 1e3, np.degrees(d), lw=0.5)
        a2.set_xlabel("t [ms]")
        a2.set_ylabel("phase error [deg]")
        a2.grid(alpha=0.3)
        self.figs.set_figs([fig])

    def _go(self):
        self.run_async(self.compute, self.render, self.btn)


class HopSettlingPage(Page):
    title = "Hop settling"
    title_zh = "跳频建立"

    def __init__(self):
        super().__init__()
        lay = QVBoxLayout(self)
        row = QHBoxLayout()
        self.preset = QComboBox()
        self.preset.addItems(list(presets.ALL_PRESETS))
        self.preset.currentTextChanged.connect(self._update_fll)
        self.hop = float_edit("-100e6")
        self.n_cyc = float_edit("200000")
        self.seed = float_edit("1", width=60)
        self.n_seeds = float_edit("12", width=60)
        for lab, w in [("preset", self.preset), ("hop [Hz]", self.hop),
                       ("cycles", self.n_cyc), ("seed", self.seed)]:
            row.addWidget(QLabel(lab))
            row.addWidget(w)
        self.btn = tr(QPushButton(), "运行跳频", "Run hop")
        self.btn_stats = tr(QPushButton(), "多种子统计", "Seed statistics")
        row.addWidget(self.btn)
        row.addWidget(tr(QLabel(), "种子数", "seeds"))
        row.addWidget(self.n_seeds)
        row.addWidget(self.btn_stats)
        row.addStretch(1)
        lay.addLayout(row)
        self.fll_label = QLabel("")
        lay.addWidget(self.fll_label)
        self.metrics = MetricRow()
        lay.addWidget(self.metrics)
        self.figs = FigList()
        lay.addWidget(self.figs, 1)
        self.btn.clicked.connect(self._go)
        self.btn_stats.clicked.connect(self._go_stats)
        self._update_fll(self.preset.currentText())

    def _update_fll(self, name: str):
        pll = presets.ALL_PRESETS[name]()
        if hasattr(pll.cfg, "fll_i"):
            s = fll_stability(pll)
            ok = s["margin"] > 1.0
            self.fll_label.setText(
                f"FLL: slew {s['slew_per_window_hz'] / 1e3:.0f} kHz/window, "
                f"i_fll_max {s['i_fll_max_a'] * 1e6:.2f} uA, margin "
                f"{s['margin']:.2f}x"
                + ("" if ok else "  — OVER the bound: limit cycle, never "
                                 "hands off!"))
        else:
            self.fll_label.setText("no FLL in this architecture")

    def compute(self):
        """The worker body, named so a test can call exactly what runs."""
        nm = self.preset.currentText()
        pll = presets.ALL_PRESETS[nm]()
        return hop_settling(pll, pll.cfg.fout + float(self.hop.text()),
                            n_cycles=int(float(self.n_cyc.text())),
                            seed=int(float(self.seed.text())))

    def render(self, r):
        self.metrics.set_metrics([
            ("t_freq", f"{r.t_freq_s * 1e6:.1f} us"
             if np.isfinite(r.t_freq_s) else "not settled"),
            ("t_phase", f"{r.t_phase_s * 1e6:.1f} us"
             if np.isfinite(r.t_phase_s) else "not settled"),
            ("FLL segment", f"{r.fll_engaged_s * 1e6:.1f} us"
             if r.fll_engaged_s else "-"),
            ("jitter", f"{r.jitter_fs:.0f} fs" if r.jitter_fs else "-")])
        sim = r.sim
        fig, ax = plt.subplots(figsize=(9, 4))
        ax.plot(sim.t * 1e6, (sim.freq_out - r.f_to) / 1e6, lw=0.7)
        if "fll_engaged" in sim.cal_traces:
            eng = sim.cal_traces["fll_engaged"] > 0.5
            ax.fill_between(sim.t * 1e6, *ax.get_ylim(), where=eng,
                            alpha=0.15, color="C1", label="FLL engaged")
        if np.isfinite(r.t_phase_s):
            ax.axvline(r.t_phase_s * 1e6, color="r", ls="--", lw=1,
                       label=f"settled {r.t_phase_s * 1e6:.0f} us")
        ax.set_xlabel("t [us]")
        ax.set_ylabel("freq error [MHz]")
        ax.legend(fontsize=8)
        ax.grid(alpha=0.3)
        self.figs.set_figs([fig])

    def _go(self):
        self.run_async(self.compute, self.render, self.btn, self.btn_stats)

    def compute_stats(self):
        nm = self.preset.currentText()
        return hop_statistics(
            lambda: presets.ALL_PRESETS[nm](),
            presets.ALL_PRESETS[nm]().cfg.fout + float(self.hop.text()),
            seeds=range(int(float(self.n_seeds.text()))),
            n_cycles=int(float(self.n_cyc.text())))

    def render_stats(self, stats):
        self.metrics.set_metrics([
            ("p50", f"{stats['p50_s'] * 1e6:.0f} us"),
            ("p95", f"{stats['p95_s'] * 1e6:.0f} us"),
            ("worst", f"{stats['worst_s'] * 1e6:.0f} us"),
            ("failed", f"{stats['fail_frac'] * 100:.0f} %")])
        tp = stats["t_phase_s"]
        fig, ax = plt.subplots(figsize=(7, 3.5))
        ax.hist(tp[np.isfinite(tp)] * 1e6, bins=12, alpha=0.8)
        ax.set_xlabel("t_phase [us]")
        ax.set_ylabel("hops")
        ax.set_title("spec the p95, not the mean")
        ax.grid(alpha=0.3)
        self.figs.set_figs([fig])

    def _go_stats(self):
        self.run_async(self.compute_stats, self.render_stats,
                       self.btn, self.btn_stats)


class DriftPage(Page):
    title = "Drift tracking"
    title_zh = "温漂跟踪"

    def __init__(self):
        super().__init__()
        lay = QVBoxLayout(self)
        row = QHBoxLayout()
        self.preset = QComboBox()
        self.preset.addItems(FRAC_PRESETS)
        self.eps = float_edit("0.03")
        self.n_ramp = float_edit("60000")
        self.start = float_edit("80000")
        for lab, w in [("preset", self.preset),
                       ("total gain drift", self.eps),
                       ("ramp cycles", self.n_ramp),
                       ("ramp start", self.start)]:
            row.addWidget(QLabel(lab))
            row.addWidget(w)
        self.btn = tr(QPushButton(), "运行温度斜坡", "Run ramp")
        row.addWidget(self.btn)
        row.addStretch(1)
        lay.addLayout(row)
        self.metrics = MetricRow()
        lay.addWidget(self.metrics)
        self.figs = FigList()
        lay.addWidget(self.figs, 1)
        self.btn.clicked.connect(self._go)

    def compute(self):
        """The worker body, named so a test can call exactly what runs."""
        nm = self.preset.currentText()
        eps = float(self.eps.text())
        n_ramp = int(float(self.n_ramp.text()))
        start = int(float(self.start.text()))
        n = start + n_ramp
        pll = presets.ALL_PRESETS[nm]()
        pll.cfg.frac.dtc_cal.gear_shift_n = min(
            pll.cfg.frac.dtc_cal.gear_shift_n or 40_000, start // 2)
        drift = np.zeros(n)
        drift[start:] = eps * np.arange(n_ramp) / n_ramp
        sim = pll.simulate(n, seed=3, dtc_gain_drift=drift)
        g = sim.cal_traces["dtc_gain"]
        lag = np.abs(g * (1.0 + drift) - 1.0)
        c = pll.cfg
        kind = type(pll).__name__
        if kind == "SPLL":
            tof = lambda r: -r / c.fout - c.frac.dtc.range_s / 2.0
        elif kind == "SSPLL":
            tof = lambda r: (1.0 + r) / c.fout - c.frac.dtc.range_s / 2.0
        else:
            tof = lambda r: r / c.fout
        tab = dtc_spur_table(c.frac, tof, c.fref, c.fout,
                             gain_eps=float(lag[-1]))
        mu = c.frac.dtc_cal.mu_final or c.frac.dtc_cal.mu
        return sim, drift, lag, tab, mu, c.fref

    def render(self, res):
        sim, drift, lag, tab, mu, fref = res
        rate = float(self.eps.text()) / int(float(self.n_ramp.text()))
        self.metrics.set_metrics([
            ("rate/mu", f"{rate / mu:.2f}x"),
            ("peak lag", f"{lag[-1] * 100:.2f} %"),
            ("lag spur", f"{max(tab.values()):.1f} dBc" if tab else "-"),
            ("jitter", f"{sim.jitter_fs:.0f} fs"
             if sim.jitter_fs else "-")])
        fig, ax = plt.subplots(figsize=(9, 4))
        start = int(float(self.start.text()))
        t_ms = (np.arange(lag.size) - start) / fref * 1e3
        ax.plot(t_ms, lag * 100, lw=0.9, label="tracking lag")
        ax.plot(t_ms, drift * 100, "--", lw=0.9, label="true drift")
        ax.set_xlabel("time from ramp start [ms]")
        ax.set_ylabel("[%]")
        ax.legend()
        ax.grid(alpha=0.3)
        self.figs.set_figs([fig])

    def _go(self):
        self.run_async(self.compute, self.render, self.btn)
