"""
learn_profile.py - tunes the viral profile from REFERENCE shorts that YOU collect.

WHY it exists:
    The tool cannot (and must not) scrape Instagram/YouTube trends automatically - their rules
    forbid it and the data is not public. The honest, legal way to "copy what is viral" is:
    you save a handful of shorts you know performed well in your niche (for example your own
    best videos, or videos you have rights to study), and the tool MEASURES them.

HOW it works:
    For every video in the folder it measures: length, scene cuts per 10 s and (optionally)
    speaking speed. It takes the typical (median / quartile) values and writes them to
    viral_profile.learned.json, which config.py automatically merges over the defaults.
    Needs at least 3 videos. Delete the .learned.json file to go back to the defaults.

HOW TO IMPROVE:
    - Also learn loudness curve, caption density, first-3-seconds cut rate.
    - Store one learned profile per niche (folder name = niche).
    - Learn hook phrases by transcribing the first sentence of each reference video.
"""

import json
from pathlib import Path

import numpy as np

from . import analyze, ingest, segments
from .config import LEARNED_PROFILE_PATH

VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm", ".m4v"}


def learn(folder: str, with_speech: bool = False, model: str = "small", log=print) -> dict:
    """Measure every video in `folder` and write viral_profile.learned.json."""
    files = [p for p in sorted(Path(folder).iterdir()) if p.suffix.lower() in VIDEO_EXTENSIONS]
    if len(files) < 3:
        raise RuntimeError("Put at least 3 reference videos in the folder first.")

    durations, cut_rates, speeds = [], [], []
    for path in files:
        log(f"Measuring {path.name} ...")
        info = ingest.probe(path)
        durations.append(info["duration"])
        cuts = analyze.scene_cuts(path)
        cut_rates.append(len(cuts) / max(info["duration"] / 10.0, 0.1))
        if with_speech:
            from .transcribe import transcribe
            tr = transcribe(path, Path("output") / "_learn" / path.stem, model_size=model)
            words = sum(len(s["words"]) for s in segments.to_sentences(tr))
            speeds.append(words / max(info["duration"], 0.1))

    q = lambda arr, p: float(np.percentile(arr, p))   # short helper for percentiles
    learned = {
        "min_seconds": round(max(8.0, q(durations, 10)), 1),
        "max_seconds": round(min(59.0, q(durations, 90)), 1),
        "ideal_seconds": round(q(durations, 50), 1),
        "ideal_cuts_per_10s": [round(q(cut_rates, 25), 2), round(q(cut_rates, 75), 2)],
    }
    if speeds:
        learned["ideal_words_per_second"] = [round(q(speeds, 25), 2), round(q(speeds, 75), 2)]
    LEARNED_PROFILE_PATH.write_text(json.dumps(learned, indent=1), encoding="utf-8")
    log(f"Saved learned profile: {learned}")
    return learned
