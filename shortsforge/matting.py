"""
matting.py - removes the background behind a person, with no green screen.

WHY it exists:
    CapCut can cut a person out of an ordinary video. This does the same on your own PC.

HOW it works:
    1. A small neural network (PP-HumanSeg from the OpenCV model zoo, Apache 2.0, 6 MB) looks
       at each frame and says, for every pixel, how likely it is part of a person.
    2. That likelihood picture (the "matte") is sharpened and smoothed over time, so the edge
       does not flicker.
    3. The person is placed over the new background: see-through (for layers), blurred, or a
       plain colour.

HONEST LIMITS:
    - The model was made for people near the camera (talking, streaming). Small or far people,
      hands holding things, and hair edges are less accurate. It only knows PEOPLE.
    - It runs on the processor: roughly 10 to 30 frames per second.

HOW TO IMPROVE:
    - A bigger matting model (for example MODNet) for cleaner hair.
    - Run it on the graphics card.
"""

import subprocess
from pathlib import Path

import numpy as np

from . import ingest, paths

MODEL_NAME = "pphumanseg.onnx"
SIDE = 192                      # the model looks at 192 x 192 pictures
SMOOTH = 0.35                   # how much of the previous matte is kept (stops flicker)
BACKGROUNDS = ("blur", "black", "white", "green", "transparent")
COLOURS = {"black": (0, 0, 0), "white": (255, 255, 255), "green": (0, 255, 0)}
MAX_SECONDS = 180
_net = None


def available() -> bool:
    return paths.model_file(MODEL_NAME) is not None


def _load():
    global _net
    if _net is None:
        import cv2
        found = paths.model_file(MODEL_NAME)
        if found is None:
            raise ValueError("The background-removal model is missing. Install the newest app.")
        # Reading the bytes ourselves also works with non-English folder names on Windows.
        _net = cv2.dnn.readNetFromONNX(np.fromfile(str(found), np.uint8))
    return _net


def matte(rgb: np.ndarray) -> np.ndarray:
    """0..1 "is a person" value for every pixel of an RGB picture."""
    import cv2
    net = _load()
    small = cv2.resize(rgb, (SIDE, SIDE), interpolation=cv2.INTER_AREA).astype(np.float32)
    net.setInput(((small / 255.0 - 0.5) / 0.5).transpose(2, 0, 1)[None])
    out = net.forward()[0]                      # two maps: background, person
    if out.min() < 0 or out.max() > 1:          # raw scores: turn them into likelihoods
        out = np.exp(out - out.max(axis=0))
        out /= out.sum(axis=0)
    full = cv2.resize(out[1], (rgb.shape[1], rgb.shape[0]), interpolation=cv2.INTER_LINEAR)
    # Push unsure values towards 0 or 1: firmer edges, less see-through haze.
    return np.clip((full - 0.2) / 0.6, 0.0, 1.0)


def compose(rgb: np.ndarray, alpha: np.ndarray, background: str) -> np.ndarray:
    """The new frame (RGBA when background is "transparent", otherwise RGB)."""
    import cv2
    if background == "transparent":
        return np.dstack([rgb, (alpha * 255).astype(np.uint8)])
    if background == "blur":
        h, w = rgb.shape[:2]
        tiny = cv2.resize(rgb, (max(8, w // 8), max(8, h // 8)), interpolation=cv2.INTER_AREA)
        behind = cv2.resize(cv2.GaussianBlur(tiny, (0, 0), 3), (w, h))
    else:
        behind = np.full_like(rgb, COLOURS[background])
    a = alpha[..., None]
    return (rgb * a + behind * (1 - a) + 0.5).astype(np.uint8)


def process(source, start: float, duration: float, out: Path, background: str,
            fps: int = 30, log=print) -> Path:
    """Write a copy of [start, start+duration] with the background replaced.

    out should end in .mkv. The sound is copied along.
    """
    if background not in BACKGROUNDS:
        raise ValueError("Unknown background.")
    if duration > MAX_SECONDS:
        raise ValueError("Background removal works on pieces up to 3 minutes.")
    _load()
    info = ingest.probe(Path(source))
    scale = min(1.0, 1920 / max(info["width"], info["height"]))
    w, h = int(info["width"] * scale) // 2 * 2, int(info["height"] * scale) // 2 * 2
    still = Path(source).suffix.lower() in (".png", ".jpg", ".jpeg", ".webp", ".bmp")
    head = (["-loop", "1", "-framerate", str(fps)] if still else ["-ss", f"{start:.3f}"])
    head += ["-t", f"{duration:.3f}", "-i", str(source)]
    reader = subprocess.Popen(
        ["ffmpeg", "-v", "error", "-nostdin", *head, "-an", "-vf",
         f"fps={fps},scale={w}:{h}", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    clear = background == "transparent"
    sound = not still and info["has_audio"]
    command = ["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt",
               "rgba" if clear else "rgb24", "-s", f"{w}x{h}", "-r", str(fps), "-i", "-"]
    if sound:
        command += ["-ss", f"{start:.3f}", "-t", f"{duration:.3f}", "-i", str(source),
                    "-map", "0:v", "-map", "1:a:0", "-c:a", "pcm_s16le"]
    # "transparent" needs a format that stores see-through pixels without loss.
    command += (["-c:v", "ffv1", "-pix_fmt", "yuva420p"] if clear else
                ["-c:v", "libx264", "-preset", "veryfast", "-crf", "12", "-pix_fmt", "yuv420p"])
    writer = subprocess.Popen(command + [str(out)], stdin=subprocess.PIPE,
                              stderr=subprocess.DEVNULL)
    size, previous, count = w * h * 3, None, 0
    try:
        while True:
            raw = reader.stdout.read(size)
            if len(raw) < size:
                break
            rgb = np.frombuffer(raw, np.uint8).reshape(h, w, 3)
            alpha = matte(rgb)
            if previous is not None:
                alpha = alpha * (1 - SMOOTH) + previous * SMOOTH
            previous = alpha
            writer.stdin.write(compose(rgb, alpha, background).tobytes())
            count += 1
            if count % (fps * 5) == 0:
                log(f"Removing the background: {count // fps} seconds done ...")
    finally:
        reader.kill()
        reader.wait()
        reader.stdout.close()
        writer.stdin.close()
        writer.wait()
    if not count or writer.returncode != 0:
        raise RuntimeError("Background removal could not read or write the video.")
    return out
