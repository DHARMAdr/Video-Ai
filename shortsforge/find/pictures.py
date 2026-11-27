"""
pictures.py - the example pictures YOU teach, and the code that finds them in a video.

WHY it exists:
    The app has no game artwork of its own. To recognise one character, weapon or screen you
    pause a video once, drag a box around it and give it a name. From then on you can type
    "kills on Jett" or "show me victory screen" and the app searches for that picture.

HOW it works:
    - Two kinds of picture:
        feed  : a small icon inside the kill feed (an agent face, a weapon, a headshot mark).
        scene : something anywhere on screen (a banner, a menu, a place on the map).
    - Everything is stored at a fixed size (video scaled to 1080 high), so one example works
      for 720p, 1080p and 1440p recordings of the same screen layout.
    - OpenCV "template matching" slides the example over a frame and scores each position from
      0 to 1. We try a few sizes, and a mirrored copy for feed icons.

HONEST LIMITS:
    - It finds pictures that LOOK THE SAME. A 3-D character seen from another side will not
      match; use the picture AI (vision.py) for that.

HOW TO IMPROVE:
    - Keep several examples per name (the search already accepts them: same name, new box).
"""

import json
import secrets
from pathlib import Path

import numpy as np

from .. import ingest
from . import video as videos

REF_HEIGHT = 1080
SCALES = (1.0, 0.92, 1.08)
THRESHOLDS = {"feed": 0.74, "scene": 0.72}
MAX_PICTURES = 200


def folder(root) -> Path:
    return Path(root) / "_find"


def load_all(root) -> list:
    """The saved examples (an empty list if there are none or the file is damaged)."""
    try:
        data = json.loads((folder(root) / "pictures.json").read_text(encoding="utf-8"))
        return [p for p in data if (folder(root) / p["file"]).is_file()]
    except (OSError, ValueError, KeyError, TypeError):
        return []


def _save_all(root, items: list) -> None:
    folder(root).mkdir(parents=True, exist_ok=True)
    (folder(root) / "pictures.json").write_text(json.dumps(items, indent=1), encoding="utf-8")


def names(root) -> list:
    return sorted({p["name"] for p in load_all(root)})


def full_width(info: dict) -> int:
    """Width of the video after scaling its height to 1080."""
    return int(round(info["width"] * REF_HEIGHT / info["height"])) // 2 * 2


def add(root, video, time_s: float, box, name: str, kind: str = "feed") -> dict:
    """Cut the box out of one frame and remember it under `name`."""
    from ..imgio import write_png
    name = " ".join(str(name or "").split())[:40]
    if not name:
        raise ValueError("Give the picture a name, for example Jett.")
    if kind not in THRESHOLDS:
        raise ValueError("Unknown picture type.")
    items = load_all(root)
    if len(items) >= MAX_PICTURES:
        raise ValueError("Too many pictures. Delete some first.")
    try:
        x0, y0, x1, y1 = [min(1.0, max(0.0, float(v))) for v in box]
    except (TypeError, ValueError):
        raise ValueError("Draw the box again.")
    info = ingest.probe(Path(video))
    width = full_width(info)
    big = {"width": width, "height": REF_HEIGHT, "duration": info["duration"]}
    w, h = videos.sized(big, width)
    picture = _frame_scaled(video, info, time_s, w, h)
    crop = picture[int(y0 * h):int(y1 * h), int(x0 * w):int(x1 * w)]
    if crop.size == 0 or crop.shape[0] < 12 or crop.shape[1] < 12:
        raise ValueError("The box is too small. Drag a bigger one.")
    if float(crop.std()) < 8:
        raise ValueError("That box is almost one plain colour. Pick something with detail.")
    item_id = secrets.token_hex(4)
    folder(root).mkdir(parents=True, exist_ok=True)
    write_png(folder(root) / f"{item_id}.png", crop[:, :, ::-1])       # file wants red first
    item = {"id": item_id, "name": name, "kind": kind, "file": f"{item_id}.png",
            "box": [round(v, 4) for v in (x0, y0, x1, y1)]}
    items.append(item)
    _save_all(root, items)
    return item


def _frame_scaled(video, info, time_s, w, h):
    """One BGR frame scaled to exactly w x h (also enlarges small videos)."""
    import cv2
    picture = videos.frame_at(video, info, float(time_s), width=info["width"])
    if picture is None:
        raise ValueError("Could not read a picture at that time.")
    return cv2.resize(picture, (w, h), interpolation=cv2.INTER_CUBIC)


def delete(root, item_id: str) -> None:
    items = load_all(root)
    keep = [p for p in items if p["id"] != item_id]
    if len(keep) == len(items):
        raise ValueError("That picture does not exist.")
    for gone in items:
        if gone["id"] == item_id:
            (folder(root) / gone["file"]).unlink(missing_ok=True)
    _save_all(root, keep)


def load_image(root, item: dict):
    """The example as a grey picture (works with non-English folder names)."""
    import cv2
    data = np.fromfile(str(folder(root) / item["file"]), dtype=np.uint8)
    image = cv2.imdecode(data, cv2.IMREAD_GRAYSCALE) if len(data) else None
    if image is None:
        raise ValueError(f"The picture '{item['name']}' is damaged. Delete it and add it again.")
    return image


def variants(image, mirrored: bool, shrink: float = 1.0) -> list:
    """The example at a few sizes (and mirrored), ready for matching."""
    import cv2
    out = []
    sources = [image, image[:, ::-1]] if mirrored else [image]
    for source in sources:
        for scale in SCALES:
            h, w = source.shape
            size = (max(8, int(round(w * scale * shrink))), max(8, int(round(h * scale * shrink))))
            out.append(np.ascontiguousarray(cv2.resize(source, size, interpolation=cv2.INTER_AREA)))
    return out


def matches(gray, templates: list, threshold: float, limit: int = 6) -> list:
    """Every place the example appears: [(x, y, width, height, score)], best first."""
    import cv2
    found = []
    for template in templates:
        th, tw = template.shape
        if gray.shape[0] < th or gray.shape[1] < tw:
            continue
        result = np.nan_to_num(cv2.matchTemplate(gray, template, cv2.TM_CCOEFF_NORMED),
                               nan=0.0, posinf=0.0, neginf=0.0)
        for _ in range(limit):
            _, best, _, (x, y) = cv2.minMaxLoc(result)
            if best < threshold:
                break
            found.append((x, y, tw, th, float(best)))
            result[max(0, y - th // 2): y + th // 2 + 1, max(0, x - tw // 2): x + tw // 2 + 1] = 0
    found.sort(key=lambda m: -m[4])
    keep = []
    for m in found:                                   # the same icon matched by two sizes
        if all(abs(m[0] - k[0]) > k[2] // 2 or abs(m[1] - k[1]) > k[3] // 2 for k in keep):
            keep.append(m)
    return keep[:limit]


def scan_scene(root, video, info: dict, name: str, start: float, end: float, fps: float = 2.0,
               log=print) -> list:
    """Hits (see moments.hit) where a 'scene' picture is visible."""
    from .moments import hit
    wanted = [p for p in load_all(root) if p["name"].lower() == name.lower() and p["kind"] == "scene"]
    if not wanted:
        return []
    shrink = 0.5                                     # half size is much faster and still accurate
    templates = [t for p in wanted for t in variants(load_image(root, p), False, shrink)]
    width = max(2, int(full_width(info) * shrink) // 2 * 2)
    log(f"Looking for your picture '{name}' ...")
    hits = []
    import cv2
    big = {"width": width, "height": int(REF_HEIGHT * shrink), "duration": info["duration"]}
    source_width = min(width, info["width"])
    for t, picture in videos.frames(video, info, fps, source_width, start, end, gray=True):
        if picture.shape[1] != width:
            picture = cv2.resize(picture, (big["width"], big["height"]))
        found = matches(picture, templates, THRESHOLDS["scene"], limit=1)
        if found:
            hits.append(hit(t, found[0][4], "picture", f"'{name}' is on screen"))
    return hits
