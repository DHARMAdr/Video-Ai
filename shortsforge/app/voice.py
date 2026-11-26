"""
voice.py - turns what you SAY into text (offline), for the microphone button.

WHY it exists:
    The window cannot use the browser's online speech service. The app already carries the
    Whisper speech model for captions, so we use it for your voice too. Nothing leaves your PC.

HOW it works:
    The window records the microphone and sends the sound here. We save it to a temporary file,
    run Whisper on the processor (reliable on every PC) and return the words. The model is
    loaded once and kept, so the second command is much faster.

HOW TO IMPROVE:
    - Add a language choice in Settings if auto-detect picks the wrong one.
    - Use the graphics card once the NVIDIA libraries are bundled.
"""

import os
import tempfile
import threading
from pathlib import Path

from ..paths import bundled_model

MAX_AUDIO = 15 * 1024 * 1024            # bytes; several minutes of speech
_lock = threading.Lock()
_model = None


def _load():
    global _model
    if _model is None:
        from faster_whisper import WhisperModel
        _model = WhisperModel(bundled_model("small"), device="cpu", compute_type="int8")
    return _model


def transcribe_audio(data: bytes, language: str = "") -> str:
    """The words in a recording (webm, ogg, wav or mp4 sound)."""
    if len(data) < 1000:
        raise ValueError("I heard nothing. Hold on a little longer and speak after pressing the mic.")
    if len(data) > MAX_AUDIO:
        raise ValueError("That recording is too long.")
    handle, name = tempfile.mkstemp(suffix=".webm", prefix="sf_voice_")
    try:
        with os.fdopen(handle, "wb") as out:
            out.write(data)
        with _lock:                                   # one recording at a time
            try:
                segments, _ = _load().transcribe(name, vad_filter=True, language=language or None,
                                                 beam_size=3, condition_on_previous_text=False)
                return " ".join(s.text.strip() for s in segments).strip()
            except ImportError:
                raise ValueError("Voice typing needs the speech model, which this copy lacks.")
            except Exception as exc:                   # noqa: BLE001
                raise ValueError(f"Could not understand the recording ({exc}).")
    finally:
        Path(name).unlink(missing_ok=True)
