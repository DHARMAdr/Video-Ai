"""
editor_extras.py - curve speed, masks, blend modes and match cut for the editor.

WHY it exists:
    These are the CapCut tools that need their own small piece of maths. Keeping them here
    keeps editor.py readable.

HOW it works:
    - Curve speed: the piece is cut into equal slices, each with its own constant speed taken
      from the curve, and the slices are joined again. (12 slices look smooth in practice.)
    - Mask: a grey picture (white = keep, black = hide, soft edge = "feather") that is
      multiplied with the layer's see-through values.
    - Blend mode: the layer is first drawn on a "neutral" colour that the mode ignores, then
      ffmpeg blends that with the video underneath.
    - Match cut: looks for the two moments (end of one piece, start of the next) whose pictures
      are most alike, so the cut feels continuous.

HOW TO IMPROVE: let you draw your own speed curve and mask shape.
"""

import subprocess
from pathlib import Path

import numpy as np

# Speed at equal steps through the piece. Names follow what editing apps usually call them.
CURVES = {
    "montage": (1.0, 2.0, 2.5, 1.2, 0.5, 0.4, 0.4, 0.5, 1.2, 2.5, 2.0, 1.0),
    "hero": (3.0, 3.0, 2.0, 1.0, 0.4, 0.3, 0.3, 0.4, 1.0, 2.0, 3.0, 3.0),
    "bullet": (2.0, 2.0, 2.0, 2.0, 0.3, 0.25, 0.25, 0.3, 2.0, 2.0, 2.0, 2.0),
    "jump cut": (1.0, 1.0, 1.0, 3.5, 3.5, 1.0, 1.0, 1.0, 3.5, 3.5, 1.0, 1.0),
    "flash in": (4.0, 3.5, 3.0, 2.5, 2.0, 1.6, 1.3, 1.1, 1.0, 1.0, 1.0, 1.0),
    "flash out": (1.0, 1.0, 1.0, 1.0, 1.1, 1.3, 1.6, 2.0, 2.5, 3.0, 3.5, 4.0),
}
MASKS = ("none", "circle", "rectangle", "rounded", "split", "band", "heart", "star")
# name -> (ffmpeg blend mode, neutral colour, which input goes first)
BLENDS = {
    "normal": None,
    "screen": ("screen", "black", "layer"),
    "add": ("addition", "black", "layer"),
    "lighten": ("lighten", "black", "layer"),
    "difference": ("difference", "black", "layer"),
    "multiply": ("multiply", "white", "layer"),
    "darken": ("darken", "white", "layer"),
    "overlay": ("overlay", "0x808080", "base"),
    "soft light": ("softlight", "0x808080", "base"),
}


def curve_factor(name: str) -> float:
    """Output length = source length x this."""
    speeds = CURVES.get(name)
    return sum(1.0 / s for s in speeds) / len(speeds) if speeds else 1.0


def _tempo(speed: float) -> str:
    steps = []
    while speed < 0.5:
        steps.append("atempo=0.5")
        speed /= 0.5
    while speed > 2.0:
        steps.append("atempo=2.0")
        speed /= 2.0
    return ",".join(steps + [f"atempo={speed:.4f}"])


def curve_graph(name: str, length: float, has_audio: bool, fps: int) -> str:
    """Filter graph that turns input 0 (a piece `length` seconds long) into [v] (and [a])."""
    speeds = CURVES[name]
    n, step = len(speeds), length / len(speeds)
    graph = [f"[0:v]setpts=PTS-STARTPTS,split={n}" + "".join(f"[s{i}]" for i in range(n))]
    if has_audio:
        graph.append(f"[0:a]asetpts=PTS-STARTPTS,asplit={n}" + "".join(f"[t{i}]" for i in range(n)))
    pads = ""
    for i, speed in enumerate(speeds):
        span = f"start={i * step:.4f}:end={(i + 1) * step:.4f}"
        graph.append(f"[s{i}]trim={span},setpts=(PTS-STARTPTS)/{speed}[v{i}]")
        pads += f"[v{i}]"
        if has_audio:
            graph.append(f"[t{i}]atrim={span},asetpts=PTS-STARTPTS,{_tempo(speed)}[a{i}]")
            pads += f"[a{i}]"
    graph.append(f"{pads}concat=n={n}:v=1:a={int(has_audio)}[vj]" + ("[a]" if has_audio else ""))
    graph.append(f"[vj]fps={fps}[v]")
    return ";".join(graph)


# ---------------------------------------------------------------------------
# Masks
# ---------------------------------------------------------------------------
def clean_mask(raw, number) -> dict:
    """A safe mask description, or None. x, y, size and height are shares of the picture."""
    if not isinstance(raw, dict) or raw.get("shape") not in MASKS[1:]:
        return None
    return {"shape": raw["shape"], "x": number(raw.get("x"), 0.5, 0.0, 1.0),
            "y": number(raw.get("y"), 0.5, 0.0, 1.0),
            "size": number(raw.get("size"), 0.6, 0.05, 2.0),
            "height": number(raw.get("height"), 0.6, 0.05, 2.0),
            "feather": number(raw.get("feather"), 0.05, 0.0, 0.5),
            "invert": bool(raw.get("invert"))}


def draw_mask(width: int, height: int, mask: dict, path: Path) -> None:
    """Save the mask as a grey PNG."""
    import cv2
    picture = np.zeros((height, width), np.uint8)
    cx, cy = mask["x"] * width, mask["y"] * height
    half_w, half_h = mask["size"] * width / 2, mask["height"] * height / 2
    short = min(width, height)
    centre = (int(cx), int(cy))
    shape = mask["shape"]

    def box(w, h):
        cv2.rectangle(picture, (int(cx - w), int(cy - h)), (int(cx + w), int(cy + h)), 255, -1)

    if shape == "circle":
        cv2.circle(picture, centre, max(1, int(mask["size"] * short / 2)), 255, -1, cv2.LINE_AA)
    elif shape == "rectangle":
        box(half_w, half_h)
    elif shape == "rounded":
        r = int(min(half_w, half_h) * 0.35)
        box(half_w - r, half_h)
        box(half_w, half_h - r)
        for sx in (-1, 1):
            for sy in (-1, 1):
                cv2.circle(picture, (int(cx + sx * (half_w - r)), int(cy + sy * (half_h - r))),
                           r, 255, -1, cv2.LINE_AA)
    elif shape == "split":                       # everything above the line
        picture[:max(0, int(cy))] = 255
    elif shape == "band":                        # a horizontal strip
        picture[max(0, int(cy - half_h)):max(0, int(cy + half_h))] = 255
    elif shape in ("heart", "star"):
        r = mask["size"] * short / 2
        if shape == "heart":                     # the classic heart curve
            t = np.linspace(0, 2 * np.pi, 120)
            xs = 16 * np.sin(t) ** 3
            ys = -(13 * np.cos(t) - 5 * np.cos(2 * t) - 2 * np.cos(3 * t) - np.cos(4 * t))
            points = np.stack([cx + xs * r / 16, cy + ys * r / 16], axis=1)
        else:
            angle = np.arange(10) * np.pi / 5 - np.pi / 2
            radius = np.where(np.arange(10) % 2 == 0, r, r * 0.45)
            points = np.stack([cx + radius * np.cos(angle), cy + radius * np.sin(angle)], axis=1)
        cv2.fillPoly(picture, [points.astype(np.int32)], 255, cv2.LINE_AA)
    if mask["feather"] > 0:
        picture = cv2.GaussianBlur(picture, (0, 0), max(0.5, mask["feather"] * short / 2))
    if mask["invert"]:
        picture = 255 - picture
    ok, data = cv2.imencode(".png", picture)
    if not ok:
        raise RuntimeError("Could not draw the mask.")
    Path(path).write_bytes(data.tobytes())


def blend_graph(mode: str, base: str, layer: str, n: int, width: int, height: int,
                total: float, where: str) -> tuple:
    """Filter parts that blend `layer` onto `base`. Returns (parts, result stream name).

    `where` is the overlay position/timing text (the same one a normal layer would use).
    """
    ffmode, neutral, first = BLENDS[mode]
    parts = [f"color=c={neutral}:s={width}x{height}:r=30:d={total:.3f},format=rgba[nc{n}]",
             f"[nc{n}][{layer}]overlay={where}:format=rgb,format=gbrp[nl{n}]",
             f"[{base}]format=gbrp[bb{n}]"]
    order = f"[nl{n}][bb{n}]" if first == "layer" else f"[bb{n}][nl{n}]"
    parts.append(f"{order}blend=all_mode={ffmode}:shortest=0:repeatlast=1,format=yuv420p[base{n}]")
    return parts, f"base{n}"


# ---------------------------------------------------------------------------
# Match cut
# ---------------------------------------------------------------------------
def _looks(video, start: float, duration: float, fps: int = 10) -> list:
    """[(time, description)] of the pictures in a short window: brightness shapes + edges."""
    import cv2
    w, h = 64, 36
    done = subprocess.run(
        ["ffmpeg", "-v", "error", "-nostdin", "-ss", f"{start:.3f}", "-t", f"{duration:.3f}",
         "-i", str(video), "-an", "-vf", f"fps={fps},scale={w}:{h}", "-f", "rawvideo",
         "-pix_fmt", "gray", "-"], capture_output=True)
    out = []
    for i in range(len(done.stdout) // (w * h)):
        grey = np.frombuffer(done.stdout, np.uint8, w * h, i * w * h).reshape(h, w).astype(np.float32)
        edges = np.hypot(cv2.Sobel(grey, cv2.CV_32F, 1, 0), cv2.Sobel(grey, cv2.CV_32F, 0, 1))
        parts = []
        for part in (grey, edges):
            part = part - part.mean()
            parts.append(part.ravel() / (np.linalg.norm(part) or 1.0))
        out.append((start + i / fps, np.concatenate(parts) / np.sqrt(2)))
    return out


def match_cut(first: dict, second: dict, window: float = 1.5) -> dict:
    """Best new end for `first` and new start for `second` (dicts with source, start, end).

    Returns {"end", "start", "likeness"}; likeness 1.0 means identical pictures.
    """
    def edge(piece, at_end):
        low, high = piece["start"] + 0.3, piece["end"] - 0.3
        if at_end:
            return max(low, piece["end"] - window), piece["end"] + 0.05
        return piece["start"], min(max(piece["start"] + 0.1, high), piece["start"] + window)

    a0, a1 = edge(first, True)
    b0, b1 = edge(second, False)
    ends = _looks(first["source"], a0, max(0.2, a1 - a0))
    starts = _looks(second["source"], b0, max(0.2, b1 - b0))
    if not ends or not starts:
        raise ValueError("Those pieces are too short for a match cut.")
    best = max(((float(a @ b), ta, tb) for ta, a in ends for tb, b in starts),
               key=lambda item: item[0])
    return {"likeness": round(best[0], 3), "end": round(min(best[1] + 0.1, first["end"]), 3),
            "start": round(best[2], 3)}


def curve_time(name: str, t: float, length: float) -> float:
    """Where the source moment t (0..length) ends up after the speed curve."""
    speeds = CURVES.get(name)
    if not speeds or length <= 0:
        return t
    step, out = length / len(speeds), 0.0
    for i, speed in enumerate(speeds):
        out += max(0.0, min(step, t - i * step)) / speed
    return out
