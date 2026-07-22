"""PyInstaller entry point for the PySide6 desktop GUI (onefile exe).

Built by .github/workflows/windows-exe.yml:
    pyinstaller --onefile --windowed --name pllsim-gui-qt packaging/launch_qt.py

All imports here are static so PyInstaller's analysis collects the full
pllsim tree (the pages import everything else transitively).
"""
from pllsim.guiqt.app import main

if __name__ == "__main__":
    main()
