"""Tests for ClipboardCapturer logic (clipboard backend mocked)."""

from __future__ import annotations

import pytest

from grandplan.adapters.capture import ClipboardCapturer, HotkeyDebouncer, resolve_hotkey


class FakeClipboard:
    """In-memory clipboard backend; `send_copy` simulates Ctrl+C putting the selection on it."""

    def __init__(self, *, clipboard: str | None = None, selection: str | None = None) -> None:
        self.clipboard = clipboard
        self.selection = selection
        self.copies = 0

    def read(self) -> str | None:
        return self.clipboard

    def write(self, text: str) -> None:
        self.clipboard = text

    def send_copy(self) -> None:
        self.copies += 1
        self.clipboard = self.selection


def test_capture_returns_selection_and_restores_clipboard() -> None:
    fake = FakeClipboard(clipboard="PREV", selection="hello selection")
    assert ClipboardCapturer(fake).capture() == "hello selection"
    assert fake.copies == 1
    assert fake.clipboard == "PREV"  # prior clipboard restored


def test_empty_selection_returns_none_and_restores() -> None:
    fake = FakeClipboard(clipboard="PREV", selection="   ")
    assert ClipboardCapturer(fake).capture() is None
    assert fake.clipboard == "PREV"


def test_none_previous_clipboard_restored_as_empty_string() -> None:
    fake = FakeClipboard(clipboard=None, selection="x")
    assert ClipboardCapturer(fake).capture() == "x"
    assert fake.clipboard == ""


def test_uia_path_skips_clipboard() -> None:
    fake = FakeClipboard(clipboard="PREV", selection="unused")

    def uia() -> str | None:
        return "from uia"

    capturer = ClipboardCapturer(fake, uia=uia)
    assert capturer.capture() == "from uia"
    assert fake.copies == 0  # clipboard untouched
    assert fake.clipboard == "PREV"


def test_uia_none_falls_back_to_clipboard() -> None:
    fake = FakeClipboard(clipboard="PREV", selection="clip selection")

    def uia() -> str | None:
        return None

    assert ClipboardCapturer(fake, uia=uia).capture() == "clip selection"
    assert fake.copies == 1


def test_no_fresh_selection_never_captures_stale_clipboard() -> None:
    # Regression: a background process left content on the clipboard and the user highlighted nothing,
    # so Ctrl+C is a no-op and leaves the clipboard UNCHANGED. We must return None — never the stale
    # content the user didn't select (the real-world "it captured a background command" bug).
    class NoSelectionClipboard:
        """Ctrl+C copies nothing (no selection), so it leaves the clipboard exactly as it was."""

        def __init__(self, content: str) -> None:
            self.clipboard: str | None = content
            self.copies = 0

        def read(self) -> str | None:
            return self.clipboard

        def write(self, text: str) -> None:
            self.clipboard = text

        def send_copy(self) -> None:
            self.copies += 1  # no selection → does NOT change the clipboard

    fake = NoSelectionClipboard("STALE BACKGROUND COMMAND")
    assert ClipboardCapturer(fake).capture() is None  # not the stale content
    assert fake.clipboard == "STALE BACKGROUND COMMAND"  # prior clipboard restored


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
