"""
follow.py - moves the vertical crop to the person who is TALKING, and jumps when the camera cuts.

WHY it exists:
    reframe.py used ONE crop position for the whole clip. With two people, or a video that cuts
    between cameras, that crop often shows the wrong person or an empty chair.

HOW it works:
    1. Look at about 4 pictures per second.
    2. Note camera cuts (the picture suddenly changes a lot).
    3. Find faces. For each face, measure how much its mouth area changed since the last picture.
    4. For each short moment choose the face whose mouth moves most. Do not jump back and forth:
       stay at least 1.5 seconds, except right after a camera cut.
    5. Give ffmpeg a list of "from this second, crop here".
    The approach (cut -> faces -> mouth movement -> crop) follows ClipsAI's resizer
    (https://github.com/DHARMAdr/clipsai, MIT licence, see THIRD_PARTY_NOTICES.md). ClipsAI uses
    PyTorch face models and a speaker-separation model that needs an online account. This is our
    own light version using only OpenCV, which the app already carries.

LIMITS: side faces and very small faces are often missed; a person who nods a lot can win over
    the one speaking.
HOW TO IMPROVE:
    - A better face detector (OpenCV YuNet) with real mouth points.
    - Use the voice (who is speaking) and a split screen for two people.
"""

from pathlib import Path

SAMPLE_EVERY = 0.25          # seconds between pictures
HOLD = 1.5                   # shortest time to stay on one person
CUT_DIFFERENCE = 30          # average brightness change that counts as a camera cut
SAME_PLACE = 0.08            # faces closer than this (part of the width) are the same spot
MAX_SECONDS = 600            # longer clips keep the simple single crop
MAX_CHANGES = 60             # keeps the ffmpeg formula a sensible size


def sample(video: Path, start: float, end: float, detect=None):
    """[(time from clip start, camera cut?, [(face centre 0..1, size, mouth movement)])]."""
    import cv2
    import numpy as np

    if detect is None:
        cascade = cv2.CascadeClassifier(
            cv2.data.haarcascades + "haarcascade_frontalface_default.xml")

        def detect(gray):
            return cascade.detectMultiScale(gray, 1.15, 5, minSize=(30, 30))

    cap = cv2.VideoCapture(str(video))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30
    step = max(1, int(round(fps * SAMPLE_EVERY)))
    cap.set(cv2.CAP_PROP_POS_MSEC, start * 1000)
    out, before, number = [], None, 0
    while True:
        if not cap.grab():                      # reading straight through is much faster than seeking
            break
        t = number / fps
        number += 1
        if t > end - start:
            break
        if (number - 1) % step:
            continue
        ok, frame = cap.retrieve()
        if not ok:
            break
        scale = 640 / frame.shape[1]
        gray = cv2.cvtColor(cv2.resize(frame, None, fx=scale, fy=scale), cv2.COLOR_BGR2GRAY)
        cut = before is not None and float(np.mean(cv2.absdiff(gray, before))) > CUT_DIFFERENCE
        faces = []
        for x, y, w, h in detect(gray):
            mouth = (slice(y + h * 3 // 5, y + h), slice(x + w // 5, x + w * 4 // 5))
            moved = 0.0
            if before is not None and not cut and gray[mouth].size:
                moved = float(np.mean(cv2.absdiff(gray[mouth], before[mouth])))
            faces.append(((x + w / 2) / gray.shape[1], w / gray.shape[1], moved))
        out.append((t, cut, faces))
        before = gray
    cap.release()
    return out


def plan(samples: list) -> list:
    """Turn the samples into [(from second, centre 0..1)]. [] when faces are too rare."""
    with_faces = sum(1 for _, _, faces in samples if faces)
    if not samples or with_faces / len(samples) < 0.2:
        return []

    result, since = [], 0.0
    for i, (t, cut, faces) in enumerate(samples):
        # Add up movement over the next second, per spot, so one blink does not decide.
        spots = []                                     # [centre, movement, size]
        for later_t, later_cut, later_faces in samples[i:]:
            if later_t - t > 1.0 or (later_cut and later_t > t):
                break
            for centre, size, moved in later_faces:
                for spot in spots:
                    if abs(spot[0] - centre) < SAME_PLACE:
                        spot[1] += moved
                        spot[2] = max(spot[2], size)
                        break
                else:
                    spots.append([centre, moved, size])
        if not spots:
            continue                                   # no face now: stay where we are
        best = max(spots, key=lambda s: (s[1], s[2]))
        if not result:
            result.append((0.0, best[0]))
            continue
        now = result[-1][1]
        if abs(best[0] - now) < SAME_PLACE:
            continue
        here = next((s for s in spots if abs(s[0] - now) < SAME_PLACE), None)
        clearly = here is None or best[1] > here[1] * 1.3
        if cut or (t - since >= HOLD and clearly):
            result.append((round(t, 2), best[0]))
            since = t
    return result[:MAX_CHANGES]


def follow(video: Path, start: float, end: float, src_w: int):
    """[(from second, centre x in pixels)] for the clip, or None to use the simple method."""
    if end - start > MAX_SECONDS:
        return None
    try:
        steps = plan(sample(video, start, end))
    except Exception:                                  # noqa: BLE001 - framing must never stop a render
        return None
    return [(t, x * src_w) for t, x in steps] or None


def crop_x(steps: list, crop_w: int, src_w: int) -> str:
    """The ffmpeg formula for the left edge of the crop over time."""
    def left(centre):
        return int(min(max(centre - crop_w / 2, 0), src_w - crop_w))

    formula = str(left(steps[-1][1]))
    for (_, centre), (next_start, _) in zip(reversed(steps[:-1]), reversed(steps[1:])):
        formula = f"if(lt(t,{next_start:.2f}),{left(centre)},{formula})"
    return f"'{formula}'"
