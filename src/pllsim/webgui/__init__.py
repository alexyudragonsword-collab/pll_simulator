"""Streamlit web GUI, shipped inside the package.

It lives here rather than in a top-level gui/ directory so that a
`pip install pllsim[gui]` actually gets the pages: setuptools only collects
what is under src/.  `home_path()` is how every launcher (the console script,
the PyInstaller/Nuitka entry points, the tests) finds Home.py without
hardcoding a layout.
"""
from pathlib import Path


def package_dir() -> Path:
    return Path(__file__).resolve().parent


def home_path() -> Path:
    return package_dir() / "Home.py"


def main() -> None:
    """Console-script entry point: `pllsim-web`."""
    import sys

    from streamlit.web import cli as stcli
    sys.argv = ["streamlit", "run", str(home_path()), *sys.argv[1:]]
    sys.exit(stcli.main())
