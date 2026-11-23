"""
reframe.py - turns a wide (16:9) video into a tall (9:16, 1080x1920) short.

WHY it exists:
    Shorts and Reels are vertical. Just squeezing a landscape video makes it tiny. We either
    crop around the speaker's face, or show the full video over a blurred copy of itself
    (the style most reels use).

HOW it works:
    - detect_face_x(): samples a frame per second with OpenCV's built-in face detector and
      returns the typical horizontal face position (or None if faces are rare).
    - build_filter(): creates the ffmpeg filter text for the chosen mode:
        auto   -> face crop if a face was found, otherwise blur
        face   -> crop around the face
        center -> crop the middle
        blur   -> full video on a blurred background
    - If the source is ALREADY vertical we just scale it to 1080x1920.

HOW TO IMPROVE:
    - Follow the face smoothly over time (moving crop) instead of one fixed position.
    - Support two speakers (split screen) and screen-recordings (zoom on the active area).
    - Use a better detector (MediaPipe / YOLO face) for side-faces and small faces.
"""

from pathlib import Path

OUT_W, OUT_H = 1080, 1920


def detect_face_x(video: Path, start: float, end: float, src_w: int):
    """Typical face centre (x pixel) in [start, end], or None if no reliable face."""
    try:
        import cv2
    except ImportError:
        return None   # OpenCV not installed -> caller falls back to blur/center
    cascade = cv2.CascadeClassifier(
        cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    cap = cv2.VideoCapture(str(video))
    xs, tried, t = [], 0, start
    while t < end and tried < 40:            # at most 40 samples keeps it fast
        cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
        ok, frame = cap.read()
        if not ok:
            break
        scale = 480 / frame.shape[0]         # shrink for speed
        small = cv2.resize(frame, None, fx=scale, fy=scale)
        gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
        faces = cascade.detectMultiScale(gray, 1.2, 5, minSize=(40, 40))
        if len(faces):
            x, y, w, h = max(faces, key=lambda f: f[2] * f[3])   # biggest face
            xs.append((x + w / 2) / scale)   # back to original pixel scale
        tried += 1
        t += 1.0
    cap.release()
    if tried == 0 or len(xs) / tried < 0.2:  # found in fewer than 20% of samples
        return None
    xs.sort()
    return xs[len(xs) // 2]                  # median = ignores odd outliers


def build_filter(mode: str, src_w: int, src_h: int, face_x=None) -> str:
    """Return the ffmpeg -vf text that makes a 1080x1920 picture."""
    if src_w / src_h <= 9 / 16 * 1.02:       # already vertical (or nearly)
        return f"scale={OUT_W}:{OUT_H}:force_original_aspect_ratio=increase,crop={OUT_W}:{OUT_H}"

    if mode == "auto":
        mode = "face" if face_x is not None else "blur"
    if mode == "face" and face_x is None:
        mode = "center"

    if mode in ("face", "center"):
        crop_w = int(src_h * 9 / 16) // 2 * 2          # even number, ffmpeg likes that
        centre = face_x if (mode == "face" and face_x is not None) else src_w / 2
        x = int(min(max(centre - crop_w / 2, 0), src_w - crop_w))
        return f"crop={crop_w}:{src_h}:{x}:0,scale={OUT_W}:{OUT_H}:flags=lanczos"

    # blur mode: background = zoomed + blurred copy, foreground = whole video, centred
    return (
        "split[a][b];"
        f"[a]scale={OUT_W}:{OUT_H}:force_original_aspect_ratio=increase,"
        f"crop={OUT_W}:{OUT_H},boxblur=25:5[bg];"
        f"[b]scale={OUT_W}:-2[fg];"
        "[bg][fg]overlay=(W-w)/2:(H-h)/2"
    )


# ---------------------------------------------------------------------------
# Gameplay layouts (added in v0.2.0)
# WHY: gameplay is 16:9 with the action in the middle. Good vertical layouts are:
#   center = zoom into the middle (crosshair action fills the screen)
#   blur   = whole game picture on a blurred background (safe: nothing is cut off)
#   stack  = gameplay on top + your facecam below (the classic streamer short)
# HOW: stack needs the facecam position as fractions of the frame: (x, y, width, height).
# HOW TO IMPROVE: follow the crosshair / action with a moving crop, add a zoom-punch on kills.
# ---------------------------------------------------------------------------
def build_game_filter(layout: str, src_w: int, src_h: int, facecam=None) -> str:
    """ffmpeg filter text for a gameplay short."""
    if layout != "stack" or not facecam:
        return build_filter("blur" if layout == "blur" else "center", src_w, src_h)

    top_h, bot_h = 1280, OUT_H - 1280                     # 1080x1280 gameplay + 1080x640 facecam
    gw = min(src_w, int(src_h * OUT_W / top_h)) // 2 * 2
    gx = (src_w - gw) // 2
    fx, fy, fw, fh = facecam
    cx, cy = int(fx * src_w), int(fy * src_h)
    cw = max(16, min(int(fw * src_w), src_w - cx)) // 2 * 2
    ch = max(16, min(int(fh * src_h), src_h - cy)) // 2 * 2
    return (
        "split=2[g][f];"
        f"[g]crop={gw}:{src_h}:{gx}:0,scale={OUT_W}:{top_h}:flags=lanczos[top];"
        f"[f]crop={cw}:{ch}:{cx}:{cy},scale={OUT_W}:{bot_h}:"
        f"force_original_aspect_ratio=increase:flags=lanczos,crop={OUT_W}:{bot_h}[bot];"
        "[top][bot]vstack"
    )
