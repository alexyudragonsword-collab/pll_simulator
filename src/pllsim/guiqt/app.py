"""Main window: sidebar navigation over all feature pages."""
from __future__ import annotations

import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QApplication, QHBoxLayout, QListWidget,
                               QMainWindow, QStackedWidget, QWidget)

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
        self.resize(1280, 840)
        central = QWidget()
        lay = QHBoxLayout(central)
        lay.setContentsMargins(0, 0, 0, 0)
        self.nav = QListWidget()
        self.nav.setMaximumWidth(210)
        self.stack = QStackedWidget()
        self.pages = []
        for cls in PAGES:
            page = cls()
            self.pages.append(page)
            self.nav.addItem(cls.title)
            self.stack.addWidget(page)
        self.nav.currentRowChanged.connect(self.stack.setCurrentIndex)
        self.nav.setCurrentRow(0)
        lay.addWidget(self.nav)
        lay.addWidget(self.stack, 1)
        self.setCentralWidget(central)


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("pllsim")
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
