"""
video.py - small tools to read a video: frames, one frame, shot changes, thumbnails.

WHY it exists:
    Several search steps need pictures from the video. Reading them in one place keeps the
    ffmpeg commands consistent, and ffmpeg works with every video type the app accepts.

HOW it works:
    ffmpeg writes raw pixels to a "pipe"; we cut that stream into pictures of equal size.

HOW TO IMPROVE:
    - Use the graphics card to decode (-hwaccel auto) for long 1440p recordings.
"""

import base64
import subprocess

import numpy as np


def sized(info: dict, width: int):
    """(width, height) of a scaled-down copy, both even numbers."""
    width = min(width, info["width"]) // 2 * 2
    return width, int(round(info["height"] * width / info["width"])) // 2 * 2


def frames(path, info: dict, fps: float, width: int = 640, start: float = 0.0, end=None, gray=False):
    """Yield (time_in_seconds, picture) from the video."""
    w, h = sized(info, width)
    cmd = ["ffmpeg", "-v", "error", "-nostdin"]
    if start > 0:
        cmd += ["-ss", f"{start:.3f}"]
    cmd += ["-i", str(path)]
    if end is not None:
        cmd += ["-t", f"{max(0.05, end - start):.3f}"]
    cmd += ["-an", "-sn", "-vf", f"fps={fps},scale={w}:{h}", "-f", "rawvideo",
            "-pix_fmt", "gray" if gray else "bgr24", "-"]
    shape = (h, w) if gray else (h, w, 3)
    size = w * h * (1 if gray else 3)
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    index = 0
    try:
        while True:
            buf = proc.stdout.read(size)
            if len(buf) < size:
                break
            yield start + index / fps, np.frombuffer(buf, dtype=np.uint8).reshape(shape)
            index += 1
    finally:
        proc.kill()
        proc.wait()
        proc.stdout.close()


def frame_at(path, info: dict, time_s: float, width: int = 640):
    """One picture at a time, or None past the end."""
    time_s = min(max(0.0, time_s), max(0.0, info["duration"] - 0.1))
    for _, picture in frames(path, info, 8, width, start=time_s, end=time_s + 0.5):
        return picture.copy()
    return None


def jpeg_bytes(picture, quality: int = 85) -> bytes:
    import cv2
    ok, data = cv2.imencode(".jpg", picture, [cv2.IMWRITE_JPEG_QUALITY, quality])
    if not ok:
        raise RuntimeError("Could not make a picture.")
    return data.tobytes()


def data_url(picture) -> str:
    """The picture as text, the way the AI engine receives images."""
    return "data:image/jpeg;base64," + base64.b64encode(jpeg_bytes(picture)).decode()


def shot_changes(path, info: dict, start: float = 0.0, end=None, fps: float = 4.0) -> list:
    """Times where the picture changes suddenly (a cut, a death screen, a menu)."""
    changes, previous = [], None
    for t, picture in frames(path, info, fps, 96, start, end, gray=True):
        current = picture.astype(np.int16)
        if previous is not None and np.abs(current - previous).mean() > 32:
            changes.append(round(t, 2))
        previous = current
    return changes
