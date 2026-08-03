"""Main window: sidebar navigation over all feature pages."""
from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMainWindow,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

ICON_PATH = Path(__file__).parent / "pllsim_icon.png"

from .i18n import lang, on_language_change, set_lang
from .page_analysis import BenchmarksPage, FitPage, SpursPage
from .page_design import SelectorPage, SynthesisPage
from .page_dynamics import DriftPage, HopSettlingPage, ModulationPage
from .page_tools import ExportPage, MonteCarloPage
from .page_workbench import WorkbenchPage

PAGES = [WorkbenchPage, SynthesisPage, SelectorPage, SpursPage, FitPage,
         ModulationPage, HopSettlingPage, DriftPage, MonteCarloPage,
         ExportPage, BenchmarksPage]


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("pllsim — system-level PLL workbench")
        if ICON_PATH.exists():
            self.setWindowIcon(QIcon(str(ICON_PATH)))
        self.resize(1280, 840)
        central = QWidget()
        lay = QHBoxLayout(central)
        lay.setContentsMargins(0, 0, 0, 0)

        side = QWidget()
        side_lay = QVBoxLayout(side)
        side_lay.setContentsMargins(0, 0, 0, 0)
        side.setMaximumWidth(210)
        self.nav = QListWidget()
        self.stack = QStackedWidget()
        self.pages = []
        for cls in PAGES:
            page = cls()
            self.pages.append(page)
            self.stack.addWidget(page)
        self._fill_nav()
        self.nav.currentRowChanged.connect(self.stack.setCurrentIndex)
        self.nav.setCurrentRow(0)
        side_lay.addWidget(self.nav, 1)

        row = QHBoxLayout()
        row.addWidget(QLabel("语言 / Language"))
        self.lang_box = QComboBox()
        self.lang_box.addItems(["English", "中文"])
        self.lang_box.setCurrentIndex(1 if lang() == "zh" else 0)
        self.lang_box.currentIndexChanged.connect(
            lambda i: set_lang("zh" if i == 1 else "en"))
        row.addWidget(self.lang_box, 1)
        side_lay.addLayout(row)
        lay.addWidget(side)
        lay.addWidget(self.stack, 1)
        self.setCentralWidget(central)
        # page names live in the nav list, not on a widget the registry can
        # reach, so they are refreshed through the listener hook instead
        on_language_change(lambda _code: self._fill_nav())

    def _fill_nav(self):
        row = max(self.nav.currentRow(), 0)
        self.nav.blockSignals(True)
        self.nav.clear()
        for cls in PAGES:
            self.nav.addItem(cls.nav_title())
        self.nav.setCurrentRow(row)
        self.nav.blockSignals(False)

    def open_in_workbench(self, preset: str) -> None:
        """Hand a preset to the workbench and show it.

        The documented selector -> workbench flow: picking a candidate should
        land you in the editor with that architecture loaded, rather than
        leaving you to find the name in a dropdown yourself.
        """
        wb = self.pages[PAGES.index(WorkbenchPage)]
        wb.load_preset(preset)
        self.nav.setCurrentRow(PAGES.index(WorkbenchPage))


def main():
    import os
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("pllsim")
    win = MainWindow()
    win.show()
    if os.environ.get("PLLSIM_SMOKE"):
        # CI packaging smoke: open, render, exit clean after a few seconds
        from PySide6.QtCore import QTimer
        QTimer.singleShot(4000, app.quit)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
