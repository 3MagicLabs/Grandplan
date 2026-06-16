"""Tests for ClipboardCapturer logic (clipboard backend mocked)."""

from __future__ import annotations

from grandplan.adapters.capture import ClipboardCapturer


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
