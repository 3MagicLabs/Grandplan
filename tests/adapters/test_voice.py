"""Tests for VoiceCapturer — transcript handling + error fallback (the offline-STT capture seam)."""

from __future__ import annotations

from grandplan.adapters.voice import VoiceCapturer
from grandplan.core.ports import Capturer


class _FakeTranscriber:
    def __init__(self, result: str | None = None, *, boom: bool = False) -> None:
        self._result = result
        self._boom = boom

    def transcribe(self) -> str | None:
        if self._boom:
            raise RuntimeError("microphone unavailable")
        return self._result


def test_voice_capturer_conforms_to_capturer_port() -> None:
    capturer: Capturer = VoiceCapturer(_FakeTranscriber("hello"))
    assert capturer.capture() == "hello"


def test_voice_capturer_strips_whitespace() -> None:
    assert VoiceCapturer(_FakeTranscriber("  buy milk  ")).capture() == "buy milk"


def test_voice_capturer_returns_none_on_silence() -> None:
    assert VoiceCapturer(_FakeTranscriber(None)).capture() is None
    assert VoiceCapturer(_FakeTranscriber("   ")).capture() is None


def test_voice_capturer_returns_none_on_backend_error() -> None:
    assert VoiceCapturer(_FakeTranscriber(boom=True)).capture() is None
