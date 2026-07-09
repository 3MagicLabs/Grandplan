"""Tests for ClipboardCapturer logic (clipboard backend mocked)."""

from __future__ import annotations

import pytest

from grandplan.adapters.capture import ClipboardCapturer, HotkeyDebouncer, resolve_hotkey


class FakeClipboard:
    """In-memory clipboard: `read()` returns whatever the user has copied. No writer, no synthetic
    copy — the safe copy-first model injects zero keystrokes."""

    def __init__(self, *, clipboard: str | None = None) -> None:
        self.clipboard = clipboard

    def read(self) -> str | None:
        return self.clipboard


def _uia(text: str | None):  # type: ignore[no-untyped-def]
    return lambda: text


def test_uia_selection_is_used_without_touching_the_clipboard() -> None:
    # Native apps (Notepad, etc.) expose their selection to UI Automation — capture it directly.
    fake = FakeClipboard(clipboard="something else entirely")
    assert (
        ClipboardCapturer(fake, uia=_uia("selected in notepad")).capture() == "selected in notepad"
    )


def test_falls_back_to_the_text_the_user_copied() -> None:
    # Web apps (Gmail, iCloud web, Docs) expose nothing to UIA → we read what the user copied with
    # their OWN Ctrl+C. grandplan injects no keystrokes — safe in every app.
    fake = FakeClipboard(clipboard="text I copied from gmail")
    assert ClipboardCapturer(fake, uia=_uia(None)).capture() == "text I copied from gmail"


def test_empty_clipboard_returns_none() -> None:
    assert ClipboardCapturer(FakeClipboard(clipboard="   "), uia=_uia(None)).capture() is None
    assert ClipboardCapturer(FakeClipboard(clipboard=None), uia=_uia(None)).capture() is None


def test_repeated_trigger_on_unchanged_clipboard_does_not_re_capture() -> None:
    # Pressing the hotkey again WITHOUT a fresh copy must be a no-op — never re-file stale content
    # (the old "it captured a background command" class of bug). A new copy captures again.
    fake = FakeClipboard(clipboard="my note")
    cap = ClipboardCapturer(fake, uia=_uia(None))
    assert cap.capture() == "my note"  # fresh copy → captured
    assert cap.capture() is None  # unchanged clipboard → skipped
    fake.clipboard = "a different note"  # user copies something new
    assert cap.capture() == "a different note"  # fresh again → captured


def test_capturer_only_needs_a_reader_never_injects_keystrokes() -> None:
    # SAFETY: the backend exposes only read() — no clipboard writer, no synthetic Ctrl+C. So capture
    # can never open DevTools, steal focus, or corrupt the user's typing (all caused by injection).
    class ReadOnlyBackend:
        def read(self) -> str | None:
            return "copied text"

    assert ClipboardCapturer(ReadOnlyBackend(), uia=_uia(None)).capture() == "copied text"


# -- hotkey resolution + debounce ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("spec", "expected"),
    [
        ("ctrl+shift+space", "<ctrl>+<shift>+<space>"),  # default — no Alt, no AltGr conflict
        ("Ctrl+Shift+G", "<ctrl>+<shift>+g"),  # case-insensitive; single char stays BARE (pynput)
        ("win+shift+s", "<cmd>+<shift>+s"),  # win/super/meta → cmd
        ("super+space", "<cmd>+<space>"),
        ("control+shift+g", "<ctrl>+<shift>+g"),  # "control" → "ctrl"
        ("copilot", "<shift>+<cmd>+<134>"),  # Windows Copilot key = Shift+Win+F23 (VK_F23 = 134)
        ("COPILOT", "<shift>+<cmd>+<134>"),  # alias is case-insensitive
        ("<ctrl>+<alt>+g", "<ctrl>+<alt>+g"),  # already pynput notation → passed through verbatim
        ("  ctrl+shift+space  ", "<ctrl>+<shift>+<space>"),  # surrounding whitespace tolerated
    ],
)
def test_resolve_hotkey_normalizes_specs(spec: str, expected: str) -> None:
    assert resolve_hotkey(spec) == expected


def test_resolved_default_and_copilot_chords_parse_under_pynput() -> None:
    # Guard the contract with the listener: whatever resolve_hotkey emits MUST be parseable by
    # pynput's GlobalHotKeys, or the listener would crash at startup.
    keyboard = pytest.importorskip("pynput.keyboard")
    # The default + the recommended remapped-key target (f13, a single non-printable key) + copilot.
    for spec in ("ctrl+shift+g", "f13", "copilot"):
        keyboard.HotKey.parse(resolve_hotkey(spec))  # raises ValueError if unparseable


def test_debouncer_drops_repeat_fires_within_the_window() -> None:
    clock = {"t": 100.0}
    deb = HotkeyDebouncer(0.7, now=lambda: clock["t"])

    assert deb.allow() is True  # first fire always passes
    clock["t"] += 0.3
    assert deb.allow() is False  # too soon — a burst/repeat is dropped
    clock["t"] += 0.3
    assert deb.allow() is False  # still within 0.7s of the LAST accepted fire
    clock["t"] += 1.0
    assert deb.allow() is True  # enough time elapsed — a deliberate later capture passes


# -- dead hotkey-listener detection (#7) -----------------------------------------------------------
# A listener that crashes OR quietly returns used to die silently — the user just saw a hotkey
# that never worked again. Every exit path must now report a reason via on_dead.


class _FakeListener:
    def __init__(self, mapping: dict, *, crash: Exception | None = None) -> None:
        self._crash = crash

    def __enter__(self) -> "_FakeListener":
        return self

    def __exit__(self, *args: object) -> bool:
        return False

    def join(self) -> None:
        if self._crash is not None:
            raise self._crash


def _fake_pynput(monkeypatch: pytest.MonkeyPatch, *, crash: Exception | None = None) -> None:
    import sys
    import types

    keyboard = types.SimpleNamespace(
        GlobalHotKeys=lambda mapping: _FakeListener(mapping, crash=crash)
    )
    monkeypatch.setitem(sys.modules, "pynput", types.SimpleNamespace(keyboard=keyboard))
    monkeypatch.setitem(sys.modules, "pynput.keyboard", keyboard)


def test_listener_crash_reports_reason_via_on_dead(monkeypatch: pytest.MonkeyPatch) -> None:
    from grandplan.adapters.capture import run_hotkey_listener

    _fake_pynput(monkeypatch, crash=RuntimeError("OS hook refused"))
    reasons: list[str] = []
    run_hotkey_listener("ctrl+shift+g", lambda: None, on_dead=reasons.append)
    assert len(reasons) == 1
    assert "crashed" in reasons[0] and "OS hook refused" in reasons[0]


def test_listener_quiet_stop_also_reports_via_on_dead(monkeypatch: pytest.MonkeyPatch) -> None:
    # pynput returning normally is AS dead as a crash — must not be treated as success.
    from grandplan.adapters.capture import run_hotkey_listener

    _fake_pynput(monkeypatch)
    reasons: list[str] = []
    run_hotkey_listener("ctrl+shift+g", lambda: None, on_dead=reasons.append)
    assert len(reasons) == 1
    assert "stopped" in reasons[0]


def test_listener_death_without_on_dead_does_not_raise(monkeypatch: pytest.MonkeyPatch) -> None:
    from grandplan.adapters.capture import run_hotkey_listener

    _fake_pynput(monkeypatch, crash=RuntimeError("boom"))
    run_hotkey_listener("ctrl+shift+g", lambda: None)  # must not propagate


def test_failing_on_dead_callback_is_contained(monkeypatch: pytest.MonkeyPatch) -> None:
    from grandplan.adapters.capture import run_hotkey_listener

    _fake_pynput(monkeypatch)

    def bad_callback(reason: str) -> None:
        raise RuntimeError("notifier exploded")

    run_hotkey_listener("ctrl+shift+g", lambda: None, on_dead=bad_callback)  # must not propagate
