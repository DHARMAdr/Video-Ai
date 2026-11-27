"""
namefeed.py - finds YOUR kills by looking for YOUR NAME in the kill feed.

WHY it exists:
    The colour rule (killfeed.py) is a guess about how the game paints your kills. It can be wrong
    for your HUD settings or a game update, and then no kill is found. Your own name does not
    change: you draw a box around it once (the Teach tab), and we search for that little picture.

HOW it works:
    1. Every picture is first scaled as if the video were 1080 pixels high, so one saved name
       picture works for 720p, 1080p and 1440p recordings of the same HUD.
    2. ffmpeg crops the kill-feed area a few times per second.
    3. OpenCV's matchTemplate gives, for every position, how much it looks like your name (0-1).
    4. A feed line reads "KILLER  weapon  VICTIM" and ends at the right of the screen. If your
       name sits very close to the right edge, you are the VICTIM (a death), so it is ignored.
    5. Each time the number of lines with your name (as killer) goes UP, that is a new kill.

HONEST LIMITS:
    - The picture must come from the same game and HUD scale as the videos you scan.
    - The victim rule assumes the feed is on the RIGHT side of the screen.

HOW TO IMPROVE:
    - Try a few sizes of the name picture, so a changed HUD scale still matches.
    - Read the text with OCR instead of matching a picture.
"""

import subprocess

import numpy as np

from .killfeed import roi_box

REF_HEIGHT = 1080                     # all name pictures are measured at this video height


def ref_geometry(info: dict, roi) -> dict:
    """Where the kill-feed area is, in source pixels and in '1080p-high' pixels."""
    x, y, w, h = roi_box(info["width"], info["height"], roi)
    k = REF_HEIGHT / info["height"]
    return {"crop": (x, y, w, h), "w": int(round(w * k)) // 2 * 2, "h": int(round(h * k)) // 2 * 2,
            "x0": x * k, "y0": y * k, "frame_w": info["width"] * k}


def scan(video, info: dict, roi, fps: float, start: float = 0.0, duration=None):
    """Yield grey pictures of the kill-feed area at 1080p scale."""
    g = ref_geometry(info, roi)
    x, y, w, h = g["crop"]
    cmd = ["ffmpeg", "-v", "error", "-nostdin"]
    if start > 0:
        cmd += ["-ss", f"{start:.3f}"]
    cmd += ["-i", str(video)]
    if duration is not None:
        cmd += ["-t", f"{duration:.3f}"]
    cmd += ["-an", "-sn", "-vf",
            f"fps={fps},crop={w}:{h}:{x}:{y},scale={g['w']}:{g['h']}:flags=bicubic",
            "-f", "rawvideo", "-pix_fmt", "gray", "-"]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    size = g["w"] * g["h"]
    try:
        while True:
            buf = proc.stdout.read(size)
            if len(buf) < size:
                break
            yield np.frombuffer(buf, dtype=np.uint8).reshape(g["h"], g["w"])
    finally:
        proc.kill()
        proc.wait()
        proc.stdout.close()


def load_template(path):
    """Read the saved name picture (works with any folder name, also non-English ones)."""
    import cv2
    data = np.fromfile(str(path), dtype=np.uint8)
    image = cv2.imdecode(data, cv2.IMREAD_GRAYSCALE) if len(data) else None
    if image is None:
        raise RuntimeError("The saved name picture is missing. Teach your name again.")
    return image


def find_name(gray, template, threshold: float, geometry: dict, victim_gap: float) -> list:
    """Positions (x, y, score) of your name as KILLER in one picture, one per feed line."""
    import cv2
    th, tw = template.shape
    if gray.shape[0] < th or gray.shape[1] < tw:
        return []
    result = np.nan_to_num(cv2.matchTemplate(gray, template, cv2.TM_CCOEFF_NORMED),
                           nan=0.0, posinf=0.0, neginf=0.0)
    found = []
    for _ in range(6):                                   # a feed never shows more lines than this
        _, best, _, (x, y) = cv2.minMaxLoc(result)
        if best < threshold:
            break
        right_gap = geometry["frame_w"] - (geometry["x0"] + x + tw)
        if right_gap >= victim_gap:
            found.append((x, y, float(best)))
        result[max(0, y - th): y + th, :] = 0            # blank this line, look for the next
    return found


def counts_for(frames, template, gp: dict, geometry: dict) -> list:
    """How many lines carry your name in each picture."""
    return [len(find_name(f, template, gp["name_threshold"], geometry, gp["victim_gap"]))
            for f in frames]


# ---------------------------------------------------------------------------
# Following each feed line by what is written after your name
# WHY: counting lines misses a kill when an old line leaves in the same instant a new one
#      arrives (the count stays 1). The words and icons AFTER your name (weapon + victim) are
#      different for every kill, so we remember each line by that picture.
# HOW: each picture's lines are paired with the lines we are already following. A line that
#      pairs with nothing is new; seen twice in a row, it is a kill.
# HOW TO IMPROVE: read the weapon icon to tell a knock from a kill.
# ---------------------------------------------------------------------------
TAIL_WIDTH = 170        # 1080p pixels after the name that identify a line
SAME_LINE = 0.70        # how alike two tails must be to count as the same line
FORGET_AFTER = 1.5      # seconds unseen before a line is forgotten (covers flashes)


def _tail(gray, x: int, y: int, template):
    """The picture just after your name, on the same line."""
    th, tw = template.shape
    part = gray[y:y + th, x + tw:x + tw + TAIL_WIDTH].astype(np.float32)
    full = np.zeros((th, TAIL_WIDTH), np.float32)
    full[:part.shape[0], :part.shape[1]] = part - (part.mean() if part.size else 0)
    return full


def _alike(a, b) -> float:
    """Best likeness of two tails (-1 to 1), allowing them to sit 2 pixels apart."""
    import cv2
    padded = cv2.copyMakeBorder(a, 2, 2, 2, 2, cv2.BORDER_REPLICATE)
    score = cv2.matchTemplate(padded, b, cv2.TM_CCOEFF_NORMED)
    return float(np.nan_to_num(score, nan=0.0, posinf=0.0, neginf=0.0).max())


def line_times(frames, template, gp: dict, geometry: dict, fps: float, start: float = 0.0) -> list:
    """Times at which a new line with your name appeared (one per line = one per kill)."""
    lines, times = [], []                # each line: tail picture, first and last time, samples
    for i, gray in enumerate(frames):
        now = start + i / fps
        found = find_name(gray, template, gp["name_threshold"], geometry, gp["victim_gap"])
        tails = [_tail(gray, x, y, template) for x, y, _ in found]
        pairs = sorted(((_alike(tail, line["tail"]), a, b) for a, tail in enumerate(tails)
                        for b, line in enumerate(lines)), reverse=True)
        used_tails, used_lines = set(), set()
        for score, a, b in pairs:        # best pairs first, each line used once
            if score >= SAME_LINE and a not in used_tails and b not in used_lines:
                used_tails.add(a)
                used_lines.add(b)
                line = lines[b]
                line.update(tail=tails[a], last=now, seen=line["seen"] + 1)
                if line["seen"] == 2:
                    times.append(round(line["first"], 3))
        lines += [{"tail": tail, "first": now, "last": now, "seen": 1}
                  for a, tail in enumerate(tails) if a not in used_tails]
        # A line seen only once is dropped at once (noise); a confirmed one is kept a little.
        lines = [l for l in lines
                 if now - l["last"] <= (FORGET_AFTER if l["seen"] > 1 else 1.0 / fps)]
    return sorted(times)


def detect(video, info: dict, gp: dict, log=print) -> list:
    """Scan the whole video; return the times of your kills."""
    template = load_template(gp["name_template"])
    geometry = ref_geometry(info, gp["roi"])
    fps = gp.get("name_fps", 4)
    expected = max(1, int(info["duration"] * fps))
    log("Looking for your name in the kill feed ...")
    seen = [0]

    def watched():                       # the same pictures, with a progress message
        report = 0.1
        for i, frame in enumerate(scan(video, info, gp["roi"], fps)):
            seen[0] += 1
            yield frame
            if i / expected >= report:
                log(f"  ... {int(report * 100)}%")
                report += 0.1

    times = line_times(watched(), template, gp, geometry, fps)
    if not seen[0]:
        raise RuntimeError("ffmpeg produced no frames. Is the video path correct and readable?")
    return times
