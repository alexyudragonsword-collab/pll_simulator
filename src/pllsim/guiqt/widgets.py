"""Shared Qt building blocks: worker thread, config forms, figure list."""
from __future__ import annotations

import math

import matplotlib
import numpy as np

matplotlib.use("Agg")            # pyplot figures are re-parented onto Qt
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.backends.backend_qtagg import (
    FigureCanvasQTAgg,
    NavigationToolbar2QT,
)
from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..guiutil import GROUP_LABELS, enumerate_fields, fmt_value
from ..plotting import data_lines

# English half of the shared table, not a second copy: the web GUI and the
# Android form read the same guiutil.GROUP_LABELS, and a new sub-config used
# to need adding in two places before anyone noticed one was missing.
GROUP_TITLES = {k: en for k, (_zh, en) in GROUP_LABELS.items()}


class Worker(QThread):
    """Run a plain callable off the UI thread."""
    done = Signal(object)
    fail = Signal(str)

    def __init__(self, fn, parent=None):
        super().__init__(parent)
        self._fn = fn

    def run(self):
        try:
            self.done.emit(self._fn())
        except Exception as exc:            # surfaced in a message box
            self.fail.emit(f"{type(exc).__name__}: {exc}")


class Page(QWidget):
    """Base page: single-flight worker + busy handling + error dialog."""

    title = "page"
    title_zh: str | None = None

    def __init__(self):
        super().__init__()
        self._worker = None
        self._busy_buttons: list[QPushButton] = []

    @classmethod
    def nav_title(cls) -> str:
        """Name shown in the sidebar, in the current language."""
        from .i18n import lang
        if cls.title_zh and lang() == "zh":
            return cls.title_zh
        return cls.title

    def main_window(self):
        """The MainWindow this page sits in, or None when standalone.

        Pages are constructed directly by the tests, so nothing may assume a
        parent window exists.
        """
        w = self.window()
        return w if hasattr(w, "open_in_workbench") else None

    def run_async(self, fn, on_done, *buttons: QPushButton):
        if self._worker is not None and self._worker.isRunning():
            return
        self._busy_buttons = list(buttons)
        for b in self._busy_buttons:
            b.setEnabled(False)
        self._worker = Worker(fn, self)
        self._worker.done.connect(lambda r: self._finish(on_done, r))
        self._worker.fail.connect(self._error)
        self._worker.start()

    def _finish(self, on_done, result):
        for b in self._busy_buttons:
            b.setEnabled(True)
        on_done(result)

    def _error(self, msg: str):
        for b in self._busy_buttons:
            b.setEnabled(True)
        QMessageBox.warning(self, "pllsim", msg)


class ConfigForm(QWidget):
    """Auto-generated editor for a Config dataclass tree (via guiutil)."""

    def __init__(self, cfg):
        super().__init__()
        self._edits: dict[str, QLineEdit] = {}
        self._initial: dict[str, str] = {}
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        groups: dict[str, list] = {}
        for s in enumerate_fields(cfg):
            head = s.path.split(".")[0] if "." in s.path else ""
            groups.setdefault(head, []).append(s)
        for head, items in groups.items():
            box = QGroupBox(GROUP_TITLES.get(head, head))
            form = QFormLayout(box)
            for s in items:
                label = s.label_en or s.path
                if s.unit:
                    label += f" [{s.unit}]"
                edit = QLineEdit(fmt_value(s.value))
                edit.setToolTip(s.path)
                form.addRow(label, edit)
                self._edits[s.path] = edit
                self._initial[s.path] = fmt_value(s.value)
            lay.addWidget(box)
        lay.addStretch(1)

    def overrides(self) -> dict[str, str]:
        """Only the fields the user actually edited."""
        return {p: e.text() for p, e in self._edits.items()
                if e.text().strip() != self._initial[p]}


def _eng(v: float) -> str:
    """A number the way an RF engineer writes it, not the way repr does."""
    if v == 0 or not math.isfinite(v):
        return f"{v:g}"
    a = abs(v)
    for lim, div, suf in ((1e9, 1e9, "G"), (1e6, 1e6, "M"), (1e3, 1e3, "k"),
                          (1.0, 1.0, ""), (1e-3, 1e-3, "m"), (1e-6, 1e-6, "µ"),
                          (1e-9, 1e-9, "n")):
        if a >= lim:
            return f"{v / div:.4g}{suf}"
    return f"{v * 1e12:.4g}p"


class PlotCursor:
    """A readout cursor over one axes: snap to a sample, list every curve.

    Reading a phase-noise plot means asking "what is it at 1 MHz, and which
    source is responsible" -- which is two questions, and a crosshair that
    reports one (x, y) answers neither.  So the cursor snaps to the nearest
    sample of the nearest curve and then reports **every** curve at that
    abscissa, worst first.  That is the question a budget review starts from.

    A second click drops a reference cursor and the box switches to deltas.
    On a log-log pair it also states the slope in dB/dec, because "is this
    segment -20 or -30 dB/dec" is how you tell a flicker-dominated region
    from a thermal one, and by eye on a squeezed axis it is a coin toss.

    Curves are selected with ``plotting.data_lines`` -- the same predicate the
    remote surfaces use -- so the desktop and the phone never disagree about
    what counts as a trace.  The *values* are read straight off the artists
    here, at full precision: there is no transfer, so nothing is rounded and
    nothing is length-capped.
    """

    def __init__(self, canvas, ax):
        from ..plotting import data_lines
        self.canvas, self.ax = canvas, ax
        self.lines = data_lines(ax)
        self.ref: tuple[float, float] | None = None
        self._vline = ax.axvline(ax.get_xlim()[0], color="0.25", lw=0.8,
                                 ls="--", visible=False, animated=True)
        self._rline = ax.axvline(ax.get_xlim()[0], color="tab:red", lw=0.8,
                                 ls=":", visible=False, animated=True)
        self._dot, = ax.plot([], [], "o", ms=5, mfc="none", mec="0.15",
                             visible=False, animated=True)
        self._text = ax.text(
            0.99, 0.99, "", transform=ax.transAxes, ha="right", va="top",
            fontsize=7.5, family="monospace", visible=False, animated=True,
            bbox={"boxstyle": "round,pad=0.35", "fc": "#ffffe0",
                  "ec": "0.6", "alpha": 0.93})
        self._bg = None
        self._cids = [
            canvas.mpl_connect("motion_notify_event", self._on_move),
            canvas.mpl_connect("button_press_event", self._on_click),
            canvas.mpl_connect("axes_leave_event", self._on_leave),
            canvas.mpl_connect("draw_event", self._on_draw),
        ]

    # ---- the artists are animated, so they live outside the cached background
    def _on_draw(self, _ev=None):
        self._bg = self.canvas.copy_from_bbox(self.ax.bbox)

    def _blit(self):
        if self._bg is None:
            self._on_draw()
        self.canvas.restore_region(self._bg)
        for art in (self._vline, self._rline, self._dot, self._text):
            self.ax.draw_artist(art)
        self.canvas.blit(self.ax.bbox)

    def _nearest(self, xd: float, yd: float):
        """Nearest sample, measured in *display* pixels.

        Not in data units: on a log-x / linear-y plot those are not
        commensurable, and a "nearest point" that mixes decades with dB picks
        whichever axis happens to have the larger numbers.
        """
        px, py = self.ax.transData.transform((xd, yd))
        best = None
        for ln in self.lines:
            x = np.asarray(ln.get_xdata(), dtype=float)
            y = np.asarray(ln.get_ydata(), dtype=float)
            if not x.size:
                continue
            pts = self.ax.transData.transform(np.column_stack([x, y]))
            d2 = (pts[:, 0] - px) ** 2 + (pts[:, 1] - py) ** 2
            i = int(np.nanargmin(d2))
            if best is None or d2[i] < best[0]:
                best = (d2[i], ln, float(x[i]), float(y[i]))
        return best

    def _values_at(self, xd: float) -> list[tuple[str, float]]:
        """Every curve at this abscissa, worst first."""
        out = []
        for ln in self.lines:
            x = np.asarray(ln.get_xdata(), dtype=float)
            y = np.asarray(ln.get_ydata(), dtype=float)
            if x.size < 2 or not (min(x[0], x[-1]) <= xd <= max(x[0], x[-1])):
                continue
            i = int(np.argmin(np.abs(x - xd)))
            label = ln.get_label()
            if label.startswith("_"):
                label = self.ax.get_ylabel() or "trace"
            out.append((label, float(y[i])))
        return sorted(out, key=lambda kv: -kv[1])

    def _on_move(self, ev):
        # the toolbar owns the drag while pan or zoom is armed; a cursor that
        # also tracked it would fight the rubber band
        tb = getattr(self.canvas, "toolbar", None)
        if ev.inaxes is not self.ax or (tb is not None and tb.mode):
            return
        hit = self._nearest(ev.xdata, ev.ydata)
        if hit is None:
            return
        _d2, _ln, xs, ys = hit
        self._vline.set_xdata([xs, xs])
        self._dot.set_data([xs], [ys])
        self._text.set_text(self._readout(xs))
        # keep the box away from the cursor: seven rows in the top-right
        # corner cover exactly the part of the curve someone reading 10 MHz
        # is looking at
        frac = self.ax.transAxes.inverted().transform(
            self.ax.transData.transform((xs, ys)))[0]
        right = frac < 0.5
        self._text.set_position((0.99 if right else 0.01, 0.99))
        self._text.set_ha("right" if right else "left")
        for art in (self._vline, self._dot, self._text):
            art.set_visible(True)
        self._rline.set_visible(self.ref is not None)
        self._blit()

    def _readout(self, xs: float) -> str:
        xlab = self.ax.get_xlabel() or "x"
        rows = self._values_at(xs)
        head = f"{xlab.split('[')[0].strip()} = {_eng(xs)}"
        if self.ref is None:
            body = "\n".join(f"  {k:<22s}{v:>9.2f}" for k, v in rows)
            return f"{head}\n{body}\n  [click to set a Δ reference]"
        rx, ry = self.ref
        dx = xs - rx
        cur = dict(rows)
        best = max(rows, key=lambda kv: kv[1])[0] if rows else ""
        dy = cur.get(best, float("nan")) - ry
        out = [head, f"ref = {_eng(rx)}", f"Δ   = {_eng(dx)}",
               f"Δ{best} = {dy:+.2f} dB"]
        if self.ax.get_xscale() == "log" and rx > 0 and xs > 0 and xs != rx:
            dec = math.log10(xs / rx)
            out.append(f"slope = {dy / dec:+.1f} dB/dec")
        return "\n".join(out)

    def _on_click(self, ev):
        tb = getattr(self.canvas, "toolbar", None)
        if ev.inaxes is not self.ax or (tb is not None and tb.mode):
            return
        if ev.button != 1:
            return
        if self.ref is not None:
            self.ref = None
            self._rline.set_visible(False)
            self._blit()
            return
        hit = self._nearest(ev.xdata, ev.ydata)
        if hit is None:
            return
        _d2, _ln, xs, _ys = hit
        rows = self._values_at(xs)
        if not rows:
            return
        self.ref = (xs, max(rows, key=lambda kv: kv[1])[1])
        self._rline.set_xdata([xs, xs])
        self._rline.set_visible(True)
        self._blit()

    def _on_leave(self, _ev):
        for art in (self._vline, self._dot, self._text):
            art.set_visible(False)
        self._blit()


class FigList(QWidget):
    """Scrollless vertical stack of matplotlib canvases (host in a scroll).

    Every figure carries its own navigation toolbar.  A phase-noise plot
    spans eight decades and a settling transient hides its ringing in the
    last 2% of the x axis; without zoom the reader is limited to whatever
    limits the plotting code chose, which is the wrong place to decide what
    someone wants to look at.  Per figure rather than one shared toolbar
    because the toolbar acts on one canvas, and these stacks routinely hold
    two unrelated plots (the PN breakdown and its IPN pie, say).
    """

    def __init__(self):
        super().__init__()
        self._lay = QVBoxLayout(self)
        self._lay.setContentsMargins(0, 0, 0, 0)

    def set_figs(self, figs):
        while self._lay.count():
            item = self._lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        for fig in figs:
            holder = QWidget()
            box = QVBoxLayout(holder)
            box.setContentsMargins(0, 0, 0, 0)
            box.setSpacing(0)
            # close *before* wrapping: plt.close() destroys the pyplot manager
            # and with it re-points fig.canvas at a plain FigureCanvasBase, so
            # closing afterwards leaves the figure disowned by the very widget
            # showing it.  Nothing noticed while only paintEvent drew -- the Qt
            # canvas draws itself -- but ax.draw_artist() goes through
            # fig.canvas.get_renderer(), which that base class does not have.
            plt.close(fig)               # drop the pyplot registry reference
            canvas = FigureCanvasQTAgg(fig)
            h = int(fig.get_size_inches()[1] * fig.dpi)
            canvas.setMinimumHeight(max(h, 220))
            canvas.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            # the toolbar must outlive this scope and be found again by the
            # tests, so it is parented into the holder rather than floated
            bar = NavigationToolbar2QT(canvas, holder)
            bar.setIconSize(bar.iconSize() * 0.75)
            box.addWidget(bar)
            box.addWidget(canvas)
            holder.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            self._lay.addWidget(holder)
            # a readout cursor per data axes.  Held on the canvas so it lives
            # exactly as long as the widget does: a cursor that is only
            # referenced by its own mpl callbacks is collected the moment this
            # loop moves on, and then silently never fires again.
            canvas._pllsim_cursors = [
                PlotCursor(canvas, ax) for ax in fig.axes if data_lines(ax)]

    def canvases(self) -> list[FigureCanvasQTAgg]:
        """The canvases currently shown, in order -- the seam the tests use."""
        return self.findChildren(FigureCanvasQTAgg)

    def cursors(self) -> list[PlotCursor]:
        out: list[PlotCursor] = []
        for c in self.canvases():
            out.extend(getattr(c, "_pllsim_cursors", []))
        return out

    def toolbars(self) -> list[NavigationToolbar2QT]:
        return self.findChildren(NavigationToolbar2QT)


def in_scroll(widget: QWidget) -> QScrollArea:
    sc = QScrollArea()
    sc.setWidgetResizable(True)
    sc.setWidget(widget)
    return sc


def table_from_rows(rows: list[dict]) -> QTableWidget:
    tbl = QTableWidget()
    if not rows:
        return tbl
    cols = list(rows[0].keys())
    tbl.setColumnCount(len(cols))
    tbl.setRowCount(len(rows))
    tbl.setHorizontalHeaderLabels(cols)
    for i, r in enumerate(rows):
        for j, c in enumerate(cols):
            tbl.setItem(i, j, QTableWidgetItem(str(r.get(c, ""))))
    tbl.resizeColumnsToContents()
    tbl.setMinimumHeight(min(60 + 26 * len(rows), 420))
    return tbl


class MetricRow(QWidget):
    def __init__(self):
        super().__init__()
        self._lay = QHBoxLayout(self)
        self._lay.setContentsMargins(0, 4, 0, 4)

    def set_metrics(self, items: list[tuple[str, str]]):
        while self._lay.count():
            w = self._lay.takeAt(0).widget()
            if w is not None:
                w.deleteLater()
        for name, val in items:
            lab = QLabel(f"<b>{name}</b><br><span style='font-size:16px'>"
                         f"{val}</span>")
            self._lay.addWidget(lab)
        self._lay.addStretch(1)


def float_edit(text: str, width: int = 110) -> QLineEdit:
    e = QLineEdit(text)
    e.setMaximumWidth(width)
    return e
