"""Windows selection capture (issue #6) — conforms to the `Capturer` port.

Universal method: save the clipboard → **clear it** → send Ctrl+C → read the *fresh* selection
(still empty ⇒ nothing was highlighted, so we capture nothing rather than whatever a background
process last left on the clipboard) → **restore** the prior clipboard (so we never clobber it). An
optional Windows UI Automation probe is tried first — it reads the current selection directly from
the focused control without touching the clipboard at all. The clipboard/keyboard backend is
injected, so the save/restore/fallback LOGIC is unit-tested here; the real backend
(pyperclip + pynput + uiautomation) is lazily imported and integration-tested on Windows
(`pip install grandplan[windows]`).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Protocol

logger = logging.getLogger(__name__)

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
        # 1) Prefer UI Automation: it reads the CURRENT selection straight from the focused control,
        #    never touching the clipboard — so it can't pick up stale or background-written content.
        if self._uia is not None:
            selected = self._uia()
            if selected and selected.strip():
                return selected
        # 2) Clipboard fallback. CLEAR the clipboard first, THEN copy: if the user has nothing
        #    highlighted (or Ctrl+C is a no-op, e.g. a terminal where it means SIGINT), the clipboard
        #    stays empty and we return None — instead of returning whatever a background process last
        #    left on the clipboard. Only a real Ctrl+C of the current selection re-populates it.
        previous = self._backend.read()
        self._backend.write(
            ""
        )  # clear so "no fresh selection" is distinguishable from stale content
        self._backend.send_copy()
        selected = self._backend.read()
        self._backend.write(previous if previous is not None else "")  # restore prior clipboard
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

        import pyperclip
        from pynput.keyboard import Controller, Key

        keyboard = Controller()
        with keyboard.pressed(Key.ctrl):
            keyboard.press("c")
            keyboard.release("c")
        # POLL until the foreground app populates the clipboard, rather than waiting a fixed 50 ms.
        # The first/cold capture (and slow apps) can take far longer than 50 ms to respond to Ctrl+C;
        # with the clear-before-copy step that would read an empty clipboard and wrongly report
        # "nothing selected". When nothing is actually selected, this just polls out and stays empty.
        for _ in range(30):  # up to ~600 ms
            time.sleep(0.02)
            if pyperclip.paste():
                return


def _uia_selection() -> str | None:  # pragma: no cover - needs Windows UI Automation
    try:
        import uiautomation as auto
    except ImportError:
        return None
    try:
        control = auto.GetFocusedControl()
        # uiautomation generates pattern accessors dynamically; getattr sidesteps an
        # incomplete type stub while staying behaviour-identical at runtime.
        get_text_pattern = getattr(control, "GetTextPattern", None) if control else None
        pattern = get_text_pattern() if get_text_pattern else None
        if pattern is None:
            return None
        ranges = pattern.GetSelection()
        text = "".join(text_range.GetText(-1) for text_range in ranges) if ranges else ""
        return text or None
    except Exception:  # noqa: BLE001 - UIA can fail many ways; fall back to clipboard, but log why
        logger.debug("UIA selection probe failed; falling back to clipboard capture", exc_info=True)
        return None


def make_windows_capturer() -> ClipboardCapturer:  # pragma: no cover - Windows wiring
    return ClipboardCapturer(_WindowsClipboardBackend(), uia=_uia_selection)


def run_hotkey_listener(hotkey: str, on_trigger: Callable[[], None]) -> None:  # pragma: no cover
    from pynput import keyboard

    with keyboard.GlobalHotKeys({hotkey: on_trigger}) as listener:
        listener.join()
