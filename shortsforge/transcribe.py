"""
transcribe.py - turns speech into text WITH the exact time of every word.

WHY it exists:
    The whole tool "understands" a video mainly through what is said. Word timestamps let us
    (a) cut cleanly at sentence ends, (b) judge the hook, (c) draw word-by-word captions.

HOW it works:
    Uses faster-whisper (a fast, free, offline version of OpenAI Whisper). The first run
    downloads the model once (small ~460 MB). The result is saved to transcript.json so
    re-running the tool on the same video is instant.

Format of the result (also what you can give with --transcript if you already have one):
    {"language": "en", "segments": [{"start": 0.0, "end": 4.2, "text": "Hello there.",
                                     "words": [{"word": "Hello", "start": 0.0, "end": 0.4}, ...]}]}

HOW TO IMPROVE:
    - Use model "medium" or "large-v3" for better accuracy (slower).
    - Add speaker detection (diarization) so interviews can be cut per speaker.
    - Handle videos with no speech (music / gameplay) by using audio + visual signals only.
"""

import json
from pathlib import Path


def transcribe(video: Path, work_dir: Path, model_size: str = "small",
               language=None, force: bool = False) -> dict:
    """Return the transcript dict. Uses the cached file if it exists."""
    cache = work_dir / "transcript.json"
    if cache.exists() and not force:
        with open(cache, "r", encoding="utf-8") as handle:
            return json.load(handle)

    # Imported here (not at the top) so the rest of the tool still works,
    # and `doctor` can give a friendly message, if faster-whisper is not installed.
    from faster_whisper import WhisperModel

    from .paths import bundled_model   # the packaged app ships the model inside its folder

    # device="auto" uses your NVIDIA GPU if available, otherwise the CPU.
    # compute_type="int8" keeps memory use low and is fast on CPU.
    model = WhisperModel(bundled_model(model_size), device="auto", compute_type="int8")

    segments_iter, info = model.transcribe(
        str(video),
        word_timestamps=True,   # we need the time of each word
        vad_filter=True,        # skip long silences (voice activity detection)
        language=language,      # None = auto-detect
    )

    segments = []
    for seg in segments_iter:   # this loop is where the real work happens
        words = [
            {"word": w.word.strip(), "start": float(w.start), "end": float(w.end)}
            for w in (seg.words or [])
        ]
        segments.append({
            "start": float(seg.start), "end": float(seg.end),
            "text": seg.text.strip(), "words": words,
        })

    result = {"language": info.language, "segments": segments}
    work_dir.mkdir(parents=True, exist_ok=True)
    with open(cache, "w", encoding="utf-8") as handle:
        json.dump(result, handle, ensure_ascii=False, indent=1)
    return result
