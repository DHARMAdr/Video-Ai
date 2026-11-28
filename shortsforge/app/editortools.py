"""
editortools.py - the editor's "do something for me" buttons: motion tracking, match cut,
compound clip and text to speech.

WHY it exists:
    These need the PC (they read or write video), and they translate between what you see on
    the preview and what is inside the source video.

HOW it works:
    - track(): the sticker you placed over something marks WHAT to follow. Its place on the
      preview is converted to a place inside the source video (undoing zoom, pan and crop),
      the thing is followed there, and the path is converted back into keyframes.
    - compound(): the chosen pieces are rendered into one new video file.

HOW TO IMPROVE: support rotated and mirrored pieces when tracking.
"""

import time
from pathlib import Path

from .. import editor, editor_extras, ingest, tracking, tts

MAX_KEYS = 50


def _piece_at(segments: list, moment: float, fade: float):
    """(piece, timeline time where it starts) shown at `moment` on the timeline."""
    start, found = 0.0, None
    for seg in segments:
        if moment >= start - 0.001:
            found = (seg, start)
        length = (seg["end"] - seg["start"]) / seg["speed"] * \
            editor_extras.curve_factor(seg["curve"])
        start += length - fade
    return found


def mapping(width: int, height: int, source_w: int, source_h: int, seg: dict, fit: str):
    """Two functions: canvas share -> source share, and back (plus the size ratio)."""
    zoom = seg["zoom"]
    crop_w, crop_h = source_w / zoom, source_h / zoom
    crop_x = (source_w - crop_w) * (seg["pan_x"] + 1) / 2
    crop_y = (source_h - crop_h) * (seg["pan_y"] + 1) / 2
    pick = max if fit == "crop" else min
    k = pick(width / crop_w, height / crop_h)
    off_x, off_y = (crop_w * k - width) / 2, (crop_h * k - height) / 2

    def to_source(x, y):
        return (crop_x + (x * width + off_x) / k) / source_w, \
            (crop_y + (y * height + off_y) / k) / source_h

    def to_canvas(x, y):
        return ((x * source_w - crop_x) * k - off_x) / width, \
            ((y * source_h - crop_y) * k - off_y) / height

    return to_source, to_canvas, k


def track(timeline: dict, number: int, log=print) -> dict:
    """Make overlay `number` follow what is under it. Returns its new keyframes."""
    plan = editor.clean(timeline)
    raw = timeline.get("overlays") or []
    if not 0 <= number < len(raw):
        raise ValueError("Select a sticker or picture first.")
    overlay = editor.layers.clean_overlays([raw[number]])[0]
    fade = plan["transition"]["seconds"] if plan["transition"]["type"] != "none" else 0.0
    found = _piece_at(plan["segments"], overlay["start"], fade)
    if not found:
        raise ValueError("There is no video under it at that time.")
    seg, piece_start = found
    if seg["reverse"] or seg["freeze"] or seg["curve"] or seg["rotate"] or seg["mirror"] \
            or seg["keyframes"]:
        raise ValueError("Tracking needs a plain piece: no reverse, still, curve speed, "
                         "rotate, mirror or zoom keyframes.")
    width, height = editor.SIZES[plan["aspect"]]
    info = ingest.probe(Path(seg["source"]))
    to_source, to_canvas, k = mapping(width, height, info["width"], info["height"], seg,
                                      plan["fit"])
    # The overlay's box on the canvas, as shares.
    box_w = overlay["scale"]
    if overlay["kind"] == "sticker":
        box_h = box_w * width / height
    else:
        shape = ingest.probe(Path(overlay["source"]))
        box_h = box_w * width * shape["height"] / shape["width"] / height
    x0, y0 = to_source(overlay["x"] - box_w / 2, overlay["y"] - box_h / 2)
    x1, y1 = to_source(overlay["x"] + box_w / 2, overlay["y"] + box_h / 2)
    start = seg["start"] + (overlay["start"] - piece_start) * seg["speed"]
    end = min(seg["end"], start + (overlay["end"] - overlay["start"]) * seg["speed"])
    log("Following the thing under your overlay ...")
    result = tracking.track(seg["source"], start, end, (x0, y0, x1 - x0, y1 - y0))
    points = []
    for p in result["points"]:
        x, y = to_canvas(p["x"], p["y"])
        points.append({"t": round(p["t"] / seg["speed"], 3), "x": round(x, 4), "y": round(y, 4),
                       "scale": round(min(3.0, max(0.03, overlay["scale"] * p["scale"])), 4)})
    return {"keyframes": tracking.simplify(points, MAX_KEYS), "found": round(result["found"], 2),
            "overlay": number}


def match_cut(timeline: dict, number: int) -> dict:
    """Better cut points between main piece `number` and the one after it."""
    pieces = timeline.get("segments") or []
    if not 0 <= number < len(pieces) - 1:
        raise ValueError("Select a video piece that has another piece after it.")
    plan = editor.clean({"segments": pieces[number:number + 2]})
    first, second = plan["segments"]
    if first["reverse"] or second["reverse"] or first["freeze"] or second["freeze"]:
        raise ValueError("Match cut does not work on reversed or still pieces.")
    return {**editor_extras.match_cut(first, second), "piece": number}


def compound(out_dir, timeline: dict, numbers: list, log=print) -> dict:
    """Render neighbouring main pieces into one new video."""
    pieces = timeline.get("segments") or []
    numbers = sorted({int(n) for n in numbers})
    if len(numbers) < 2 or numbers[0] < 0 or numbers[-1] >= len(pieces) \
            or numbers != list(range(numbers[0], numbers[-1] + 1)):
        raise ValueError("Select two or more video pieces that are next to each other.")
    part = {"aspect": timeline.get("aspect"), "fit": timeline.get("fit"),
            "transition": timeline.get("transition"), "fps": timeline.get("fps"),
            "segments": [pieces[n] for n in numbers]}
    target = Path(out_dir) / "_editor" / "compound" / f"compound_{int(time.time() * 1000)}.mp4"
    seconds = editor.render(part, target, log=log)
    return {"path": str(target), "duration": round(seconds, 2), "pieces": numbers}


def speak(out_dir, text: str, voice: str = "", rate: int = 0) -> dict:
    target = Path(out_dir) / "_editor" / "voice" / f"voice_{int(time.time() * 1000)}.wav"
    tts.speak(text, target, voice, rate)
    return {"path": str(target), "duration": round(ingest.length_of(target), 2)}
