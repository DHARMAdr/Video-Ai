"""
teach.py - "learn from MY video": makes kill detection fit your own recordings.

WHY it exists:
    Every recording is a bit different (HUD scale, colours, resolution, game updates). Instead of
    one fixed guess, you show the app an example video:
        1. optionally draw a box around the kill-feed area,
        2. optionally draw a box around YOUR NAME in one kill-feed line,
        3. mark a few moments where you really got a kill.
    The app then tries several ways of detecting and keeps the one that finds your marked kills,
    and TELLS YOU how many it found, so you know whether it will work.

HOW it works:
    - Everything is saved in Documents/ShortsForge/_teach/ (valorant.json + valorant_name.png).
    - learn(): only reads short pieces around your marks (fast). Each candidate method gets
      score = marked kills found - half a point for every extra detection.
    - apply(): pipeline.run_game() adds the learned settings to the game profile.

HONEST LIMITS:
    - With only 1-2 marks the choice can be luck. Mark 4 or more different kills.
    - It learns where and how to look. It is not a trained neural network.

HOW TO IMPROVE:
    - Learn the sound of your kill confirmation as a second, independent clue.
    - Keep one teaching per resolution, or per game.
"""

import hashlib
import json
from pathlib import Path

from . import ingest, killfeed, namefeed
from .config import load_game_profile
from .imgio import write_png

VICTIM_GAP = 120                       # pixels at 1080p; closer to the right edge = you died
BEFORE, AFTER = 4.0, 3.0               # seconds read around each marked kill
EARLY, LATE = 1.5, 2.0                 # a detection this close to a mark counts as found

# Other ways your kills may be painted. learn() tries each one on YOUR marks.
COLOUR_METHODS = {
    "red bar": {"style": "fill", "highlight": {"hue_ranges": [[340, 360], [0, 20]],
                                               "min_saturation": 0.40, "min_value": 0.40}},
    "yellow outline": {"style": "border", "highlight": {"hue_ranges": [[35, 72]],
                                                        "min_saturation": 0.25, "min_value": 0.65}},
    "yellow bar": {"style": "fill", "highlight": {"hue_ranges": [[35, 72]],
                                                  "min_saturation": 0.35, "min_value": 0.55}},
    "green bar": {"style": "fill", "highlight": {"hue_ranges": [[130, 185]],
                                                 "min_saturation": 0.30, "min_value": 0.35}},
}


def folder(root) -> Path:
    return Path(root) / "_teach"


def load(root, game: str = "valorant") -> dict:
    """What has been taught so far ({} when nothing)."""
    try:
        data = json.loads((folder(root) / f"{game}.json").read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save(root, data: dict, game: str) -> None:
    folder(root).mkdir(parents=True, exist_ok=True)
    (folder(root) / f"{game}.json").write_text(json.dumps(data, indent=1), encoding="utf-8")


def reset(root, game: str = "valorant") -> None:
    """Forget everything that was taught."""
    for name in (f"{game}.json", f"{game}_name.png"):
        (folder(root) / name).unlink(missing_ok=True)


def _box(values) -> list:
    """Check a box [x0, y0, x1, y1] given as fractions of the picture."""
    try:
        x0, y0, x1, y1 = [min(1.0, max(0.0, float(v))) for v in values]
    except (TypeError, ValueError):
        raise ValueError("Draw the box again.")
    if x1 - x0 < 0.005 or y1 - y0 < 0.005:
        raise ValueError("The box is too small. Drag a bigger one.")
    return [round(v, 4) for v in (x0, y0, x1, y1)]


def save_area(root, roi, game: str = "valorant") -> dict:
    """Remember where the kill feed is."""
    data = load(root, game)
    data["roi"] = _box(roi)
    _save(root, data, game)
    return data


def save_name(root, video, time_s: float, box, game: str = "valorant") -> dict:
    """Cut your name out of one frame and remember it."""
    box = _box(box)
    info = ingest.probe(Path(video))
    data = load(root, game)
    roi = data.get("roi") or load_game_profile(game)["roi"]
    if box[0] < roi[0] or box[1] < roi[1] or box[2] > roi[2] or box[3] > roi[3]:
        # The name is outside the current kill-feed area: widen the area to include it.
        roi = [max(0.0, min(roi[0], box[0] - 0.02)), max(0.0, min(roi[1], box[1] - 0.02)),
               min(1.0, max(roi[2], box[2] + 0.02)), min(1.0, max(roi[3], box[3] + 0.1))]
    geometry = namefeed.ref_geometry(info, roi)
    picture = next(iter(namefeed.scan(video, info, roi, 8, start=max(0.0, float(time_s)),
                                      duration=1.0)), None)
    if picture is None:
        raise ValueError("Could not read a picture at that time.")
    k = namefeed.REF_HEIGHT / info["height"]
    x0 = max(0, int(round(box[0] * info["width"] * k - geometry["x0"])))
    y0 = max(0, int(round(box[1] * info["height"] * k - geometry["y0"])))
    x1 = int(round(box[2] * info["width"] * k - geometry["x0"]))
    y1 = int(round(box[3] * info["height"] * k - geometry["y0"]))
    crop = picture[y0:y1, x0:x1]
    if crop.shape[0] < 8 or crop.shape[1] < 16:
        raise ValueError("The name box is too small. Drag it around your whole name.")
    if float(crop.std()) < 8:
        raise ValueError("That box has no visible text. Pick a moment where your name is shown.")
    folder(root).mkdir(parents=True, exist_ok=True)
    path = folder(root) / f"{game}_name.png"
    write_png(path, crop)
    data.update({"roi": [round(v, 4) for v in roi], "method": "name", "name": True,
                 "name_id": hashlib.md5(crop.tobytes()).hexdigest()[:10],
                 "name_threshold": 0.70, "victim_gap": VICTIM_GAP})
    data.pop("report", None)
    _save(root, data, game)
    return data


def apply(root, gp: dict, game: str = "valorant") -> dict:
    """The game profile with the learned settings written over it."""
    data, out = load(root, game), dict(gp)
    if data.get("roi"):
        out["roi"] = data["roi"]
    method = data.get("method")
    if method == "name" and (folder(root) / f"{game}_name.png").exists():
        out.update({"method": "name", "name_template": str(folder(root) / f"{game}_name.png"),
                    "name_template_id": data.get("name_id"),
                    "name_threshold": data.get("name_threshold", 0.70),
                    "victim_gap": data.get("victim_gap", VICTIM_GAP)})
    elif method in COLOUR_METHODS:
        out.update({"method": "colour", **COLOUR_METHODS[method]})
    return out


def describe(root, game: str = "valorant") -> dict:
    """Short summary for the window and the assistant."""
    data = load(root, game)
    return {"taught": bool(data), "area": data.get("roi"), "name": bool(data.get("name")),
            "method": data.get("method") or "built-in red bar rule",
            "report": data.get("report")}


def match_marks(found: list, marks: list) -> tuple:
    """(how many marks were found, how many detections matched no mark)."""
    left, hits = list(found), 0
    for mark in sorted(marks):
        near = [t for t in left if mark - EARLY <= t <= mark + LATE]
        if near:
            left.remove(min(near, key=lambda t: abs(t - mark)))
            hits += 1
    return hits, len(left)


def _kills_in_window(counts, fps: float, start: float, window: int) -> list:
    """Kills inside one short piece. Lines already on screen at its start are not new kills."""
    smooth = killfeed.smooth_counts(counts, window)
    if len(smooth) == 0:
        return []
    times, previous = [], int(smooth[0])
    for i, count in enumerate(smooth):
        times.extend([start + i / fps] * max(0, int(count) - previous))
        previous = int(count)
    return times


def learn(root, video, marks: list, game: str = "valorant", log=print) -> dict:
    """Try every method on the marked kills, keep the best and report how good it is."""
    marks = sorted(float(m) for m in marks)[:20]
    if not marks:
        raise ValueError("Mark at least one moment where you got a kill (4 or more is better).")
    info = ingest.probe(Path(video))
    base = load_game_profile(game)
    data = load(root, game)
    if data.get("roi"):
        base["roi"] = data["roi"]

    # Joined time windows around the marks (so two close kills are not read twice).
    windows = []
    for mark in marks:
        lo, hi = max(0.0, mark - BEFORE), min(info["duration"], mark + AFTER)
        if windows and lo <= windows[-1][1]:
            windows[-1][1] = max(windows[-1][1], hi)
        else:
            windows.append([lo, hi])

    results = {}

    def score(label, found, extra=None):
        hits, extras = match_marks(found, marks)
        results[label] = {"hits": hits, "extra": extras, "settings": extra or {}}
        log(f"  {label}: found {hits} of {len(marks)} marked kills, {extras} extra")

    log("Trying the colour rules ...")
    colour_frames = [(lo, list(killfeed.scan_frames(video, info, base, start=lo, duration=hi - lo)))
                     for lo, hi in windows]
    row_h = killfeed.row_height_scaled(info, base)
    for label, change in COLOUR_METHODS.items():
        gp = {**base, **change}
        found = []
        for lo, frames in colour_frames:
            counts = [min(sum(b[2] for b in killfeed.rows_in_frame(f, gp, row_h)), gp["max_rows"])
                      for f in frames]
            found += _kills_in_window(counts, gp["scan_fps"], lo, gp["smooth_window"])
        score(label, found)

    template_file = folder(root) / f"{game}_name.png"
    if data.get("name") and template_file.exists():
        log("Trying your name ...")
        template = namefeed.load_template(template_file)
        geometry = namefeed.ref_geometry(info, base["roi"])
        frames = [(lo, list(namefeed.scan(video, info, base["roi"], 4, start=lo, duration=hi - lo)))
                  for lo, hi in windows]
        for threshold in (0.62, 0.70, 0.80):
            for gap in (VICTIM_GAP, 0):
                gp = {"name_threshold": threshold, "victim_gap": gap}
                found = []
                for lo, piece in frames:
                    # Lines already on screen when the piece starts are not new kills.
                    found += [t for t in namefeed.line_times(piece, template, gp, geometry, 4, lo)
                              if t > lo + 0.01]
                label = f"name {threshold:.2f}" + ("" if gap else " (no death filter)")
                score(label, found, gp)

    # Best = most marks found, then fewest extras. Names win ties (they cannot be a colour fluke).
    def rank(item):
        label, r = item
        return (r["hits"] - 0.5 * r["extra"], r["hits"], label.startswith("name"),
                r["settings"].get("victim_gap", 0) > 0, -abs(r["settings"].get("name_threshold", 0.7) - 0.7))

    label, best = max(results.items(), key=rank)
    if best["hits"] == 0:
        message = ("None of the methods found your marked kills. Check that the box around the "
                   "kill feed is right, and draw a box around your name in a kill-feed line.")
        data["report"] = {"ok": False, "marks": len(marks), "hits": 0, "extra": 0,
                          "method": "", "message": message}
        _save(root, data, game)
        return data["report"]

    if label.startswith("name"):
        data.update({"method": "name", **best["settings"]})
    else:
        data["method"] = label
    message = f"Best method: {label}. It found {best['hits']} of your {len(marks)} marked kills"
    message += f" and {best['extra']} other moment(s) near them." if best["extra"] else "."
    if best["hits"] < len(marks) or best["extra"] > best["hits"]:
        message += " Not perfect: adding your name box or more marks may help."
    data["report"] = {"ok": True, "marks": len(marks), "hits": best["hits"],
                      "extra": best["extra"], "method": label, "message": message}
    _save(root, data, game)
    return data["report"]
