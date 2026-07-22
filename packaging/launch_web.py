"""PyInstaller entry point for the Streamlit web GUI (onefile exe).

Built by .github/workflows/windows-exe.yml:
    pyinstaller --onefile --name pllsim-gui-web --add-data "gui;gui"
                --collect-all streamlit --copy-metadata streamlit
                packaging/launch_web.py

The gui/ scripts ride along as DATA files (streamlit executes them from
the extracted bundle), so their imports are invisible to PyInstaller's
static analysis — the explicit pllsim imports below pull the whole
library into the bundle.  A console window stays open on purpose: it is
the server log.  The default browser opens automatically once the
server is up.
"""
import os
import sys
import threading
import time
import webbrowser

# static imports so PyInstaller bundles everything the pages use
import matplotlib  # noqa: F401
import pllsim.core.dtcspurs  # noqa: F401
import pllsim.export  # noqa: F401
import pllsim.fit  # noqa: F401
import pllsim.guiutil  # noqa: F401
import pllsim.modulation  # noqa: F401
import pllsim.montecarlo  # noqa: F401
import pllsim.plotting  # noqa: F401
import pllsim.presets  # noqa: F401
import pllsim.selector  # noqa: F401
import pllsim.settling  # noqa: F401
import pllsim.synth  # noqa: F401


def _base() -> str:
    if hasattr(sys, "_MEIPASS"):                 # frozen: extracted bundle
        return sys._MEIPASS
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main() -> None:
    from streamlit.web import cli as stcli

    script = os.path.join(_base(), "gui", "Home.py")
    port = os.environ.get("PLLSIM_PORT", "8501")
    url = f"http://localhost:{port}"

    def _open():
        time.sleep(4.0)
        try:
            webbrowser.open(url)
        except Exception:
            pass

    if not os.environ.get("PLLSIM_NO_BROWSER"):
        threading.Thread(target=_open, daemon=True).start()
    print(f"pllsim web GUI: {url}  (close this window to stop the server)")
    sys.argv = ["streamlit", "run", script,
                "--server.port", port,
                "--server.headless", "true",
                "--global.developmentMode", "false",
                "--browser.gatherUsageStats", "false"]
    sys.exit(stcli.main())


if __name__ == "__main__":
    main()
