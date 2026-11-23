"""
calibrate.py - helps you tune the kill detector to YOUR footage (do this once per setup).

WHY it exists:
    Kill-feed position, size and colour depend on your resolution, HUD settings, colour-blind
    mode and game version. We could not test on your exact recordings, so instead of guessing
    silently, this tool shows you what the detector sees and suggests better settings.

HOW to use it:
    1. Open your recording and find a moment just AFTER you got a kill (the feed shows your row).
       Note the time in seconds, e.g. 123.
    2. Run:   python -m shortsforge calibrate "video.mp4" --time 123
    3. Open the pictures it writes in output/_calibrate/ :
         full_frame.png  - the whole frame with a RED box = the area we scan
         roi.png         - the scanned area, enlarged
         mask.png        - WHITE = pixels that match the highlight colour (should be your kill rows)
    4. If the red box misses the kill feed, pass  --roi x0,y0,x1,y1  (fractions 0-1, e.g.
       0.60,0.03,1.0,0.45) and run again until it fits.
    5. If the mask is empty/wrong, look at the printed colour table, copy the suggested
       "highlight" JSON into a file my_valorant.json and use it with  --game-profile my_valorant.json

HOW it works:
    It grabs ONE frame, applies exactly the same functions the detector uses (killfeed.py), and
    prints how many kill-feed rows it found. It also lists the most common saturated colours in
    the area, because your kill highlight is usually one of them.

HOW TO IMPROVE:
    - Open an interactive window where you click on a kill row to pick its colour.
    - Auto-search the ROI by looking for the right-aligned bars across many frames.
"""

import json
import subprocess
from pathlib import Path

import numpy as np

from . import ingest, killfeed
from .config import load_game_profile
from .imgio import draw_hlines, enlarge, write_png


def _full_frame(video, info: dict, time_s: float, width: int = 960):
    """One whole frame, shrunk to `width` pixels wide, as an RGB array."""
    height = int(info["height"] * width / info["width"]) // 2 * 2
    cmd = ["ffmpeg", "-v", "error", "-nostdin", "-ss", f"{time_s:.3f}", "-i", str(video),
           "-frames:v", "1", "-vf", f"scale={width}:{height}", "-f", "rawvideo",
           "-pix_fmt", "rgb24", "-"]
    raw = subprocess.run(cmd, capture_output=True).stdout
    if len(raw) < width * height * 3:
        raise RuntimeError("Could not read a frame at that time (is it beyond the video end?).")
    return np.frombuffer(raw, dtype=np.uint8).reshape(height, width, 3).copy()


def _draw_roi_box(frame, roi, colour=(255, 0, 0), t: int = 3):
    """Draw the rectangle of the scanned area onto a copy of the frame."""
    h, w = frame.shape[:2]
    x0, y0, x1, y1 = int(roi[0] * w), int(roi[1] * h), int(roi[2] * w) - 1, int(roi[3] * h)
    img = frame.copy()
    img[y0:y0 + t, x0:x1] = colour
    img[y1 - t:y1, x0:x1] = colour
    img[y0:y1, x0:x0 + t] = colour
    img[y0:y1, x1 - t:x1] = colour
    return img


def _suggest_colours(roi_img) -> list:
    """Top colour groups (by hue) among clearly coloured pixels. Returns printable dicts."""
    hue, sat, val = killfeed.rgb_to_hsv(roi_img)
    chosen = (sat >= 0.35) & (val >= 0.35)
    if chosen.sum() < 20:
        return []
    buckets = (hue[chosen] // 10).astype(int) % 36           # 36 buckets of 10 degrees
    counts = np.bincount(buckets, minlength=36)
    out = []
    for b in np.argsort(counts)[::-1][:3]:
        if counts[b] < 20:
            continue
        pick = chosen & (hue >= b * 10) & (hue < b * 10 + 10)
        mean_rgb = roi_img[pick].mean(axis=0).astype(int).tolist()
        lo, hi = int(b * 10 - 10), int(b * 10 + 20)           # a bit of margin each side
        ranges = [[lo, hi]] if lo >= 0 and hi <= 360 else \
            [[(lo + 360) % 360, 360], [0, hi % 360]] if lo < 0 else [[lo, 360], [0, hi - 360]]
        out.append({
            "hue_bucket": f"{b * 10}-{b * 10 + 10} deg",
            "pixels": int(counts[b]),
            "share_of_area": f"{counts[b] / chosen.size * 100:.1f}%",
            "average_rgb": mean_rgb,
            "suggested_highlight": {
                "hue_ranges": ranges,
                "min_saturation": round(float(np.percentile(sat[pick], 10)) * 0.85, 2),
                "min_value": round(float(np.percentile(val[pick], 10)) * 0.85, 2),
            },
        })
    return out


def calibrate(video: str, time_s: float, game: str = "valorant", game_profile_path=None,
              roi=None, out_dir: str = "output/_calibrate", log=print) -> dict:
    """Write the debug pictures, print what was found, and return the numbers."""
    gp = load_game_profile(game, game_profile_path, {"roi": roi} if roi else None)
    info = ingest.probe(Path(video))
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    full = _full_frame(video, info, time_s)
    write_png(out / "full_frame.png", _draw_roi_box(full, gp["roi"]))

    roi_img = killfeed.grab_roi(video, info, gp, time_s)
    mask = killfeed.highlight_mask(roi_img, gp["highlight"])
    bands = killfeed.find_rows(mask, gp, killfeed.row_height_scaled(info, gp))

    marked = roi_img.copy()
    for y0, y1, _ in bands:
        draw_hlines(marked, y0, y1)
    write_png(out / "roi.png", enlarge(marked, 2))
    write_png(out / "mask.png", enlarge(mask.astype(np.uint8) * 255, 2))

    rows = sum(b[2] for b in bands)
    log(f"Video {info['width']}x{info['height']}, scanned area (fractions) = {gp['roi']}")
    log(f"Kill-feed rows detected at {time_s}s: {rows}")
    if rows == 0:
        log("  -> Nothing detected. Check full_frame.png (is the red box on the kill feed?)")
        log("     and mask.png (white = matching colour). Then adjust --roi or the colours below.")
    suggestions = _suggest_colours(roi_img)
    if suggestions:
        log("Most common coloured pixels in the scanned area (your kill highlight is probably one):")
        for s in suggestions:
            log(f"  {s['hue_bucket']}: {s['share_of_area']} of area, average RGB {s['average_rgb']}")
        log("Suggested file my_valorant.json for the FIRST colour (edit if it is not the right one):")
        log(json.dumps({"highlight": suggestions[0]["suggested_highlight"]}, indent=2))
    log(f"Pictures saved in: {out.resolve()}")
    return {"rows": rows, "suggestions": suggestions}
