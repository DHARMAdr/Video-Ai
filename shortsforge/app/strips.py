"""
strips.py - small pictures for the editor timeline: a film strip for video, a wave shape for sound.

WHY: coloured bars all look the same. Pictures and waves show you WHERE to cut.
HOW: film strip = 40 frames taken evenly from the whole file, side by side (80x45 each).
     wave = ffmpeg draws the loudness of the whole file as one picture.
     Both are saved in <output>/_editor/strips, so each file is only worked on once.
HOW TO IMPROVE: more frames for very long videos; make them in the background.
"""

import base64
import hashlib
import json
import subprocess
from pathlib import Path

COUNT, WIDTH, HEIGHT = 40, 80, 45


def _duration(path: Path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-print_format", "json", "-show_format",
                          str(path)], capture_output=True, text=True, check=True).stdout
    return float(json.loads(out)["format"]["duration"])


def _film(path: Path, duration: float, target: Path) -> None:
    import cv2
    import numpy as np

    cap = cv2.VideoCapture(str(path))
    sheet = np.zeros((HEIGHT, WIDTH * COUNT, 3), np.uint8)
    for i in range(COUNT):
        cap.set(cv2.CAP_PROP_POS_MSEC, duration * (i + 0.5) / COUNT * 1000)
        ok, frame = cap.read()
        if not ok:
            continue
        sheet[:, i * WIDTH:(i + 1) * WIDTH] = cv2.resize(frame, (WIDTH, HEIGHT))
    cap.release()
    ok, data = cv2.imencode(".jpg", sheet, [cv2.IMWRITE_JPEG_QUALITY, 70])
    if not ok:
        raise ValueError("Could not make the film strip.")
    target.write_bytes(data.tobytes())            # works with any folder name, unlike imwrite


def _wave(path: Path, target: Path) -> None:
    done = subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-i", str(path), "-filter_complex",
         "[0:a]aformat=channel_layouts=mono,showwavespic=s=2000x56:colors=0x4a90d9:scale=sqrt",
         "-frames:v", "1", str(target)], capture_output=True, text=True)
    if done.returncode:
        raise ValueError("This file has no sound to draw.")


def strip(out_dir: Path, path: Path, kind: str) -> dict:
    """{"duration": seconds, "count": frames, "image": data URL} for one file."""
    if kind not in ("film", "wave"):
        raise ValueError("Unknown strip type.")
    info = path.stat()
    name = hashlib.sha1(f"{path.resolve()}|{info.st_mtime_ns}|{info.st_size}|{kind}".encode()).hexdigest()
    folder = Path(out_dir) / "_editor" / "strips"
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / (name + (".jpg" if kind == "film" else ".png"))
    duration = _duration(path)
    if not target.exists():
        if kind == "film":
            _film(path, duration, target)
        else:
            _wave(path, target)
    mime = "image/jpeg" if kind == "film" else "image/png"
    return {"duration": duration, "count": COUNT,
            "image": f"data:{mime};base64,{base64.b64encode(target.read_bytes()).decode()}"}
