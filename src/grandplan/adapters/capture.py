"""Windows selection capture (issue #6) — conforms to the `Capturer` port.

SAFE, no-synthesis model: grandplan NEVER injects keystrokes. It captures your selection two ways,
both harmless:
- **UI Automation** — reads the selection straight from the focused control (native apps like
  Notepad). No clipboard, no keystrokes.
- **Copy-first** — for apps UIA can't read (browsers / web apps: Gmail, iCloud web, Docs) you press
  Ctrl+C yourself (your own copy works in every app on every keyboard), then the hotkey; grandplan
  reads what you copied. It remembers the last text it captured, so pressing the hotkey again
  without a fresh copy is a no-op (it never re-files stale clipboard content) — copy something new.

Why no synthetic Ctrl+C: an earlier design pressed Ctrl+C *for* you on the hotkey. With a MODIFIER
hotkey (e.g. ctrl+shift+g) that landed as Ctrl+Shift+C while the keys were held — opening Chrome
DevTools and, by clashing with the physically-held keys, leaving a modifier stuck DOWN so the
user's typing turned into shortcuts that DELETED their text (observed live). Reading the user's own
copy removes that entire class of harm, needs no exotic non-modifier key, and works everywhere.

The capture LOGIC is injected + unit-tested here; the OS backend (pyperclip read + uiautomation) is
lazily imported and integration-tested on Windows (`pip install grandplan[windows]`).
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Protocol

logger = logging.getLogger(__name__)

SelectionProbe = Callable[[], str | None]


class ClipboardBackend(Protocol):
    """Read the OS clipboard (injected so the capture logic is testable)."""

    def read(self) -> str | None: ...


class ClipboardCapturer:
    """Capture the user's selection safely — UI Automation for native apps, else the text they
    copied (copy-first). Injects NO keystrokes, so it can never open DevTools, steal focus, or
    corrupt the user's typing."""

    def __init__(self, backend: ClipboardBackend, *, uia: SelectionProbe | None = None) -> None:
        self._backend = backend
        self._uia = uia
        self._last_captured: str | None = None  # skip re-capturing an unchanged clipboard

    def capture(self) -> str | None:
        # 1) UI Automation — reads the CURRENT selection from the focused control with no keystrokes.
        #    Works for native controls (Notepad, etc.); web apps expose nothing here → fall through.
        if self._uia is not None:
            selected = self._uia()
            logger.debug("capture: UIA probe returned %d chars", len(selected or ""))
            if selected and selected.strip():
                return selected
        # 2) Copy-first — read what the user copied (their own Ctrl+C, safe in every app). We inject
        #    NOTHING. Only capture text that CHANGED since the last capture, so a repeated hotkey on a
        #    stale clipboard is a no-op instead of re-filing old content.
        current = self._backend.read()
        logger.debug("capture: clipboard has %d chars", len(current or ""))
        if not (current and current.strip()):
            return None  # nothing on the clipboard — select text and press Ctrl+C first
        if current == self._last_captured:
            logger.debug("capture: clipboard unchanged since last capture — skipping")
            return None  # not a fresh copy — copy the text you want, then trigger
        self._last_captured = current
        return current


class _WindowsClipboardBackend:  # pragma: no cover - needs Windows + grandplan[windows]
    def read(self) -> str | None:
        import pyperclip

        text = pyperclip.paste()
        return text or None


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
        # Length only (never the user's text). A browser typically returns 0 chars here (its rendered
        # selection isn't exposed on the focused control) → we fall back to the clipboard.
        logger.debug(
            "UIA: %d selection range(s), %d chars", len(ranges) if ranges else 0, len(text)
        )
        return text or None
    except Exception:  # noqa: BLE001 - UIA can fail many ways; fall back to clipboard, but log why
        logger.debug("UIA selection probe failed; falling back to clipboard capture", exc_info=True)
        return None


def make_windows_capturer() -> ClipboardCapturer:  # pragma: no cover - Windows wiring
    # UI Automation for native apps + read the user's own copy for everything else. No keystrokes
    # are ever injected, so capture can never open DevTools, steal focus, or corrupt typing.
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
