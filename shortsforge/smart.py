"""
smart.py - finds exciting moments in ANY video, even when no kill could be confirmed.

WHY it exists:
    Before, a video with no detected kills gave you nothing. Now you still get the most exciting
    moments, clearly labelled "action moment" so nobody mistakes them for confirmed kills.

HOW it works (one number per half second for each clue, each scaled 0-1):
    - shots : sudden sharp sounds (gunfire, hits, impacts)
    - loud  : overall loudness (reactions, abilities, explosions)
    - motion: how much the whole picture changes
    - feed  : how much new text-like detail appears in the kill-feed corner (any colour)
    The clues are added with weights; the best non-overlapping windows become clips.

HONEST LIMITS:
    - It measures excitement, not meaning. A loud menu can score high.

HOW TO IMPROVE:
    - Skip music-like regular beats (lobby music).
    - Learn the weights from the clips you keep or delete.
"""

import subprocess
from pathlib import Path

import numpy as np

HOP = 0.5                              # seconds per value
SAMPLE_RATE = 16000
WEIGHTS = {"shots": 0.40, "loud": 0.20, "motion": 0.15, "feed": 0.25}


def audio_clues(video, n: int):
    """(shots, loud) arrays. Reads the sound in 60-second blocks to save memory."""
    shots, loud = np.zeros(n), np.zeros(n)
    cmd = ["ffmpeg", "-v", "error", "-nostdin", "-i", str(video), "-vn", "-ac", "1",
           "-ar", str(SAMPLE_RATE), "-f", "s16le", "-"]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    size = 320                                          # 20 ms slices
    per_hop = int(HOP * SAMPLE_RATE / size)
    window = np.hanning(size)
    bins = np.fft.rfftfreq(size, 1 / SAMPLE_RATE)
    high = (bins >= 1500) & (bins <= 7500)
    index, previous = 0, None
    try:
        while True:
            raw = proc.stdout.read(SAMPLE_RATE * 60 * 2)
            if len(raw) < size * 2:
                break
            audio = np.frombuffer(raw[: len(raw) // 2 * 2], dtype=np.int16) / 32768.0
            slices = audio[: len(audio) // size * size].reshape(-1, size)
            spectrum = np.log1p(np.abs(np.fft.rfft(slices * window, axis=1))[:, high])
            before = np.vstack([spectrum[:1] if previous is None else previous, spectrum[:-1]])
            flux = np.maximum(spectrum - before, 0).sum(axis=1)    # only NEW sound counts
            previous = spectrum[-1:]
            sharp = np.maximum(flux - 1.8 * np.median(flux), 0)
            rms = np.sqrt((slices ** 2).mean(axis=1))
            for i in range(len(slices)):
                j = (index + i) // per_hop
                if j < n:
                    shots[j] += sharp[i]
                    loud[j] = max(loud[j], rms[i])
            index += len(slices)
    finally:
        proc.kill()
        proc.wait()
        proc.stdout.close()
    return shots, loud


def picture_clues(video, n: int, roi=None):
    """(motion, feed) arrays from a tiny grey copy of the video, 4 pictures per second."""
    motion, feed = np.zeros(n), np.zeros(n)
    w, h = 320, 180
    cmd = ["ffmpeg", "-v", "error", "-nostdin", "-i", str(video), "-an", "-sn",
           "-vf", f"fps=4,scale={w}:{h}", "-f", "rawvideo", "-pix_fmt", "gray", "-"]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    previous, previous_edges, i = None, 0.0, 0
    try:
        while True:
            buf = proc.stdout.read(w * h)
            if len(buf) < w * h:
                break
            frame = np.frombuffer(buf, dtype=np.uint8).reshape(h, w).astype(np.int16)
            j = int(i / 4 / HOP)
            edges = 0.0
            if roi:
                part = frame[int(roi[1] * h): int(roi[3] * h), int(roi[0] * w): int(roi[2] * w)]
                edges = float((np.abs(np.diff(part, axis=1)) > 60).mean()) if part.size else 0.0
            if previous is not None and j < n:
                change = float(np.abs(frame - previous).mean()) / 255.0
                motion[j] = max(motion[j], change)
                if change < 0.2:                         # a scene cut is not a new feed line
                    feed[j] += max(0.0, edges - previous_edges - 0.002)
            previous, previous_edges, i = frame, edges, i + 1
    finally:
        proc.kill()
        proc.wait()
        proc.stdout.close()
    return motion, feed


def _scale(values, floor: float):
    """Scale to 0-1 using a high percentile; `floor` stops quiet noise looking important."""
    top = max(float(np.percentile(values, 98)) if len(values) else 0.0, floor)
    return np.clip(values / top, 0, 1)


def excitement(video, duration: float, roi=None, log=print) -> dict:
    """All clues plus the combined line, one value per half second."""
    n = max(1, int(np.ceil(duration / HOP)))
    log("Listening for action ...")
    shots, loud = audio_clues(video, n)
    log("Watching for movement ...")
    motion, feed = picture_clues(video, n, roi)
    clues = {"shots": _scale(shots, 20.0), "loud": _scale(loud, 0.05),
             "motion": _scale(motion, 0.03), "feed": _scale(feed, 0.01)}
    total = sum(WEIGHTS[k] * v for k, v in clues.items())
    kernel = np.ones(7) / 7                              # smooth over 3.5 s
    clues["total"] = np.convolve(total, kernel, mode="same")[:n]
    return clues


def pick_moments(clues: dict, duration: float, count: int, length: float = 16.0) -> list:
    """The best non-overlapping windows as 'plays' (same shape as highlights.py uses)."""
    total = clues["total"]
    length = min(length, duration)
    words = {"shots": "lots of sharp sounds", "loud": "loud audio",
             "motion": "fast movement", "feed": "new text in the kill-feed corner"}
    plays = []
    for j in np.argsort(total)[::-1]:
        if len(plays) >= count or total[j] < 0.05:
            break
        centre = (j + 0.5) * HOP
        start = max(0.0, min(duration - length, centre - length * 0.55))
        end = start + length
        if any(start < p["end"] and end > p["start"] for p in plays):
            continue
        a, b = int(start / HOP), max(int(start / HOP) + 1, int(end / HOP))
        means = {k: float(clues[k][a:b].max()) for k in words}
        reasons = [words[k] for k in sorted(means, key=means.get, reverse=True) if means[k] > 0.4][:3]
        score = round(float(min(1.0, total[j])) * 100, 1)
        plays.append({"kills": [], "count": 0, "start": start, "end": end, "label": "ACTION MOMENT",
                      "score": {"total": score, "base": score, "speed": 0, "energy": 0,
                                "reasons": reasons + ["NOT a confirmed kill"]}})
    return sorted(plays, key=lambda p: p["start"])


def find(video, info: dict, count: int, roi=None, log=print) -> list:
    """The whole job: measure, then pick."""
    clues = excitement(Path(video), info["duration"], roi, log=log)
    return pick_moments(clues, info["duration"], count)
