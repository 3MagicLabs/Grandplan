"""Voice capture (offline STT) — conforms to the `Capturer` port (ROADMAP theme H / "PR-H").

A `VoiceCapturer` records a short audio clip and transcribes it **offline** to text, so the user can
capture an idea by speaking instead of typing. The recording + transcription backend is injected (a
`Transcriber`), so the capture LOGIC — empty/blank-transcript handling, error fallback — is unit-
tested here; the real backend (a local Whisper model + microphone) is lazily imported and integration-
tested on the user's machine (`pip install grandplan[voice]`). Offline by default (QAS-1): the
transcription runs against a *local* model — no audio ever leaves the device.
"""

from __future__ import annotations

import logging
from typing import Protocol

logger = logging.getLogger(__name__)


class Transcriber(Protocol):
    """Record a short utterance and return its transcript (None / blank if nothing was said)."""

    def transcribe(self) -> str | None: ...


class VoiceCapturer:
    """Capture an idea by voice: record → transcribe offline → return the text (None if silent)."""

    def __init__(self, transcriber: Transcriber) -> None:
        self._transcriber = transcriber

    def capture(self) -> str | None:
        try:
            text = self._transcriber.transcribe()
        except Exception as exc:  # noqa: BLE001 - mic unavailable, model not pulled, decode error
            logger.warning("voice capture failed: %s", exc)
            return None
        if text and text.strip():
            return text.strip()
        return None


class _WhisperTranscriber:  # pragma: no cover - needs a mic + grandplan[voice]
    """Offline STT: record from the default microphone, transcribe with a local Whisper model.

    Everything runs on-device (sounddevice for capture, faster-whisper for transcription) — no audio
    leaves the machine, preserving the offline-by-default invariant.
    """

    def __init__(self, *, model: str = "base.en", seconds: float = 8.0, samplerate: int = 16_000):
        self._model = model
        self._seconds = seconds
        self._samplerate = samplerate

    def transcribe(self) -> str | None:
        import sounddevice as sd
        from faster_whisper import WhisperModel

        frames = sd.rec(
            int(self._seconds * self._samplerate),
            samplerate=self._samplerate,
            channels=1,
            dtype="float32",
        )
        sd.wait()
        model = WhisperModel(self._model, device="cpu", compute_type="int8")
        segments, _info = model.transcribe(frames.flatten(), language="en")
        return " ".join(segment.text for segment in segments).strip() or None


def default_voice_capturer() -> VoiceCapturer:  # pragma: no cover - needs the optional backend
    """A VoiceCapturer wired to the local Whisper backend (lazy optional dep)."""
    return VoiceCapturer(_WhisperTranscriber())
