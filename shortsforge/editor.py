"""
editor.py - the manual video editor engine (cut, join, speed, filters, effects, text, music).

WHY it exists:
    The automatic shorts are a first draft. Like in CapCut you want to cut, slow down, colour,
    add text and music, and join pieces. This file turns that wish list into a finished MP4.

HOW it works:
    A "timeline" is plain data (a dict):
        segments   - pieces of videos, in order, each with its own settings
        overlays   - pictures, videos and stickers on top (see editor_layers.py)
        audio      - extra sounds placed at any time
        transition - how one piece changes into the next
        texts      - words shown over the video for a while
        music      - a song mixed under the sound
    1. clean() checks every value and forces it into a safe range.
    2. Each segment is rendered to a temporary file with ffmpeg filters (all the same size,
       frame rate and sound format, so they can be joined).
    3. A final pass joins them (with transitions), draws the text and mixes the music.

HONEST LIMITS:
    - Masks do not move on their own; speed curves are chosen from a list.
    - The preview in the window is approximate; "Quick preview" shows the real result.

HOW TO IMPROVE:
    - Draw your own speed curve.
    - Use the graphics card (h264_nvenc) to export faster.
    - Put each effect in a small plug-in file so new ones are easy to add.
"""

import shutil
import subprocess
import tempfile
from pathlib import Path

from . import editor_extras as extras
from . import editor_layers as layers
from . import ingest, matting

SIZES = {"9:16": (1080, 1920), "16:9": (1920, 1080), "1:1": (1080, 1080), "4:5": (1080, 1350)}
FITS = ("crop", "blur", "bars")
FPS = 30
MAX_SEGMENTS, MAX_TEXTS, MAX_SECONDS = 60, 400, 600
TEXT_ANIMATIONS = ("none", "pop", "fade", "slide up", "slide left")
RESOLUTIONS = (720, 1080)
FRAME_RATES = (30, 60)

# name -> ffmpeg filter. The window shows these names in a drop-down.
FILTERS = {
    "none": "",
    "black and white": "hue=s=0",
    "warm": "colorbalance=rs=0.12:rm=0.08:bs=-0.10:bm=-0.06",
    "cool": "colorbalance=bs=0.12:bm=0.08:rs=-0.10:rm=-0.06",
    "vivid": "eq=saturation=1.55:contrast=1.10",
    "cinematic": "eq=contrast=1.12:saturation=0.92,colorbalance=bs=0.10:rh=0.10:bh=-0.06",
    "vintage": "curves=preset=vintage",
    "faded": "eq=contrast=0.85:saturation=0.75:brightness=0.04",
    "sepia": "colorchannelmixer=.393:.769:.189:0:.349:.686:.168:0:.272:.534:.131",
    "negative": "negate",
}
EFFECTS = ("none", "shake", "zoom in", "zoom out", "zoom punch", "glitch", "vhs", "vignette",
           "blur", "sharpen", "flash", "pixelate", "film grain", "mirror split", "edge glow",
           "pulse", "spin in")
TRANSITIONS = ("none", "fade", "dissolve", "fadeblack", "fadewhite", "slideleft", "slideright",
               "slideup", "wipeleft", "circleopen", "pixelize", "zoomin")
TEXT_STYLES = ("outline", "box", "plain")
AUDIO_TYPES = {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac"}


def _num(value, default, low, high):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return default
    return default if value != value else min(high, max(low, value))


def _choice(value, allowed, default):
    return value if value in allowed else default


def _range(raw):
    """The marked area (I and O keys) as (from, to) seconds, or None."""
    if not isinstance(raw, dict):
        return None
    a = _num(raw.get("in"), 0.0, 0.0, MAX_SECONDS)
    b = _num(raw.get("out"), 0.0, 0.0, MAX_SECONDS)
    return (a, b) if b - a >= 0.2 else None


def clean(timeline: dict) -> dict:
    """A safe copy of the timeline. Raises ValueError with a message you can show."""
    segments = []
    for raw in (timeline.get("segments") or [])[:MAX_SEGMENTS]:
        if raw.get("disabled"):                              # switched off with the V key
            continue
        source = str(raw.get("source") or "").strip().strip('"')
        if not Path(source).is_file():
            raise ValueError(f"Video not found: {source or '(empty)'}")
        start = _num(raw.get("start"), 0.0, 0.0, 1e7)
        end = _num(raw.get("end"), 0.0, 0.0, 1e7)
        freeze = _num(raw.get("freeze"), 0.0, 0.0, 30.0)
        if freeze:
            end = start + freeze                             # a still picture of that moment
        if end - start < 0.2:
            raise ValueError("Every piece must be at least 0.2 seconds long.")
        rotate = int(_num(raw.get("rotate"), 0, 0, 270))
        curve = _choice(raw.get("curve"), extras.CURVES, "")
        bg = _choice(raw.get("bg"), matting.BACKGROUNDS[:-1], "")
        segments.append({
            "source": source, "start": start, "end": end,
            "speed": _num(raw.get("speed"), 1.0, 0.25, 4.0),
            "volume": _num(raw.get("volume"), 1.0, 0.0, 3.0),
            "filter": _choice(raw.get("filter"), FILTERS, "none"),
            "effect": _choice(raw.get("effect"), EFFECTS, "none"),
            "brightness": _num(raw.get("brightness"), 0.0, -0.3, 0.3),
            "contrast": _num(raw.get("contrast"), 1.0, 0.5, 2.0),
            "saturation": _num(raw.get("saturation"), 1.0, 0.0, 3.0),
            "zoom": _num(raw.get("zoom"), 1.0, 1.0, 4.0),
            "pan_x": _num(raw.get("pan_x"), 0.0, -1.0, 1.0),
            "pan_y": _num(raw.get("pan_y"), 0.0, -1.0, 1.0),
            "mirror": bool(raw.get("mirror")), "reverse": bool(raw.get("reverse")),
            "rotate": rotate if rotate in (0, 90, 180, 270) else 0,
            "fade_in": _num(raw.get("fade_in"), 0.0, 0.0, 5.0),
            "fade_out": _num(raw.get("fade_out"), 0.0, 0.0, 5.0),
            "freeze": freeze, "curve": "" if freeze else curve, "bg": bg,
            "mask": extras.clean_mask(raw.get("mask"), layers.number),
            "keyframes": layers.keyframes(raw.get("keyframes"), {
                "zoom": (1.0, 1.0, 4.0), "pan_x": (0.0, -1.0, 1.0), "pan_y": (0.0, -1.0, 1.0)}),
        })
        if freeze:
            segments[-1].update({"speed": 1.0, "reverse": False})
        if segments[-1]["curve"]:
            segments[-1]["speed"] = 1.0                      # the curve decides the speed
    if not segments:
        raise ValueError("Add at least one video to the timeline.")
    total = sum((s["end"] - s["start"]) / s["speed"] * extras.curve_factor(s["curve"])
                for s in segments)
    if total > MAX_SECONDS:
        raise ValueError("The edit is longer than 10 minutes.")
    if any(s["reverse"] and s["end"] - s["start"] > 30 for s in segments):
        raise ValueError("Reverse works on pieces up to 30 seconds (it needs a lot of memory).")

    texts = []
    for raw in (timeline.get("texts") or [])[:MAX_TEXTS]:
        words = str(raw.get("text") or "").strip()[:200]
        if not words:
            continue
        start = _num(raw.get("start"), 0.0, 0.0, MAX_SECONDS)
        color = str(raw.get("color") or "#ffffff").lstrip("#")
        if len(color) != 6 or any(c not in "0123456789abcdefABCDEF" for c in color):
            color = "ffffff"
        texts.append({"text": words, "start": start,
                      "end": _num(raw.get("end"), start + 3, start + 0.2, MAX_SECONDS + 5),
                      "x": _num(raw.get("x"), 0.5, 0.0, 1.0), "y": _num(raw.get("y"), 0.2, 0.0, 1.0),
                      "size": _num(raw.get("size"), 80, 20, 300), "color": color,
                      "style": _choice(raw.get("style"), TEXT_STYLES, "outline"),
                      "pop": bool(raw.get("pop", True)),
                      "anim": _choice(raw.get("anim"), TEXT_ANIMATIONS,
                                      "pop" if raw.get("pop", True) else "none")})

    music = None
    raw = timeline.get("music") or {}
    if raw.get("path"):
        if not Path(str(raw["path"])).is_file():
            raise ValueError("The music file was not found.")
        music = {"path": str(raw["path"]), "volume": _num(raw.get("volume"), 0.4, 0.0, 2.0),
                 "start": _num(raw.get("start"), 0.0, 0.0, 1e6)}
    transition = timeline.get("transition") or {}
    return {"aspect": _choice(timeline.get("aspect"), SIZES, "9:16"),
            "fit": _choice(timeline.get("fit"), FITS, "crop"),
            "segments": segments, "texts": texts, "music": music,
            "overlays": layers.clean_overlays(timeline.get("overlays")),
            "audio": layers.clean_audio(timeline.get("audio"), AUDIO_TYPES),
            "resolution": 720 if timeline.get("resolution") in (720, "720") else 1080,
            "range": _range(timeline.get("range")),
            "fps": 60 if timeline.get("fps") in (60, "60") else FPS,
            "transition": {"type": _choice(transition.get("type"), TRANSITIONS, "none"),
                           "seconds": _num(transition.get("seconds"), 0.5, 0.1, 2.0)}}


def segment_filter(seg: dict, width: int, height: int, fit: str) -> str:
    """The ffmpeg video filter chain for one piece (ends with a stream called [v])."""
    length = (seg["end"] - seg["start"]) / seg["speed"]
    chain = []
    if seg["reverse"]:
        chain.append("reverse")
    chain.append(f"setpts=(PTS-STARTPTS)/{seg['speed']:.4f}")
    chain.append({90: "transpose=1", 180: "hflip,vflip", 270: "transpose=2"}.get(seg["rotate"], "null"))
    if seg["mirror"]:
        chain.append("hflip")
    if seg["zoom"] > 1.001:
        z = seg["zoom"]
        chain.append(f"crop=iw/{z:.3f}:ih/{z:.3f}:(iw-iw/{z:.3f})*{(seg['pan_x'] + 1) / 2:.3f}"
                     f":(ih-ih/{z:.3f})*{(seg['pan_y'] + 1) / 2:.3f}")
    head = ",".join(chain)

    if fit == "blur":
        graph = (f"[0:v]{head},split[a][b];"
                 f"[a]scale={width}:{height}:force_original_aspect_ratio=increase,"
                 f"crop={width}:{height},boxblur=24:2[bg];"
                 f"[b]scale={width}:{height}:force_original_aspect_ratio=decrease:"
                 f"force_divisible_by=2[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2")
    elif fit == "bars":
        graph = (f"[0:v]{head},scale={width}:{height}:force_original_aspect_ratio=decrease:"
                 f"force_divisible_by=2,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2")
    else:
        graph = (f"[0:v]{head},scale={width}:{height}:force_original_aspect_ratio=increase,"
                 f"crop={width}:{height}")

    after = [f"fps={seg.get('out_fps', FPS)}", "setsar=1"]
    if FILTERS[seg["filter"]]:
        after.append(FILTERS[seg["filter"]])
    if (seg["brightness"], seg["contrast"], seg["saturation"]) != (0.0, 1.0, 1.0):
        after.append(f"eq=brightness={seg['brightness']:.3f}:contrast={seg['contrast']:.3f}"
                     f":saturation={seg['saturation']:.3f}")
    effect, d = seg["effect"], max(length, 0.1)
    grow = {"zoom in": f"1+0.25*min(t/{d:.3f},1)", "zoom out": f"1.25-0.25*min(t/{d:.3f},1)",
            "zoom punch": "1+0.22*max(0,1-t/0.45)"}.get(effect)
    keys = seg.get("keyframes") or []
    if keys:
        zoom = layers.expression(keys, "zoom")
        px, py = layers.expression(keys, "pan_x"), layers.expression(keys, "pan_y")
        after.append(f"scale=w='2*trunc({width}*({zoom})/2)':h='2*trunc({height}*({zoom})/2)':eval=frame,"
                     f"crop={width}:{height}:x='(iw-{width})*(({px})+1)/2':y='(ih-{height})*(({py})+1)/2'")
    if grow:
        after.append(f"scale=w='2*trunc({width}*({grow})/2)':h='2*trunc({height}*({grow})/2)'"
                     f":eval=frame,crop={width}:{height}:(iw-{width})/2:(ih-{height})/2")
    elif effect == "shake":
        after.append(f"scale={int(width * 1.08) // 2 * 2}:{int(height * 1.08) // 2 * 2},"
                     f"crop={width}:{height}:(iw-{width})/2+sin(t*47)*{width * 0.02:.1f}"
                     f":(ih-{height})/2+cos(t*39)*{height * 0.012:.1f}")
    elif effect == "glitch":
        after.append("rgbashift=rh=14:bh=-14,noise=alls=18:allf=t")
    elif effect == "vhs":
        after.append("rgbashift=rh=5:bh=-5,noise=alls=12:allf=t+u,eq=saturation=1.2:contrast=0.95")
    elif effect == "vignette":
        after.append("vignette=PI/4")
    elif effect == "blur":
        after.append("gblur=sigma=10")
    elif effect == "sharpen":
        after.append("unsharp=5:5:1.2")
    elif effect == "flash":
        after.append("fade=t=in:st=0:d=0.35:color=white")
    elif effect == "pixelate":
        after.append(f"scale={width // 24 * 2}:{height // 24 * 2}:flags=area,"
                     f"scale={width}:{height}:flags=neighbor")
    elif effect == "film grain":
        after.append("noise=alls=22:allf=t+u,eq=contrast=1.05:saturation=0.9")
    elif effect == "mirror split":                  # left half repeated as a reflection
        after.append(f"split[ml][mr];[ml]crop={width // 2}:{height}:0:0[mh];"
                     f"[mr]crop={width // 2}:{height}:0:0,hflip[mf];[mh][mf]hstack")
    elif effect == "edge glow":
        after.append("split[ea][eb];[eb]edgedetect=mode=colormix:high=0.2,gblur=sigma=3[ec];"
                     "[ea][ec]blend=all_mode=screen")
    elif effect == "pulse":
        after.append(f"scale=w='2*trunc({width}*(1.03+0.03*sin(t*8))/2)':"
                     f"h='2*trunc({height}*(1.03+0.03*sin(t*8))/2)':eval=frame,"
                     f"crop={width}:{height}:(iw-{width})/2:(ih-{height})/2")
    elif effect == "spin in":
        after.append("rotate='6.2832*max(0,1-t/0.5)':c=black")
    if seg["fade_in"] > 0:
        after.append(f"fade=t=in:st=0:d={seg['fade_in']:.2f}")
    if seg["fade_out"] > 0:
        after.append(f"fade=t=out:st={max(0.0, length - seg['fade_out']):.2f}:d={seg['fade_out']:.2f}")
    after.append("format=yuv420p")
    return f"{graph},{','.join(after)}[v]"


def audio_filter(seg: dict) -> str:
    """Sound for one piece: same speed, volume and fades as the picture."""
    length = (seg["end"] - seg["start"]) / seg["speed"]
    chain = ["areverse"] if seg["reverse"] else []
    speed = seg["speed"]
    while speed < 0.5:                      # atempo cannot go below 0.5 in one step
        chain.append("atempo=0.5")
        speed /= 0.5
    while speed > 2.0:
        chain.append("atempo=2.0")
        speed /= 2.0
    chain += [f"atempo={speed:.4f}", f"volume={seg['volume']:.3f}"]
    if seg["fade_in"] > 0:
        chain.append(f"afade=t=in:st=0:d={seg['fade_in']:.2f}")
    if seg["fade_out"] > 0:
        chain.append(f"afade=t=out:st={max(0.0, length - seg['fade_out']):.2f}:d={seg['fade_out']:.2f}")
    chain += ["aresample=48000", "aformat=channel_layouts=stereo", "apad"]
    return ",".join(chain)


def _ffmpeg(args: list, cwd=None) -> None:
    done = subprocess.run(["ffmpeg", "-y", "-v", "error", "-nostdin", *args], cwd=cwd,
                          capture_output=True, text=True)
    if done.returncode != 0:
        raise RuntimeError("Video processing failed: " + done.stderr.strip()[-400:])


def _prepare(seg: dict, info: dict, out: Path, fps: int, log) -> tuple:
    """Jobs that need their own pass first: background removal, then curve speed.

    Returns the (possibly changed) piece and the facts about its video.
    """
    if seg.get("bg") and not seg.get("freeze"):
        length = seg["end"] - seg["start"]
        cut = matting.process(seg["source"], seg["start"], length,
                              out.with_name(out.stem + "_bg.mkv"), seg["bg"], fps=fps, log=log)
        seg = {**seg, "source": str(cut), "start": 0.0, "end": length}
        info = ingest.probe(cut)
        seg["end"] = min(seg["end"], info["duration"])
    if seg.get("curve"):
        length = seg["end"] - seg["start"]
        timed = out.with_name(out.stem + "_curve.mkv")
        graph = extras.curve_graph(seg["curve"], length, info["has_audio"], fps)
        _ffmpeg(["-ss", f"{seg['start']:.3f}", "-t", f"{length:.3f}", "-i", seg["source"],
                 "-filter_complex", graph, "-map", "[v]",
                 *(["-map", "[a]", "-c:a", "pcm_s16le"] if info["has_audio"] else []),
                 "-c:v", "libx264", "-preset", "veryfast", "-crf", "14", str(timed)])
        info = ingest.probe(timed)
        seg = {**seg, "source": str(timed), "start": 0.0, "end": info["duration"], "speed": 1.0}
    return seg, info


def render_segment(seg: dict, out: Path, width: int, height: int, fit: str,
                   fps: int = FPS, log=print) -> float:
    """Render one piece; returns its real length in seconds."""
    info = ingest.probe(Path(seg["source"]))
    end = min(seg["end"], info["duration"])
    if end - seg["start"] < 0.2:
        raise ValueError("A piece starts after the end of its video.")
    seg = {**seg, "end": end, "out_fps": fps}
    seg, info = _prepare(seg, info, out, fps, log)
    end = seg["end"]
    if seg.get("freeze"):                                    # take one frame and hold it
        seg["end"] = seg["start"] + seg["freeze"]
        still = out.with_suffix(".png")
        _ffmpeg(["-ss", f"{min(seg['start'], max(0.0, info['duration'] - 0.1)):.3f}", "-i",
                 seg["source"], "-frames:v", "1", str(still)])
        length = seg["freeze"]
        args = ["-loop", "1", "-framerate", str(fps), "-t", f"{length:.3f}", "-i", str(still)]
    else:
        length = (end - seg["start"]) / seg["speed"]
        args = ["-ss", f"{seg['start']:.3f}", "-t", f"{end - seg['start']:.3f}", "-i", seg["source"]]
    graph = segment_filter(seg, width, height, fit)
    if info["has_audio"] and not seg.get("freeze"):
        graph += f";[0:a]{audio_filter(seg)}[a]"
    else:
        args += ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"]
        graph += ";[1:a]anull[a]"
    if seg.get("mask"):                                      # hide everything outside the shape
        extras.draw_mask(width, height, seg["mask"], out.with_suffix(".mask.png"))
        number = args.count("-i")
        args += ["-loop", "1", "-framerate", str(fps), "-i", str(out.with_suffix(".mask.png"))]
        graph = graph.replace("format=yuv420p[v]", "format=gbrp[vm]", 1)
        graph += (f";[{number}:v]format=gbrp[mk];[vm][mk]blend=all_mode=multiply:shortest=1,"
                  f"format=yuv420p[v]")
    _ffmpeg(args + ["-filter_complex", graph, "-map", "[v]", "-map", "[a]", "-t", f"{length:.3f}",
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "16",
                    "-c:a", "aac", "-b:a", "192k", str(out)])
    return ingest.probe(out)["duration"]


def _ass_time(t: float) -> str:
    cs = int(round(t * 100))
    return f"{cs // 360000}:{cs // 6000 % 60:02d}:{cs // 100 % 60:02d}.{cs % 100:02d}"


def build_text_file(texts: list, width: int, height: int) -> str:
    """Subtitle file (ASS) that draws every text box."""
    head = ("[Script Info]\nScriptType: v4.00+\n"
            f"PlayResX: {width}\nPlayResY: {height}\nWrapStyle: 0\n\n[V4+ Styles]\n"
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
            "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, "
            "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n")
    for name, border, outline in (("outline", 1, 5), ("box", 3, 10), ("plain", 1, 0)):
        head += (f"Style: {name},Arial,80,&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,-1,0,0,0,"
                 f"100,100,0,0,{border},{outline},1,5,40,40,40,1\n")
    head += ("\n[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, "
             "Effect, Text\n")
    lines = []
    for t in texts:
        # Remove characters that ASS would read as commands.
        words = t["text"].replace("\\", "/").replace("{", "(").replace("}", ")").replace("\n", "\\N")
        r, g, b = t["color"][0:2], t["color"][2:4], t["color"][4:6]
        tags = f"\\an5\\pos({int(t['x'] * width)},{int(t['y'] * height)})\\fs{int(t['size'])}\\c&H{b}{g}{r}&"
        anim = t.get("anim", "pop" if t.get("pop") else "none")
        if anim == "pop":
            tags += "\\fscx60\\fscy60\\t(0,160,\\fscx100\\fscy100)"
        elif anim == "fade":
            tags += "\\fad(300,300)"
        elif anim in ("slide up", "slide left"):
            x, y = int(t["x"] * width), int(t["y"] * height)
            from_x, from_y = (x, y + height // 8) if anim == "slide up" else (x + width // 4, y)
            tags = tags.replace(f"\\pos({x},{y})", f"\\move({from_x},{from_y},{x},{y},0,250)")
            tags += "\\fad(150,0)"
        lines.append(f"Dialogue: 0,{_ass_time(t['start'])},{_ass_time(t['end'])},{t['style']},,"
                     f"0,0,0,,{{{tags}}}{words}")
    return head + "\n".join(lines) + "\n"


def render(timeline: dict, out_file, log=print, preview: bool = False) -> float:
    """Render the whole timeline to out_file. Returns its length in seconds.

    preview=True makes a small, fast copy to check the look.
    """
    plan = clean(timeline)
    width, height = SIZES[plan["aspect"]]
    shrink = 1 / 3 if preview else plan["resolution"] / 1080
    fps = FPS if preview else plan["fps"]
    if shrink != 1:
        width, height = int(width * shrink) // 2 * 2, int(height * shrink) // 2 * 2
        for t in plan["texts"]:
            t["size"] *= shrink
    out_file = Path(out_file).resolve()
    out_file.parent.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="sf_edit_"))
    try:
        parts, lengths = [], []
        for i, seg in enumerate(plan["segments"], start=1):
            log(f"Preparing piece {i} of {len(plan['segments'])} ...")
            parts.append(work / f"part{i:03d}.mp4")
            lengths.append(render_segment(seg, parts[-1], width, height, plan["fit"], fps, log))

        log("Joining, adding text and music ...")
        args, graph = [], []
        for part in parts:
            args += ["-i", str(part)]
        kind = plan["transition"]["type"]
        fade = min(plan["transition"]["seconds"], min(lengths) * 0.45)
        if len(parts) > 1 and kind != "none":
            video, audio, total = "0:v", "0:a", lengths[0]
            for i in range(1, len(parts)):
                graph.append(f"[{video}][{i}:v]xfade=transition={kind}:duration={fade:.3f}"
                             f":offset={total - fade:.3f}[v{i}]")
                graph.append(f"[{audio}][{i}:a]acrossfade=d={fade:.3f}[a{i}]")
                video, audio, total = f"v{i}", f"a{i}", total + lengths[i] - fade
        else:
            pads = "".join(f"[{i}:v][{i}:a]" for i in range(len(parts)))
            graph.append(f"{pads}concat=n={len(parts)}:v=1:a=1[vc][ac]")
            video, audio, total = "vc", "ac", sum(lengths)

        # Layers on top of the joined video: overlays first, then text above everything.
        extra, parts_graph, video, sounds = layers.overlay_graph(
            plan["overlays"], video, width, height, len(parts), total, work,
            lambda p: ingest.probe(Path(p))["has_audio"], log)
        args += extra
        graph += parts_graph
        next_input = len(parts) + extra.count("-i")
        if plan["texts"]:
            (work / "texts.ass").write_text(build_text_file(plan["texts"], width, height),
                                            encoding="utf-8")
            graph.append(f"[{video}]subtitles=texts.ass[vt]")   # plain name: we run inside `work`
        else:
            graph.append(f"[{video}]null[vt]")
        extra, parts_graph, more = layers.audio_graph(plan["audio"], next_input, total)
        args += extra
        graph += parts_graph
        sounds += more
        next_input += len(more)
        if plan["music"]:
            music = plan["music"]
            args += ["-stream_loop", "-1", "-ss", f"{music['start']:.3f}", "-i",
                     str(Path(music["path"]).resolve())]
            graph.append(f"[{next_input}:a]volume={music['volume']:.3f},aresample=48000,"
                         f"afade=t=out:st={max(0.0, total - 1.0):.3f}:d=1[m]")
            sounds.append("m")
        if sounds:
            mix = "".join(f"[{s}]" for s in [audio, *sounds])
            graph.append(f"{mix}amix=inputs={len(sounds) + 1}:duration=first:normalize=0,"
                         f"alimiter=limit=0.95[at]")
        else:
            graph.append(f"[{audio}]anull[at]")
        cut = []
        if plan["range"]:                        # export only the marked area
            a, b = plan["range"][0], min(plan["range"][1], total)
            if b - a >= 0.2:
                cut, total = ["-ss", f"{a:.3f}"], b - a
        quality = ["-preset", "ultrafast", "-crf", "30"] if preview else ["-preset", "medium", "-crf", "20"]
        _ffmpeg(args + ["-filter_complex", ";".join(graph), "-map", "[vt]", "-map", "[at]",
                        *cut, "-t", f"{total:.3f}", "-c:v", "libx264", *quality, "-pix_fmt", "yuv420p",
                        "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", str(out_file)],
                cwd=work)
        return ingest.probe(out_file)["duration"]
    finally:
        shutil.rmtree(work, ignore_errors=True)
