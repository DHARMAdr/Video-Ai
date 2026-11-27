"""
tracking.py - follows a thing in a video (motion tracking).

WHY it exists:
    To keep a sticker, arrow or picture stuck to a moving head, car or icon, or to keep a
    zoomed view centred on it.

HOW it works (classic computer vision, no model needed):
    1. Inside the box you chose, pick sharp corner points ("good features").
    2. In the next frame, find where each point moved (Lucas-Kanade optical flow), and check
       by flowing it back: a point that does not return to where it came from is dropped.
    3. The box moves by the middle value (median) of the point movements, and grows or shrinks
       as the points spread apart or together.
    4. If too few points survive, search for the picture of the box nearby
       (template matching). If that is not good enough either, the target is "lost" and the
       box stays still.

HONEST LIMITS: a target that turns around, is hidden for long, or leaves the screen is lost.
HOW TO IMPROVE: a learned tracker; let you correct the box half way and continue.
"""

import subprocess

import numpy as np

from . import ingest

TRACK_FPS = 15
TRACK_WIDTH = 960              # frames are shrunk to this width: faster and steadier
MAX_SECONDS = 60
MIN_POINTS = 6


def frames(video, start: float, duration: float, width: int, height: int):
    """Grey frames of a piece of a video."""
    proc = subprocess.Popen(
        ["ffmpeg", "-v", "error", "-nostdin", "-ss", f"{start:.3f}", "-t", f"{duration:.3f}",
         "-i", str(video), "-an", "-vf", f"fps={TRACK_FPS},scale={width}:{height}",
         "-f", "rawvideo", "-pix_fmt", "gray", "-"], stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL)
    try:
        while True:
            raw = proc.stdout.read(width * height)
            if len(raw) < width * height:
                break
            yield np.frombuffer(raw, np.uint8).reshape(height, width)
    finally:
        proc.kill()
        proc.wait()
        proc.stdout.close()


def _corners(gray, box):
    import cv2
    x, y, w, h = [int(round(v)) for v in box]
    mask = np.zeros(gray.shape, np.uint8)
    mask[max(0, y):max(0, y + h), max(0, x):max(0, x + w)] = 255
    return cv2.goodFeaturesToTrack(gray, 80, 0.01, 4, mask=mask)


def _flow(old, new, points):
    """Move points from `old` to `new`; keep only those that also flow back correctly."""
    import cv2
    options = {"winSize": (21, 21), "maxLevel": 3}
    moved, ok, _ = cv2.calcOpticalFlowPyrLK(old, new, points, None, **options)
    back, ok_back, _ = cv2.calcOpticalFlowPyrLK(new, old, moved, None, **options)
    drift = np.linalg.norm((points - back).reshape(-1, 2), axis=1)
    good = (ok.ravel() == 1) & (ok_back.ravel() == 1) & (drift < 1.5)
    return points.reshape(-1, 2)[good], moved.reshape(-1, 2)[good]


def _search(gray, picture, box):
    """Look for the remembered picture near the last place. Returns (x, y) or None."""
    import cv2
    x, y, w, h = [int(round(v)) for v in box]
    x0, y0 = max(0, x - w), max(0, y - h)
    area = gray[y0:y + 2 * h, x0:x + 2 * w]
    if area.shape[0] < picture.shape[0] or area.shape[1] < picture.shape[1]:
        return None
    score = np.nan_to_num(cv2.matchTemplate(area, picture, cv2.TM_CCOEFF_NORMED))
    _, best, _, (bx, by) = cv2.minMaxLoc(score)
    return (x0 + bx, y0 + by) if best >= 0.6 else None


def follow_frames(grays, box):
    """box = (x, y, w, h) in pixels of the first frame.

    Returns [(x, y, w, h, found)] with one entry per frame.
    """
    grays = iter(grays)
    old = next(grays, None)
    if old is None:
        raise ValueError("Could not read the video there.")
    box = np.array(box, np.float32)
    x, y, w, h = [int(round(v)) for v in box]
    picture = old[max(0, y):y + h, max(0, x):x + w].copy()
    if picture.shape[0] < 8 or picture.shape[1] < 8 or float(picture.std()) < 6:
        raise ValueError("There is nothing clear to follow there. Put the box on a sharp detail.")
    points = _corners(old, box)
    path = [(*box.tolist(), True)]
    for new in grays:
        found = False
        if points is not None and len(points) >= MIN_POINTS:
            start, end = _flow(old, new, points)
            if len(end) >= MIN_POINTS:
                shift = np.median(end - start, axis=0)
                # Growth: how far the points are from their middle, now against before.
                before = np.linalg.norm(start - np.median(start, axis=0), axis=1)
                after = np.linalg.norm(end - np.median(end, axis=0), axis=1)
                wide = before > 3
                grow = float(np.median(after[wide] / before[wide])) if wide.sum() >= 4 else 1.0
                grow = min(1.05, max(0.95, grow))
                centre = box[:2] + box[2:] / 2 + shift
                size = box[2:] * grow
                box = np.concatenate([centre - size / 2, size])
                points, found = end.reshape(-1, 1, 2).astype(np.float32), True
        if not found:
            place = _search(new, picture, box)
            if place:
                box = np.array([place[0], place[1], picture.shape[1], picture.shape[0]], np.float32)
                found, points = True, None
        inside = 0 <= box[0] + box[2] / 2 < new.shape[1] and 0 <= box[1] + box[3] / 2 < new.shape[0]
        found = found and inside
        if found and (points is None or len(points) < 25):
            points = _corners(new, box)            # points get lost over time: pick new ones
        path.append((*box.tolist(), bool(found)))
        old = new
    return path


def track(video, start: float, end: float, box) -> dict:
    """box = (x, y, w, h) as fractions (0..1) of the video frame, at time `start`.

    Returns {"points": [{"t", "x", "y", "scale"}], "found": share of frames still on target}.
    x and y are the middle of the box as fractions; scale is its size against the start.
    """
    if end - start < 0.2:
        raise ValueError("Choose a longer part to follow.")
    end = min(end, start + MAX_SECONDS)
    info = ingest.probe(video)
    width = min(TRACK_WIDTH, info["width"]) // 2 * 2
    height = int(info["height"] * width / info["width"]) // 2 * 2
    x, y, w, h = [float(v) for v in box]
    w, h = min(max(w, 0.02), 1.0), min(max(h, 0.02), 1.0)
    pixels = (min(max(x, 0.0), 1 - w) * width, min(max(y, 0.0), 1 - h) * height,
              w * width, h * height)
    path = follow_frames(frames(video, start, end - start, width, height), pixels)
    points = [{"t": round(i / TRACK_FPS, 3), "x": (bx + bw / 2) / width,
               "y": (by + bh / 2) / height, "scale": bw / pixels[2]}
              for i, (bx, by, bw, bh, _) in enumerate(path)]
    return {"points": points, "found": sum(p[4] for p in path) / len(path)}


def simplify(points: list, limit: int, keys=("x", "y", "scale"), tolerance: float = 0.004) -> list:
    """Keep only the points needed to draw the same path with straight lines.

    Repeatedly adds the point that the straight lines get most wrong.
    """
    if len(points) <= 2:
        return list(points)
    kept = {0, len(points) - 1}
    while len(kept) < limit:
        order = sorted(kept)
        worst, where = tolerance, None
        for a, b in zip(order, order[1:]):
            span = points[b]["t"] - points[a]["t"] or 1e-6
            for i in range(a + 1, b):
                share = (points[i]["t"] - points[a]["t"]) / span
                error = max(abs(points[i][k] - points[a][k] -
                                (points[b][k] - points[a][k]) * share) for k in keys)
                if error > worst:
                    worst, where = error, i
        if where is None:
            break
        kept.add(where)
    return [points[i] for i in sorted(kept)]
