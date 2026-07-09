"""Windows selection capture (issue #6) — conforms to the `Capturer` port.

Universal method: save the clipboard → **clear it** → (wait for the user to let go of the hotkey
modifiers) → send Ctrl+C → read the *fresh* selection (still empty ⇒ nothing was highlighted, so
we capture nothing rather than whatever a background process last left on the clipboard) →
**restore** the prior clipboard (so we never clobber it). An optional Windows UI Automation probe
is tried first — it reads the current selection directly from the focused control without touching
the clipboard at all.

Browser/web-app capture + SAFETY: a web app doesn't expose its selection to UI Automation, so it
falls to the clipboard path — synthesize Ctrl+C, read the fresh clipboard. The danger is the
MODIFIER hotkey: if the synthetic Ctrl+C fires while the user still physically holds Ctrl+Shift
(from e.g. ctrl+shift+g), it lands as Ctrl+Shift+C — which opens Chrome's DevTools, and the
interleaving of synthetic and physical key events can leave a key stuck DOWN, turning the user's
next keystrokes into shortcuts that DELETE their text (observed live). So the capturer NEVER
injects Ctrl+C while modifiers are physically held: it waits (bounded) for release and, if they
stay held, SKIPS the copy (no capture, but no harm) — and the backend force-releases every key it
touches in a `finally`, so a partial sequence can never leave one stuck. Reliable browser capture
therefore wants a non-modifier hotkey (e.g. `--hotkey-combo f13`). A browser often drops the first
synthetic Ctrl+C on timing, so we retry once. The gate/retry logic lives in the injected,
unit-tested `ClipboardCapturer`; the OS backend (pyperclip + user32 keybd_event scan codes, pynput
fallback, uiautomation, GetAsyncKeyState) is integration-tested on Windows.
"""

from __future__ import annotations

import contextlib
import logging
import time
from collections.abc import Callable
from typing import Protocol

logger = logging.getLogger(__name__)

SelectionProbe = Callable[[], str | None]
ModifierProbe = Callable[[], bool]

# How long to wait for the user to physically release the hotkey modifiers before synthesizing
# Ctrl+C (so it isn't turned into Ctrl+Shift+C — which in Chrome opens DevTools and copies nothing,
# the observed Gmail-in-browser failure). The loop copies the INSTANT the keys go up; this is only
# the cap. Raised from 1s after a real capture held the chord ~1s+ and the wait timed out while
# still held. Still bounded so a genuinely stuck key can never hang a capture.
_MODIFIER_RELEASE_WAIT_S = 3.0
_MODIFIER_POLL_STEP_S = 0.02


class ClipboardBackend(Protocol):
    """OS clipboard + copy-keystroke operations (injected so the logic is testable)."""

    def read(self) -> str | None: ...

    def write(self, text: str) -> None: ...

    def send_copy(self) -> None: ...


class ClipboardCapturer:
    """Capture the current selection via the clipboard, preserving prior clipboard contents."""

    def __init__(
        self,
        backend: ClipboardBackend,
        *,
        uia: SelectionProbe | None = None,
        modifiers_held: ModifierProbe | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._backend = backend
        self._uia = uia
        self._modifiers_held = modifiers_held  # None ⇒ can't probe key state (tests / non-Windows)
        self._sleep = sleep

    def capture(self) -> str | None:
        # 1) Prefer UI Automation: it reads the CURRENT selection straight from the focused control,
        #    never touching the clipboard — so it can't pick up stale or background-written content.
        #    (Web apps like Gmail-in-a-browser don't expose it, so those fall through to step 2.)
        if self._uia is not None:
            selected = self._uia()
            # Log LENGTH only (never the user's text) — enough to see which stage yields nothing.
            logger.debug("capture: UIA probe returned %d chars", len(selected or ""))
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
        try:
            # SAFETY GATE: only ever synthesize Ctrl+C when the hotkey modifiers are physically
            # RELEASED. Injecting while Ctrl+Shift are held lands as Ctrl+Shift+C (opens Chrome's
            # DevTools) and interleaving synthetic + physical key events can leave a key stuck down,
            # turning the user's next keystrokes into shortcuts that DELETE their text. If the keys
            # stay held, we skip the copy entirely — no capture, but no harm.
            if not self._modifiers_released_for_copy():
                logger.warning(
                    "capture: hotkey modifiers still held — skipping synthetic copy to avoid "
                    "Ctrl+Shift+C. Release the keys, or use a non-modifier hotkey (e.g. --hotkey-combo f13)."
                )
                return None
            selected = self._copy_and_read()
            logger.debug("capture: clipboard after copy #1: %d chars", len(selected or ""))
            if not (selected and selected.strip()):
                # A browser/web app often ignores the FIRST synthetic Ctrl+C (focus/keystroke timing
                # is slower than a native control). One clean retry recovers it — safe because we
                # already cleared, so we still can't capture stale content.
                selected = self._copy_and_read()
                logger.debug("capture: clipboard after copy #2: %d chars", len(selected or ""))
            return selected if (selected and selected.strip()) else None
        finally:
            self._backend.write(previous if previous is not None else "")  # restore prior clipboard

    def _modifiers_released_for_copy(self) -> bool:
        """Wait (bounded) for the hotkey modifiers to be physically released. Returns True once they
        are — or if key state can't be probed (tests / non-Windows). Returns False if they are STILL
        held after the timeout, in which case the caller MUST NOT synthesize Ctrl+C (safety)."""
        if self._modifiers_held is None:
            return True
        waited = 0.0
        while waited < _MODIFIER_RELEASE_WAIT_S:
            if not self._modifiers_held():
                return True
            self._sleep(_MODIFIER_POLL_STEP_S)
            waited += _MODIFIER_POLL_STEP_S
        return not self._modifiers_held()  # one last check after the wait window

    def _copy_and_read(self) -> str | None:
        self._backend.send_copy()
        return self._backend.read()


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

        # Force the hotkey modifiers UP, then send a clean Ctrl+C. The user is typically STILL
        # physically holding the hotkey chord (e.g. ctrl+shift+g) when this runs, so a naive Ctrl+C
        # becomes Ctrl+Shift+C — which in Chrome opens DevTools and copies nothing (the Gmail bug).
        # Injecting scan-code key-UPs makes the target see the modifiers released regardless of the
        # physical keys, so the copy is clean without waiting on the user (AutoHotkey's technique).
        if not _force_clean_ctrl_c_windows():
            self._pynput_ctrl_c()  # fallback if the scan-code path is unavailable
        # POLL until the foreground app populates the clipboard, rather than waiting a fixed 50 ms.
        # The first/cold capture (and slow apps) can take far longer than 50 ms to respond to Ctrl+C;
        # with the clear-before-copy step that would read an empty clipboard and wrongly report
        # "nothing selected". When nothing is actually selected, this just polls out and stays empty.
        for _ in range(40):  # up to ~800 ms
            time.sleep(0.02)
            if pyperclip.paste():
                return

    def _pynput_ctrl_c(self) -> None:
        import time

        from pynput.keyboard import Controller, Key

        keyboard = Controller()
        for name in ("shift", "shift_l", "shift_r", "alt", "alt_l", "alt_r", "alt_gr", "ctrl"):
            modifier = getattr(Key, name, None)
            if modifier is not None:
                with contextlib.suppress(Exception):
                    keyboard.release(modifier)
        time.sleep(0.05)
        with keyboard.pressed(Key.ctrl):
            time.sleep(0.03)
            keyboard.press("c")
            time.sleep(0.03)
            keyboard.release("c")


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


def _force_clean_ctrl_c_windows() -> bool:  # pragma: no cover - needs Windows user32
    """Force Shift/Ctrl/Alt UP (scan-code), then send a clean Ctrl+C (scan-code). Returns True if sent.

    Scan-code key-UP events make the target app's input stream show the modifiers released even while
    the user still physically holds the hotkey chord, so the following Ctrl+C is a *clean* Ctrl+C —
    not Ctrl+Shift+C. Scan codes (not virtual keys) are also what Chromium apps reliably honor. This
    is why capture no longer needs the user to let go of the keys first."""
    try:
        import ctypes
        import time

        user32 = ctypes.windll.user32  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001 - fall back to the pynput path if user32 is unavailable
        logger.debug("user32 unavailable; falling back to pynput", exc_info=True)
        return False

    scancode = 0x0008  # KEYEVENTF_SCANCODE
    keyup = 0x0002  # KEYEVENTF_KEYUP
    sc_lshift, sc_rshift, sc_lctrl, sc_lalt, sc_c = 0x2A, 0x36, 0x1D, 0x38, 0x2E

    def key(sc: int, flags: int) -> None:
        user32.keybd_event(0, sc, flags, 0)  # vk=0: the scan code drives the event

    try:
        key(sc_lctrl, scancode)  # clean Ctrl down → C down → C up → Ctrl up
        time.sleep(0.02)
        key(sc_c, scancode)
        time.sleep(0.02)
        key(sc_c, scancode | keyup)
        key(sc_lctrl, scancode | keyup)
        return True
    except Exception:  # noqa: BLE001 - fall back to the pynput path
        logger.debug("scan-code clean Ctrl+C failed; falling back to pynput", exc_info=True)
        return False
    finally:
        # SAFETY (critical): never leave a key stuck DOWN. A stuck Ctrl turns the user's next
        # keystrokes into shortcuts (Ctrl+A, Ctrl+Backspace…) that delete their text — observed
        # live. Force every key we could have pressed UP, unconditionally, even on a partial or
        # interrupted sequence. The caller only reaches here with modifiers already released, so
        # these are harmless no-ops in the normal path.
        with contextlib.suppress(Exception):
            for sc in (sc_c, sc_lctrl, sc_lshift, sc_rshift, sc_lalt):
                key(sc, scancode | keyup)


def _windows_modifiers_held() -> bool:  # pragma: no cover - needs Windows user32
    """True while any hotkey modifier (Ctrl/Shift/Alt/Win) is PHYSICALLY down, via GetAsyncKeyState.

    The safety gate: the capturer refuses to synthesize Ctrl+C while this is True, so it can never
    land as Ctrl+Shift+C (Chrome DevTools) or corrupt the user's typing by clashing with the keys
    they're still holding."""
    try:
        import ctypes

        user32 = ctypes.windll.user32  # type: ignore[attr-defined]
        # VK: SHIFT 0x10, CONTROL 0x11, MENU(Alt) 0x12, LWIN 0x5B, RWIN 0x5C. High bit ⇒ key down.
        return any(user32.GetAsyncKeyState(vk) & 0x8000 for vk in (0x10, 0x11, 0x12, 0x5B, 0x5C))
    except Exception:  # noqa: BLE001 - if key state can't be read, don't block capture
        logger.debug("modifier-state probe failed", exc_info=True)
        return False


def make_windows_capturer() -> ClipboardCapturer:  # pragma: no cover - Windows wiring
    # modifiers_held gates the synthetic copy: capture waits for the hotkey keys to be released and
    # NEVER injects Ctrl+C while they're held (else Ctrl+Shift+C → DevTools / stuck keys / lost text).
    return ClipboardCapturer(
        _WindowsClipboardBackend(), uia=_uia_selection, modifiers_held=_windows_modifiers_held
    )


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
