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

import contextlib
import logging
import time
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
        # The capture hotkey is a modifier combo (e.g. ctrl+shift+g, or ctrl+shift+f13 via the Copilot
        # key). pynput does not consume it, so when this runs those modifiers are still held — a raw
        # Ctrl+C would collide with the held SHIFT and become Ctrl+Shift+C, which copies NOTHING (the
        # clipboard stays empty and we wrongly report "no text selected"). Release every modifier and
        # let the key-up events register, THEN send a clean Ctrl+C. (Releasing a not-held key is a
        # harmless no-op, so this is safe regardless of which modifiers the chosen hotkey used.)
        for name in (
            "shift",
            "shift_l",
            "shift_r",
            "alt",
            "alt_l",
            "alt_r",
            "alt_gr",
            "cmd",
            "cmd_l",
            "cmd_r",
            "ctrl",
            "ctrl_l",
            "ctrl_r",
        ):
            modifier = getattr(Key, name, None)
            if modifier is not None:
                # Releasing a not-held key is a harmless no-op; suppress any backend error so a flaky
                # key-release can never break the capture itself.
                with contextlib.suppress(Exception):
                    keyboard.release(modifier)
        time.sleep(0.05)  # let the modifier-up events land before the synthetic copy
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


# Friendly hotkey specs → pynput GlobalHotKeys notation. We deliberately avoid Ctrl+Alt: on Windows
# Ctrl+Alt IS AltGr, so a Ctrl+Alt hotkey fires *while the user types* (punctuation/symbols on many
# layouts emit AltGr), which made the app capture continuously. `copilot` binds the dedicated Windows
# Copilot key, which emits Shift+Win+F23 — pynput's Key enum stops at f20, so we use F23's raw virtual
# key code (VK_F23 = 134). Modifier synonyms (win/super/meta→cmd, control→ctrl) are normalized.
_HOTKEY_NAMED_ALIASES: dict[str, str] = {"copilot": "<shift>+<cmd>+<134>"}
_HOTKEY_MODIFIER_ALIASES: dict[str, str] = {
    "win": "cmd",
    "super": "cmd",
    "meta": "cmd",
    "command": "cmd",
    "control": "ctrl",
}
# Repeat triggers within this window are dropped — a single intent can't spawn a burst of captures
# (a held key, OS key-repeat, or a stray double-fire). Deliberate back-to-back captures are seconds
# apart (you must re-select text), so they pass through unaffected.
_HOTKEY_DEBOUNCE_S = 0.7


def resolve_hotkey(spec: str) -> str:
    """Normalize a human hotkey spec into pynput GlobalHotKeys notation.

    - A named alias ("copilot") expands to its chord.
    - A spec already in pynput notation (contains "<") passes through unchanged.
    - Otherwise "+"-separated tokens are normalized (win/super→cmd, control→ctrl) and joined in
      pynput notation: multi-char keys are wrapped in angle brackets, single characters stay bare
      (pynput requires "<ctrl>+<shift>+g", NOT "<g>"): "ctrl+shift+space" → "<ctrl>+<shift>+<space>".
    """
    key = spec.strip().lower()
    if key in _HOTKEY_NAMED_ALIASES:
        return _HOTKEY_NAMED_ALIASES[key]
    if "<" in spec:
        return spec  # already pynput notation — pass through verbatim
    tokens = [
        _HOTKEY_MODIFIER_ALIASES.get(part, part)
        for part in (p.strip() for p in key.split("+"))
        if part
    ]
    return "+".join(token if len(token) == 1 else f"<{token}>" for token in tokens)


class HotkeyDebouncer:
    """Drops repeat fires that arrive within `interval` seconds of the last accepted one.

    The injected `now` clock (monotonic by default) keeps the throttle pure and unit-testable.
    """

    def __init__(self, interval: float, now: Callable[[], float] = time.monotonic) -> None:
        self._interval = interval
        self._now = now
        self._last: float | None = None

    def allow(self) -> bool:
        """True if a trigger should fire now; False if it's a too-soon repeat of the last one."""
        moment = self._now()
        if self._last is not None and moment - self._last < self._interval:
            return False
        self._last = moment
        return True


def run_hotkey_listener(
    hotkey: str,
    on_trigger: Callable[[], None],
    on_dead: Callable[[str], None] | None = None,
) -> None:
    """Block listening for the global hotkey; report EVERY way the listener can end (#7).

    Runs on a daemon thread. A listener that crashes (bad combo, OS hook refused, missing
    backend) — or simply *returns* (pynput stopped) — used to die SILENTLY: the user just saw a
    hotkey that never worked again. Now every exit path logs AND calls `on_dead(reason)` so the
    GUI can surface it (tray notification); the tray's "Capture now" keeps working regardless.
    """
    from pynput import keyboard

    resolved = resolve_hotkey(hotkey)
    debouncer = HotkeyDebouncer(_HOTKEY_DEBOUNCE_S)

    def fire() -> None:
        # Logged so `--debug` shows the hotkey is actually being detected (vs. a remap/parse problem):
        # if you press the key and see no "hotkey fired" line, pynput never received the combo.
        logger.info("hotkey fired: %s", resolved)
        if debouncer.allow():
            on_trigger()
        else:
            logger.info("hotkey fire ignored (debounced — too soon after the last)")

    reason = "hotkey listener stopped — the global capture hotkey is no longer active"
    try:
        logger.info("hotkey listener registered on %s (from spec %r)", resolved, hotkey)
        with keyboard.GlobalHotKeys({resolved: fire}) as listener:
            listener.join()
        logger.error(reason)  # a listener that ENDS quietly is as dead as one that crashed
    except Exception as exc:  # noqa: BLE001 - any registration/backend failure ends the listener
        reason = f"hotkey listener crashed — the global capture hotkey is NOT active ({exc})"
        # ERROR level so it surfaces on stderr (and the #5 file log) even without --debug.
        logger.exception("hotkey listener crashed — the global capture hotkey is NOT active")
    if on_dead is not None:
        try:
            on_dead(reason)
        except Exception:  # noqa: BLE001 - surfacing must never re-crash the dying thread
            logger.exception("on_dead callback failed")
