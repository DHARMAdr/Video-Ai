"""
analyze.py - measures the NON-speech signals of a video: loudness and scene cuts.

WHY it exists:
    Viral clips are not only about words. Loud / dynamic moments and fast visual changes keep
    people watching. These numbers feed the "energy" and "visual" parts of the score.

HOW it works:
    - audio_energy(): ffmpeg decodes the audio to raw numbers; numpy measures loudness (RMS)
      for every half second.
    - scene_cuts(): ffmpeg's `select=gt(scene,X)` filter flags frames that differ a lot from the
      previous one. We read the time of each flagged frame from ffmpeg's log text.
    - Signals: a small helper class that answers "how loud / how many cuts between t1 and t2?"

HOW TO IMPROVE:
    - Stream the audio in chunks instead of loading it all (needed for 3+ hour videos).
    - Add laughter / applause detection (e.g. a small audio-classification model).
    - Add motion detection and face-emotion detection for visual interest.
"""

import re
import subprocess
from pathlib import Path

import numpy as np

SAMPLE_RATE = 16000  # 16 kHz mono is plenty to measure loudness and keeps memory small


def audio_energy(video: Path, hop: float = 0.5):
    """Return (hop_seconds, array_of_loudness_values). One value per `hop` seconds."""
    cmd = [
        "ffmpeg", "-v", "error", "-i", str(video),
        "-vn", "-ac", "1", "-ar", str(SAMPLE_RATE),
        "-f", "s16le", "-",              # raw 16-bit numbers sent to stdout
    ]
    raw = subprocess.run(cmd, capture_output=True).stdout
    audio = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    step = int(SAMPLE_RATE * hop)
    frames = len(audio) // step
    if frames == 0:
        return hop, np.zeros(1, dtype=np.float32)
    chunks = audio[: frames * step].reshape(frames, step)
    rms = np.sqrt((chunks ** 2).mean(axis=1))   # RMS = a standard loudness measure
    return hop, rms


def scene_cuts(video: Path, threshold: float = 0.3) -> list:
    """Return a list of times (seconds) where the picture changes a lot (a 'cut')."""
    vf = f"scale=320:-2,select=gt(scene\\,{threshold}),showinfo"  # small frames = fast
    cmd = ["ffmpeg", "-v", "info", "-i", str(video), "-vf", vf, "-an", "-f", "null", "-"]
    log = subprocess.run(cmd, capture_output=True, text=True).stderr
    return [float(t) for t in re.findall(r"pts_time:([0-9.]+)", log)]


class Signals:
    """Holds loudness + cuts and answers questions about any time window."""

    def __init__(self, hop, rms, cuts):
        self.hop = hop
        self.rms = np.asarray(rms, dtype=np.float32)
        self.cuts = list(cuts)
        # "Reference loudness": the 90th percentile of the whole video.
        # We compare each window to it, so quiet and loud videos are judged fairly.
        self.ref = max(float(np.percentile(self.rms, 90)), 1e-6) if len(self.rms) else 1e-6

    def energy_stats(self, start: float, end: float):
        """Return (level 0-1, dynamics 0-1, silence_ratio 0-1) for a time window."""
        a = int(start / self.hop)
        b = max(a + 1, int(end / self.hop))
        window = self.rms[a:b]
        if len(window) == 0:
            return 0.5, 0.5, 0.0
        level = float(np.clip(window.mean() / self.ref, 0, 1))
        dynamics = float(np.clip(window.std() / (self.ref * 0.5), 0, 1))
        silence = float((window < self.ref * 0.1).mean())
        return level, dynamics, silence

    def cuts_per_10s(self, start: float, end: float) -> float:
        """How many scene cuts happen per 10 seconds inside the window."""
        count = sum(1 for c in self.cuts if start <= c <= end)
        return count / max((end - start) / 10.0, 0.1)

    def to_dict(self):
        """Make it JSON-friendly so we can cache it on disk."""
        return {"hop": self.hop, "rms": [round(float(x), 5) for x in self.rms], "cuts": self.cuts}

    @classmethod
    def from_dict(cls, data):
        return cls(data["hop"], data["rms"], data["cuts"])


def compute_signals(video: Path) -> Signals:
    """Run both measurements and bundle them."""
    hop, rms = audio_energy(video)
    return Signals(hop, rms, scene_cuts(video))
