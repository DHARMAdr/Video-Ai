"""
editor_layers.py - the extra layers of the editor: keyframes, overlays (picture-in-picture,
stickers, green screen) and extra sound tracks.

WHY it exists:
    editor.py renders and joins the main video pieces. Everything that sits ON TOP of that is
    here, so each file stays readable.

HOW it works:
    - A "keyframe" says "at this second the value is this". Between two keyframes ffmpeg gets a
      formula that slides smoothly from one to the other.
    - Every overlay is one more ffmpeg input, laid over the picture only between its start and end.
    - "Green screen" = ffmpeg chromakey: one colour becomes see-through.
    - Stickers are simple shapes this app draws itself (no downloaded artwork).

HOW TO IMPROVE:
    - Curved (ease in / ease out) movement between keyframes.
    - Let the mask itself move with keyframes.
"""

from pathlib import Path

from . import editor_extras as extras
from . import ingest, matting

IMAGE_TYPES = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
VIDEO_TYPES = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"}
STICKERS = ("arrow", "circle", "box", "star", "cross")
MAX_OVERLAYS, MAX_AUDIO, MAX_KEYS = 20, 10, 60


def number(value, default, low, high) -> float:
    try:
        value = float(value)
    except (TypeError, ValueError):
        return default
    return default if value != value else min(high, max(low, value))


def colour(value, default: str = "") -> str:
    text = str(value or "").lstrip("#")
    ok = len(text) == 6 and all(c in "0123456789abcdefABCDEF" for c in text)
    return text.lower() if ok else default


def keyframes(raw, limits: dict) -> list:
    """Safe, time-sorted keyframes. limits: {name: (default, low, high)}."""
    keys = []
    for item in (raw or [])[:MAX_KEYS]:
        if not isinstance(item, dict):
            continue
        key = {"t": round(number(item.get("t"), 0.0, 0.0, 3600.0), 3)}
        for name, (default, low, high) in limits.items():
            key[name] = number(item.get(name), default, low, high)
        keys.append(key)
    keys.sort(key=lambda k: k["t"])
    return keys


def expression(keys: list, name: str, offset: float = 0.0, var: str = "t") -> str:
    """ffmpeg formula that follows the keyframes. offset shifts the times (layer start)."""
    points = [(k["t"] + offset, k[name]) for k in keys]
    result = f"{points[-1][1]:.4f}"
    for (t0, v0), (t1, v1) in zip(reversed(points[:-1]), reversed(points[1:])):
        span = max(t1 - t0, 0.001)
        result = f"if(lt({var},{t1:.3f}),{v0:.4f}+({v1 - v0:.4f})*({var}-{t0:.3f})/{span:.3f},{result})"
    return f"if(lt({var},{points[0][0]:.3f}),{points[0][1]:.4f},{result})"


# ---------------------------------------------------------------------------
# Checking what the window sent
# ---------------------------------------------------------------------------
def clean_overlays(raw) -> list:
    out = []
    for item in (raw or [])[:MAX_OVERLAYS]:
        kind = item.get("kind")
        source = str(item.get("source") or "").strip().strip('"')
        if kind == "sticker":
            if source not in STICKERS:
                raise ValueError("Unknown sticker.")
        elif kind in ("image", "video"):
            allowed = IMAGE_TYPES if kind == "image" else VIDEO_TYPES
            if Path(source).suffix.lower() not in allowed or not Path(source).is_file():
                raise ValueError(f"Overlay file not found: {source or '(empty)'}")
        else:
            raise ValueError("Unknown overlay type.")
        start = number(item.get("start"), 0.0, 0.0, 600.0)
        base = {"x": number(item.get("x"), 0.5, -0.5, 1.5), "y": number(item.get("y"), 0.5, -0.5, 1.5),
                "scale": number(item.get("scale"), 0.4, 0.03, 3.0)}
        out.append({"kind": kind, "source": source, "start": start,
                    "end": number(item.get("end"), start + 3, start + 0.1, 605.0),
                    "src_start": number(item.get("src_start"), 0.0, 0.0, 1e6), **base,
                    "opacity": number(item.get("opacity"), 1.0, 0.05, 1.0),
                    "rotate": number(item.get("rotate"), 0.0, -360.0, 360.0),
                    "mirror": bool(item.get("mirror")), "chroma": colour(item.get("chroma")),
                    "similarity": number(item.get("similarity"), 0.18, 0.01, 0.6),
                    "color": colour(item.get("color"), "ffe14d"),
                    "volume": number(item.get("volume"), 0.0, 0.0, 2.0),
                    "fade_in": number(item.get("fade_in"), 0.0, 0.0, 5.0),
                    "fade_out": number(item.get("fade_out"), 0.0, 0.0, 5.0),
                    "mask": extras.clean_mask(item.get("mask"), number),
                    "blend": item.get("blend") if item.get("blend") in extras.BLENDS else "normal",
                    "remove_bg": bool(item.get("remove_bg")) and kind != "sticker",
                    "keyframes": keyframes(item.get("keyframes"), {
                        "x": (base["x"], -0.5, 1.5), "y": (base["y"], -0.5, 1.5),
                        "scale": (base["scale"], 0.03, 3.0)})})
    return out


def clean_audio(raw, audio_types, video_types=VIDEO_TYPES) -> list:
    out = []
    for item in (raw or [])[:MAX_AUDIO]:
        path = str(item.get("path") or "").strip().strip('"')
        if Path(path).suffix.lower() not in (set(audio_types) | set(video_types)) or not Path(path).is_file():
            raise ValueError("A sound file was not found.")
        start = number(item.get("start"), 0.0, 0.0, 600.0)
        out.append({"path": path, "start": start,
                    "end": number(item.get("end"), 600.0, start + 0.1, 605.0),
                    "src_start": number(item.get("src_start"), 0.0, 0.0, 1e6),
                    "volume": number(item.get("volume"), 1.0, 0.0, 3.0),
                    "fade_in": number(item.get("fade_in"), 0.0, 0.0, 10.0),
                    "fade_out": number(item.get("fade_out"), 0.0, 0.0, 10.0)})
    return out


# ---------------------------------------------------------------------------
# Drawing stickers
# ---------------------------------------------------------------------------
def draw_sticker(name: str, rgb: str, path: Path, size: int = 400) -> None:
    """Draw one shape with a see-through background and save it as PNG."""
    import cv2
    import numpy as np
    picture = np.zeros((size, size, 4), np.uint8)
    ink = (int(rgb[4:6], 16), int(rgb[2:4], 16), int(rgb[0:2], 16), 255)     # blue, green, red
    s, thick = size, size // 12
    if name == "arrow":
        points = np.array([[0.05, 0.38], [0.58, 0.38], [0.58, 0.18], [0.95, 0.5], [0.58, 0.82],
                           [0.58, 0.62], [0.05, 0.62]]) * s
        cv2.fillPoly(picture, [points.astype(np.int32)], ink, cv2.LINE_AA)
    elif name == "circle":
        cv2.circle(picture, (s // 2, s // 2), s // 2 - thick, ink, thick, cv2.LINE_AA)
    elif name == "box":
        cv2.rectangle(picture, (thick, thick), (s - thick, s - thick), ink, thick)
    elif name == "star":
        angles = np.arange(10) * np.pi / 5 - np.pi / 2
        radius = np.where(np.arange(10) % 2 == 0, 0.48, 0.2) * s
        points = np.stack([s / 2 + radius * np.cos(angles), s / 2 + radius * np.sin(angles)], axis=1)
        cv2.fillPoly(picture, [points.astype(np.int32)], ink, cv2.LINE_AA)
    else:                                                            # cross
        cv2.line(picture, (thick, thick), (s - thick, s - thick), ink, thick, cv2.LINE_AA)
        cv2.line(picture, (s - thick, thick), (thick, s - thick), ink, thick, cv2.LINE_AA)
    ok, data = cv2.imencode(".png", picture)
    if not ok:
        raise RuntimeError("Could not draw the sticker.")
    path.write_bytes(data.tobytes())


# ---------------------------------------------------------------------------
# Turning layers into ffmpeg inputs and filters
# ---------------------------------------------------------------------------
def overlay_graph(overlays: list, video: str, width: int, height: int, first_input: int,
                  total: float, work: Path, has_audio, log=print) -> tuple:
    """Returns (input_args, filter_parts, name_of_result_stream, sound_streams).

    has_audio(path) -> bool tells whether a video overlay carries sound.
    """
    args, graph, sounds = [], [], []
    index = first_input
    for number_, o in enumerate(overlays):
        start, end = o["start"], min(o["end"], total)
        if end - start < 0.05:
            continue
        length = end - start
        source = o["source"]
        if o["kind"] == "sticker":
            source = str(work / f"sticker{number_}.png")
            draw_sticker(o["source"], o["color"], Path(source))
        sound_input = None
        if o["remove_bg"]:                  # make a see-through copy of the person first
            offset = o["src_start"] if o["kind"] == "video" else 0.0
            cut = matting.process(source, offset, length, work / f"cut{number_}.mkv",
                                  "transparent", log=log)
            args += ["-i", str(cut)]
            if o["kind"] == "video" and o["volume"] > 0 and has_audio(source):
                sound_input = index
        elif o["kind"] == "video":
            args += ["-ss", f"{o['src_start']:.3f}", "-t", f"{length:.3f}", "-i",
                     str(Path(source).resolve())]
            if o["volume"] > 0 and has_audio(source):
                sound_input = index
        else:
            args += ["-loop", "1", "-framerate", "30", "-t", f"{length:.3f}", "-i",
                     str(Path(source).resolve())]
        picture_input = index
        index += 1
        mask_input = None
        if o["mask"]:
            mask_input = index
            index += 1
        keys = o["keyframes"]
        moving = len(keys) > 1                                  # animated by keyframes?
        values = [k["scale"] for k in keys] if keys else [o["scale"]]
        biggest = max(values)
        x = f"({expression(keys, 'x', start)})" if moving else f"{(keys[0] if keys else o)['x']:.4f}"
        y = f"({expression(keys, 'y', start)})" if moving else f"{(keys[0] if keys else o)['y']:.4f}"
        chain = [f"setpts=PTS-STARTPTS+{start:.3f}/TB", "fps=30"]
        if o["chroma"]:
            chain.append(f"chromakey=0x{o['chroma']}:{o['similarity']:.3f}:0.06")
        chain.append("format=rgba")
        # First one fixed size (the biggest the layer ever gets) ...
        if o["mask"]:
            # The mask must be exactly as big as the layer, so work the size out here.
            info = ingest.probe(Path(source))
            wide = max(2, 2 * int(width * biggest / 2))
            tall = max(2, 2 * round(wide * info["height"] / info["width"] / 2))
            extras.draw_mask(wide, tall, o["mask"], work / f"mask{number_}.png")
            args += ["-loop", "1", "-framerate", "30", "-t", f"{length:.3f}", "-i",
                     str((work / f"mask{number_}.png").resolve())]
            graph.append(f"[{picture_input}:v]{','.join(chain)},scale={wide}:{tall},"
                         f"split[mc{number_}][ma{number_}]")
            graph.append(f"[ma{number_}]alphaextract[al{number_}]")
            graph.append(f"[{mask_input}:v]format=gray,"
                         f"setpts=PTS-STARTPTS+{start:.3f}/TB[mg{number_}]")
            graph.append(f"[al{number_}][mg{number_}]blend=all_mode=multiply:"
                         f"repeatlast=1[mm{number_}]")
            head, chain = f"[mc{number_}][mm{number_}]", ["alphamerge"]
        else:
            chain.append(f"scale=w='max(2,2*trunc({width}*{biggest:.4f}/2))':h=-2")
            head = f"[{picture_input}:v]"
        if o["mirror"]:
            chain.append("hflip")
        if abs(o["rotate"]) > 0.01:
            angle = o["rotate"] * 3.14159265 / 180
            chain.append(f"rotate={angle:.5f}:ow='hypot(iw,ih)':oh=ow:c=black@0")
        if o["opacity"] < 0.999:
            chain.append(f"colorchannelmixer=aa={o['opacity']:.3f}")
        if o["fade_in"] > 0:
            chain.append(f"fade=t=in:st={start:.3f}:d={o['fade_in']:.2f}:alpha=1")
        if o["fade_out"] > 0:
            chain.append(f"fade=t=out:st={max(start, end - o['fade_out']):.3f}:d={o['fade_out']:.2f}:alpha=1")
        # ... and the changing size LAST: newer FFmpeg stops with an error when any filter
        # other than "overlay" receives pictures whose size changes.
        if moving:
            share = f"(({expression(keys, 'scale', start)})/{biggest:.4f})"
            chain.append(f"scale=w='max(2,2*trunc(iw*{share}/2))':h=-2:eval=frame")
        graph.append(f"{head}{','.join(chain)}[ov{number_}]")
        where = (f"x='W*{x}-w/2':y='H*{y}-h/2':eval=frame:eof_action=pass:"
                 f"enable='between(t,{start:.3f},{end:.3f})'")
        if o["blend"] == "normal":
            graph.append(f"[{video}][ov{number_}]overlay={where}[base{number_}]")
            video = f"base{number_}"
        else:
            parts, video = extras.blend_graph(o["blend"], video, f"ov{number_}", number_,
                                              width, height, total, where)
            graph += parts
        if sound_input is not None:
            delay = int(start * 1000)
            graph.append(f"[{sound_input}:a]volume={o['volume']:.3f},aresample=48000,"
                         f"aformat=channel_layouts=stereo,adelay={delay}:all=1[ova{number_}]")
            sounds.append(f"ova{number_}")
    return args, graph, video, sounds


def audio_graph(tracks: list, first_input: int, total: float) -> tuple:
    """Returns (input_args, filter_parts, sound_streams) for the extra sound tracks."""
    args, graph, sounds = [], [], []
    index = first_input
    for number_, a in enumerate(tracks):
        start, end = a["start"], min(a["end"], total)
        if end - start < 0.05:
            continue
        length = end - start
        args += ["-ss", f"{a['src_start']:.3f}", "-t", f"{length:.3f}", "-i", str(Path(a["path"]).resolve())]
        chain = [f"volume={a['volume']:.3f}", "aresample=48000", "aformat=channel_layouts=stereo"]
        if a["fade_in"] > 0:
            chain.append(f"afade=t=in:st=0:d={a['fade_in']:.2f}")
        if a["fade_out"] > 0:
            chain.append(f"afade=t=out:st={max(0.0, length - a['fade_out']):.2f}:d={a['fade_out']:.2f}")
        chain.append(f"adelay={int(start * 1000)}:all=1")
        graph.append(f"[{index}:a]{','.join(chain)}[au{number_}]")
        sounds.append(f"au{number_}")
        index += 1
    return args, graph, sounds
