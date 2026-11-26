"""
killfeed.py - finds the moments YOU got a kill by watching the game's kill feed.

WHY it exists:
    A gameplay video has no speech to analyse, so the "viral moment" is the kill itself.
    In Valorant, every kill adds a row to the kill feed (top-right corner), and the rows for
    YOUR kills are drawn with a coloured highlight. If we can count those highlighted rows
    over time, every time the count goes UP a new kill just happened.

HOW it works (step by step):
    1. ffmpeg crops only the kill-feed area (the "ROI" = region of interest), samples it a few
       times per second (default 8) and shrinks it. This is the slow part, so we let ffmpeg do
       it instead of Python. It sends raw pixels to us.
    2. For each sample we make a "mask": which pixels have the highlight colour (hue,
       saturation, brightness are tested - see viral/game profile `highlight`).
    3. We look at the mask row by row. A kill-feed entry looks like a wide, horizontal bar that
       touches the RIGHT edge. Scan-lines that match are grouped into "bands"; each band about
       one row tall = one kill-feed entry. (Taller bands count as several merged entries.)
       Bands that are too tall (a full-screen red flash) are thrown away as false alarms.
    4. We smooth the count over time (median of 3 samples) so one noisy frame can't fake a kill.
    5. Every increase of the smoothed count = one kill at that time.

HONEST LIMITS:
    - The default colours/area are a best guess. HUD scale, resolution, colour-blind mode and
      game updates can change them. Run `python -m shortsforge calibrate ...` on a frame of
      YOUR footage to check and fix them (takes 2 minutes).
    - If a feed row disappears in the same 1/8 second that another appears, one kill is missed.
    - It cannot tell a kill from an assist if both use the same highlight.

HOW TO IMPROVE:
    - Track each row by its colour signature so a "swap" can never hide a kill.
    - Read the player name/agent icon with OCR or template matching to separate kills / deaths.
    - Add the kill SOUND as a second, independent signal and keep only kills seen by both.
    - Support other games by adding a new profile in games/ (Apex, CS2, Fortnite, ...).
"""

import hashlib
import json
import subprocess
from pathlib import Path

import numpy as np

from .imgio import draw_hlines, enlarge, write_png

# Keys of the game profile that change the detection result. If any of them change,
# the cached result on disk is thrown away and detection runs again.
_SIGNATURE_KEYS = ("roi", "scan_fps", "scan_width", "scan_height", "row_height_ref",
                   "highlight", "min_row_fill", "right_edge_frac", "right_edge_fill",
                   "min_band_fraction", "max_band_rows", "max_rows", "smooth_window",
                   "method", "style", "name_template_id", "name_threshold", "victim_gap",
                   "name_fps")


def roi_box(src_w: int, src_h: int, roi) -> tuple:
    """Turn the ROI fractions (0-1) into pixel numbers: (x, y, width, height)."""
    x0, y0, x1, y1 = roi
    x, y = int(x0 * src_w), int(y0 * src_h)
    w = min(max(16, int((x1 - x0) * src_w)), src_w - x)
    h = min(max(16, int((y1 - y0) * src_h)), src_h - y)
    return x, y, w // 2 * 2, h // 2 * 2          # even numbers are safest for ffmpeg


def row_height_scaled(info: dict, gp: dict) -> float:
    """How tall (in scaled sample pixels) one kill-feed row is."""
    _, _, _, ch = roi_box(info["width"], info["height"], gp["roi"])
    # A row is ~40 px tall in a 1080p video; scale for other resolutions, then for our resize.
    return gp["row_height_ref"] * (info["height"] / 1080.0) * (gp["scan_height"] / ch)


def scan_frames(video, info: dict, gp: dict, start: float = 0.0, duration=None):
    """Yield small RGB pictures (numpy arrays) of the kill-feed area, `scan_fps` per second."""
    x, y, w, h = roi_box(info["width"], info["height"], gp["roi"])
    out_w, out_h = gp["scan_width"], gp["scan_height"]
    vf = f"fps={gp['scan_fps']},crop={w}:{h}:{x}:{y},scale={out_w}:{out_h}:flags=area"
    cmd = ["ffmpeg", "-v", "error", "-nostdin"]
    if start > 0:
        cmd += ["-ss", f"{start:.3f}"]
    cmd += ["-i", str(video)]
    if duration is not None:
        cmd += ["-t", f"{duration:.3f}"]
    cmd += ["-an", "-sn", "-vf", vf, "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]

    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    frame_bytes = out_w * out_h * 3
    produced = 0
    try:
        while True:
            buf = proc.stdout.read(frame_bytes)      # blocks until a whole picture arrives
            if len(buf) < frame_bytes:
                break
            produced += 1
            yield np.frombuffer(buf, dtype=np.uint8).reshape(out_h, out_w, 3)
    finally:
        proc.kill()                                  # always stop ffmpeg, even on errors
        proc.wait()
        proc.stdout.close()                          # release the pipe (avoids a warning)
    if produced == 0:
        raise RuntimeError("ffmpeg produced no frames. Is the video path correct and readable?")


def rgb_to_hsv(rgb):
    """Convert an RGB picture to hue (0-360), saturation (0-1), value/brightness (0-1)."""
    x = rgb.astype(np.float32) / 255.0
    r, g, b = x[..., 0], x[..., 1], x[..., 2]
    mx, mn = x.max(axis=-1), x.min(axis=-1)
    d = mx - mn
    hue = np.zeros_like(mx)
    nz = d > 1e-6                                    # grey pixels have no hue
    is_r = nz & (mx == r)
    is_g = nz & (mx == g) & ~is_r
    is_b = nz & ~is_r & ~is_g
    hue[is_r] = ((g - b)[is_r] / d[is_r]) % 6
    hue[is_g] = (b - r)[is_g] / d[is_g] + 2
    hue[is_b] = (r - g)[is_b] / d[is_b] + 4
    hue *= 60.0
    sat = np.where(mx > 1e-6, d / np.maximum(mx, 1e-6), 0.0)
    return hue, sat, mx


def highlight_mask(rgb, hl: dict):
    """True where a pixel has the 'my kill' highlight colour."""
    hue, sat, val = rgb_to_hsv(rgb)
    in_hue = np.zeros(hue.shape, dtype=bool)
    for lo, hi in hl["hue_ranges"]:                  # several ranges because red wraps around 360
        in_hue |= (hue >= lo) & (hue <= hi)
    return in_hue & (sat >= hl["min_saturation"]) & (val >= hl["min_value"])


def find_rows(mask, gp: dict, row_h: float) -> list:
    """Find kill-feed entries in a mask. Returns a list of (y_start, y_end, number_of_rows)."""
    fill = mask.mean(axis=1)                         # share of matching pixels on each scan-line
    edge_n = max(1, int(mask.shape[1] * gp["right_edge_frac"]))
    edge = mask[:, -edge_n:].mean(axis=1)            # same, but only the right-hand edge
    active = (fill >= gp["min_row_fill"]) & (edge >= gp["right_edge_fill"])

    bands, y, total = [], 0, len(active)
    while y < total:
        if not active[y]:
            y += 1
            continue
        y2 = y
        while y2 + 1 < total and active[y2 + 1]:
            y2 += 1                                  # extend the band downwards
        height = y2 - y + 1
        if height >= row_h * gp["min_band_fraction"]:        # ignore thin specks
            rows = max(1, int(round(height / row_h)))
            if rows <= gp["max_band_rows"]:                  # ignore giant flashes
                bands.append((y, y2, rows))
        y = y2 + 1
    return bands


def find_border_rows(mask, gp: dict, row_h: float) -> list:
    """Find entries that are marked by a thin coloured OUTLINE instead of a filled bar.

    WHY: some games draw only a bright border around YOUR kill-feed line.
    HOW: look for thin horizontal lines of the colour, then pair a top line with a bottom line
    that is about one row lower. Each pair is one entry.
    HOW TO IMPROVE: also check the left and right sides of the rectangle.
    """
    fill = mask.mean(axis=1)
    active = fill >= gp.get("min_line_fill", 0.18)
    lines, y, total = [], 0, len(active)
    while y < total:
        if active[y]:
            y2 = y
            while y2 + 1 < total and active[y2 + 1]:
                y2 += 1
            if y2 - y + 1 <= max(3, row_h * 0.35):          # thin = a line, not a filled area
                lines.append((y + y2) / 2.0)
            y = y2 + 1
        else:
            y += 1
    bands, i = [], 0
    while i < len(lines) - 1:
        gap = lines[i + 1] - lines[i]
        if 0.55 * row_h <= gap <= 1.35 * row_h:
            bands.append((int(lines[i]), int(lines[i + 1]), 1))
            i += 2
        else:
            i += 1
    return bands


def rows_in_frame(frame, gp: dict, row_h: float) -> list:
    """The highlighted entries of one picture, for either style ('fill' bar or 'border')."""
    mask = highlight_mask(frame, gp["highlight"])
    finder = find_border_rows if gp.get("style") == "border" else find_rows
    return finder(mask, gp, row_h)


def smooth_counts(counts, window: int):
    """Median filter: each value becomes the middle of itself and its neighbours."""
    counts = np.asarray(counts, dtype=np.int32)
    if window <= 1 or len(counts) < window:
        return counts
    pad = window // 2
    padded = np.pad(counts, (pad, pad), mode="edge")
    windows = np.lib.stride_tricks.sliding_window_view(padded, window)
    return np.median(windows, axis=1).astype(np.int32)


def counts_to_kill_times(counts, fps: float, start: float = 0.0) -> list:
    """Every increase of the row count is a kill. Returns a list of times in seconds."""
    kills, previous = [], 0
    for i, c in enumerate(counts):
        if c > previous:
            kills.extend([round(start + i / fps, 2)] * int(c - previous))
        previous = int(c)
    return kills


def _signature(gp: dict, info: dict) -> str:
    """A fingerprint of the settings + video, used to know if the cache is still valid."""
    payload = {k: gp.get(k) for k in _SIGNATURE_KEYS}
    payload["video"] = [info["width"], info["height"], round(info["duration"], 1)]
    return hashlib.md5(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def detect(video, info: dict, gp: dict, work_dir: Path, log=print,
           debug_dir=None, force: bool = False) -> list:
    """Scan the whole video and return the list of kill times (seconds)."""
    work_dir.mkdir(parents=True, exist_ok=True)
    cache = work_dir / "killfeed.json"
    signature = _signature(gp, info)
    if cache.exists() and not force and not debug_dir:
        data = json.loads(cache.read_text())
        if data.get("signature") == signature:
            log("Using cached kill-feed scan.")
            return data["kills"]

    if gp.get("method") == "name":                   # you taught the app your name (teach.py)
        from . import namefeed
        kills = namefeed.detect(video, info, gp, log=log)
        log(f"Found {len(kills)} kill(s).")
        cache.write_text(json.dumps({"signature": signature, "kills": kills}))
        return kills

    fps = gp["scan_fps"]
    row_h = row_height_scaled(info, gp)
    expected = max(1, int(info["duration"] * fps))
    counts, stash, previous, next_report = [], {}, 0, 0.1
    log("Scanning the kill feed (this is the slow step) ...")

    for i, frame in enumerate(scan_frames(video, info, gp)):
        bands = rows_in_frame(frame, gp, row_h)
        n = min(sum(b[2] for b in bands), gp["max_rows"])
        counts.append(n)
        if debug_dir and n > previous:               # remember the picture for the debug folder
            stash[i] = (frame.copy(), bands)
        previous = n
        if i / expected >= next_report:
            log(f"  ... {int(next_report * 100)}%")
            next_report += 0.1

    smooth = smooth_counts(counts, gp["smooth_window"])
    kills = counts_to_kill_times(smooth, fps)
    log(f"Found {len(kills)} kill(s).")

    if debug_dir:
        _write_debug(debug_dir, smooth, kills, stash, fps)

    cache.write_text(json.dumps({"signature": signature, "kills": kills}))
    return kills


def _write_debug(debug_dir: Path, smooth, kills: list, stash: dict, fps: float) -> None:
    """Save one picture per detected kill so you can SEE what the detector saw."""
    debug_dir.mkdir(parents=True, exist_ok=True)
    for n, t in enumerate(kills, start=1):
        centre = int(round(t * fps))
        near = [k for k in stash if abs(k - centre) <= 3]      # raw frame close to this kill
        if not near:
            continue
        frame, bands = stash[min(near, key=lambda k: abs(k - centre))]
        picture = frame.copy()
        for y0, y1, _ in bands:
            draw_hlines(picture, y0, y1)                       # green lines = detected rows
        write_png(debug_dir / f"kill_{n:02d}_{t:07.2f}s.png", enlarge(picture, 2))


def grab_roi(video, info: dict, gp: dict, time_s: float):
    """One kill-feed picture at a given time (used by the calibrate tool)."""
    for frame in scan_frames(video, info, gp, start=max(0.0, time_s), duration=1.0):
        return frame.copy()
    raise RuntimeError("Could not read a frame at that time.")
