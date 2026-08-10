"""Bilingual labels for the Qt GUI.

The Streamlit side gets this for free: it re-runs the whole script on every
interaction, so `L(zh, en)` reading a session variable is enough.  Qt builds
its widgets once and keeps them, so a language switch has to find every label
already on screen and set its text again -- which means remembering, at build
time, which string pair produced each one.

`tr()` does the remembering.  Wrap a widget's text at construction and the
registry can re-apply it later:

    lay.addWidget(tr(QLabel(), "参考频率", "reference frequency"))
    self.btn = tr(QPushButton(), "运行", "Run")

Widgets are held weakly, so a page that is torn down does not keep its labels
alive or get text pushed into a deleted C++ object.
"""
from __future__ import annotations

import weakref
from typing import Callable

_LANG = "en"
# (weakref to widget, apply(widget, text), zh, en)
_REG: list[tuple[weakref.ref, Callable, str, str]] = []
_LISTENERS: list[Callable[[str], None]] = []


def lang() -> str:
    return _LANG


def L(zh: str, en: str) -> str:
    """The string for the current language, for text that is not on a widget."""
    return zh if _LANG == "zh" else en


def _default_apply(w, text: str) -> None:
    for name in ("setText", "setPlainText", "setTitle", "setWindowTitle"):
        fn = getattr(w, name, None)
        if fn is not None:
            fn(text)
            return
    raise TypeError(f"{type(w).__name__} has no text setter; pass apply=")


def tr(widget, zh: str, en: str, apply: Callable | None = None):
    """Register `widget`'s label and set it for the current language.

    Returns the widget, so it can be wrapped inline at construction.
    """
    fn = apply or _default_apply
    fn(widget, zh if _LANG == "zh" else en)
    _REG.append((weakref.ref(widget), fn, zh, en))
    return widget


def set_lang(code: str) -> None:
    """Switch language and re-apply every registered label."""
    global _LANG
    if code not in ("zh", "en"):
        raise ValueError("language must be 'zh' or 'en'")
    _LANG = code
    alive = []
    for ref, fn, zh, en in _REG:
        w = ref()
        if w is None:
            continue
        try:
            fn(w, zh if code == "zh" else en)
        except RuntimeError:
            continue          # underlying C++ object already deleted
        alive.append((ref, fn, zh, en))
    _REG[:] = alive
    for cb in _LISTENERS:
        cb(code)


def on_language_change(cb: Callable[[str], None]) -> None:
    """Register a callback for text that is not a widget label.

    Table headers, plot titles and anything rebuilt on demand cannot be
    re-applied by the registry, so their owners re-render themselves here.
    """
    _LISTENERS.append(cb)


def registered_count() -> int:
    """How many live labels the registry holds (used by the tests)."""
    return sum(1 for ref, *_ in _REG if ref() is not None)
