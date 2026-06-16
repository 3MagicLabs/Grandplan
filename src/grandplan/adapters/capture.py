"""Windows selection capture (issue #6) — conforms to the `Capturer` port.

Universal method: save the clipboard → send Ctrl+C → read the selection → **restore** the prior
clipboard (so we never clobber it). An optional Windows UI Automation probe is tried first — it
reads the selection directly without touching the clipboard. The clipboard/keyboard backend is
injected, so the save/restore/fallback LOGIC is unit-tested here; the real backend
(pyperclip + pynput + uiautomation) is lazily imported and integration-tested on Windows
(`pip install grandplan[windows]`).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

SelectionProbe = Callable[[], str | None]


class ClipboardBackend(Protocol):
    """OS clipboard + copy-keystroke operations (injected so the logic is testable)."""

    def read(self) -> str | None: ...

    def write(self, text: str) -> None: ...

    def send_copy(self) -> None: ...


class ClipboardCapturer:
    """Capture the current selection via the clipboard, preserving prior clipboard contents."""

    def __init__(self, backend: ClipboardBackend, *, uia: SelectionProbe | None = None) -> None:
        self._backend = backend
        self._uia = uia

    def capture(self) -> str | None:
        if self._uia is not None:
            selected = self._uia()
            if selected and selected.strip():
                return selected
        previous = self._backend.read()
        self._backend.send_copy()
        selected = self._backend.read()
        self._backend.write(previous if previous is not None else "")
        if selected and selected.strip():
            return selected
        return None


class _WindowsClipboardBackend:  # pragma: no cover - needs Windows + grandplan[windows]
    def read(self) -> str | None:
        import pyperclip

        text = pyperclip.paste()
        return text or None

    def write(self, text: str) -> None:
        import pyperclip

        pyperclip.copy(text)

    def send_copy(self) -> None:
        import time

        from pynput.keyboard import Controller, Key

        keyboard = Controller()
        with keyboard.pressed(Key.ctrl):
            keyboard.press("c")
            keyboard.release("c")
        time.sleep(0.05)  # let the foreground app populate the clipboard


def _uia_selection() -> str | None:  # pragma: no cover - needs Windows UI Automation
    try:
        import uiautomation as auto
    except ImportError:
        return None
    try:
        control = auto.GetFocusedControl()
        pattern = control.GetTextPattern() if control else None
        if pattern is None:
            return None
        ranges = pattern.GetSelection()
        text = "".join(text_range.GetText(-1) for text_range in ranges) if ranges else ""
        return text or None
    except Exception:
        return None


def make_windows_capturer() -> ClipboardCapturer:  # pragma: no cover - Windows wiring
    return ClipboardCapturer(_WindowsClipboardBackend(), uia=_uia_selection)


def run_hotkey_listener(hotkey: str, on_trigger: Callable[[], None]) -> None:  # pragma: no cover
    from pynput import keyboard

    with keyboard.GlobalHotKeys({hotkey: on_trigger}) as listener:
        listener.join()
