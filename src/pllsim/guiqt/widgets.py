"""Shared Qt building blocks: worker thread, config forms, figure list."""
from __future__ import annotations

import matplotlib

matplotlib.use("Agg")            # pyplot figures are re-parented onto Qt
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
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

from ..guiutil import enumerate_fields, fmt_value

GROUP_TITLES = {
    "": "Loop / top level",
    "osc": "Oscillator",
    "cp": "Charge pump",
    "sampler": "Sampler",
    "filt": "Loop filter",
    "tdc": "TDC",
    "dlf": "Digital loop filter",
    "frac": "Fractional-N / DTC / calibration",
}


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

    def __init__(self):
        super().__init__()
        self._worker = None
        self._busy_buttons: list[QPushButton] = []

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


class FigList(QWidget):
    """Scrollless vertical stack of matplotlib canvases (host in a scroll)."""

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
            canvas = FigureCanvasQTAgg(fig)
            h = int(fig.get_size_inches()[1] * fig.dpi)
            canvas.setMinimumHeight(max(h, 220))
            canvas.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            self._lay.addWidget(canvas)
            plt.close(fig)               # drop the pyplot registry reference


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
