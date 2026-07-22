"""PySide6 desktop workbench for pllsim (English UI).

Launch:  pllsim-gui     (console script)
   or:   python -m pllsim.guiqt

All computation runs in worker threads; pages share the same pllsim APIs
as the Streamlit GUI and the examples.  Form generation reuses
pllsim.guiutil (no duplication of config introspection).
"""
