"""
captions.py - makes the big, bold, word-by-word captions viewers expect on shorts.

WHY it exists:
    Most people watch with sound off, and highlighted words keep the eye moving. Captioned
    shorts hold attention better. We also show the hook sentence as a title for the first
    seconds.

HOW it works:
    We write an ASS subtitle file (a text format ffmpeg can burn into the video).
    Words are grouped in small chunks (default 3). For each word we add one event that shows
    the whole chunk with the CURRENT word in a highlight colour.
    Times are made relative to the clip start (the clip's first frame is time 0).

HOW TO IMPROVE:
    - Add pop/zoom animation per word (ASS \\t tags), emoji insertion, per-niche styles.
    - Support right-to-left and other scripts, and pick a font that has those letters.
    - Let the user choose styles from a "caption_styles" folder.
"""

import re


def _ass_time(seconds: float) -> str:
    """Seconds -> ASS time text H:MM:SS.cc"""
    seconds = max(0.0, seconds)
    h = int(seconds // 3600)
    m = int(seconds % 3600 // 60)
    s = seconds % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def _clean(text: str, upper: bool) -> str:
    """Remove characters that would break ASS (braces, backslashes, line breaks)."""
    text = re.sub(r"[{}\\\r\n]", "", text).strip()
    return text.upper() if upper else text


def build_ass(words: list, clip_start: float, clip_end: float,
              hook_title, style: dict, extra_events=None) -> str:
    """Return the full text of an .ass file for one short."""
    size = style["font_size"]
    highlight = "&H00" + style["highlight_color_bgr"] + "&"   # ASS colour order is BGR
    header = (
        "[Script Info]\nScriptType: v4.00+\nPlayResX: 1080\nPlayResY: 1920\nWrapStyle: 0\n\n"
        "[V4+ Styles]\n"
        "Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,"
        "Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,"
        "Alignment,MarginL,MarginR,MarginV,Encoding\n"
        f"Style: Cap,{style['font']},{size},&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,"
        f"-1,0,0,0,100,100,0,0,1,7,2,2,60,60,{style['margin_bottom']},1\n"
        f"Style: Hook,{style['font']},{int(size * 0.75)},&H00FFFFFF,&H00FFFFFF,&H00000000,"
        "&H80000000,-1,0,0,0,100,100,0,0,1,6,2,8,80,80,260,1\n"
        f"Style: Kill,{style['font']},{int(size * 1.45)},&H00FFFFFF,&H00FFFFFF,&H005546FF,"
        "&H80000000,-1,0,0,0,100,100,2,0,1,9,3,5,60,60,0,1\n\n"
        "[Events]\nFormat: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text\n"
    )
    lines = []
    upper = style["uppercase"]

    # Hook title at the top for the first few seconds.
    if hook_title:
        end = min(style["hook_seconds"], clip_end - clip_start)
        lines.append(f"Dialogue: 1,{_ass_time(0)},{_ass_time(end)},Hook,,0,0,0,,"
                     f"{_clean(hook_title, upper)}")

    # Keep only words that fall inside the clip.
    inside = [w for w in words if w["start"] >= clip_start - 0.05 and w["end"] <= clip_end + 0.05]
    n = style["words_per_chunk"]
    for c in range(0, len(inside), n):
        chunk = inside[c:c + n]
        for k, current in enumerate(chunk):
            # Build the chunk text, colouring only the current word.
            parts = []
            for idx, w in enumerate(chunk):
                word = _clean(w["word"], upper)
                parts.append(f"{{\\c{highlight}}}{word}{{\\c&H00FFFFFF&}}" if idx == k else word)
            start = current["start"] - clip_start
            # The word stays until the next word begins (no flicker between words).
            nxt = chunk[k + 1]["start"] if k + 1 < len(chunk) else current["end"]
            end = nxt - clip_start
            lines.append(f"Dialogue: 0,{_ass_time(start)},{_ass_time(end)},Cap,,0,0,0,,"
                         f"{' '.join(parts)}")
    lines.extend(extra_events or [])          # e.g. the kill popups from game mode
    return header + "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Kill popups (added in v0.2.0)
# WHY: game shorts feel much better with a big "DOUBLE KILL" pop-up at the moment of each kill.
# HOW: one ASS line per kill. `\\t(...)` animates the size (small -> bigger -> normal = "pop"),
#      `\\fad` fades it out. A popup ends early if the next kill happens soon.
# HOW TO IMPROVE: add a screen-shake / zoom-punch, a sound effect, or per-agent colours.
# ---------------------------------------------------------------------------
KILL_NAMES = {1: "KILL", 2: "DOUBLE KILL", 3: "TRIPLE KILL", 4: "QUADRA KILL", 5: "ACE"}


def kill_events(kill_times: list, clip_start: float, clip_end: float,
                popup_seconds: float = 1.4, y: int = 780) -> list:
    """Return ASS 'Dialogue' lines, one popup per kill (numbered inside this clip)."""
    rel = sorted(t - clip_start for t in kill_times if clip_start <= t <= clip_end)
    length = clip_end - clip_start
    lines = []
    for k, t in enumerate(rel, start=1):
        end = t + popup_seconds
        if k < len(rel):
            end = min(end, rel[k])               # make room for the next popup
        end = min(max(end, t + 0.25), length)
        tags = ("{\\an5\\pos(540,%d)\\fscx50\\fscy50"
                "\\t(0,110,\\fscx125\\fscy125)\\t(110,220,\\fscx100\\fscy100)\\fad(0,200)}" % y)
        text = KILL_NAMES.get(k, f"{k} KILLS")
        lines.append(f"Dialogue: 2,{_ass_time(t)},{_ass_time(end)},Kill,,0,0,0,,{tags}{text}")
    return lines
