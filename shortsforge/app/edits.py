"""
edits.py - the app side of the editor: saving the draft, exporting, and quick edits of clips.

WHY it exists:
    editor.py only renders. This file decides where results go (a project called "Edits", so
    they show in the Clips tab), keeps your draft, and lets the assistant do edits by words.

HOW it works:
    - export(): renders into Documents/ShortsForge/Edits/clips and adds a line to shorts.json.
    - delete_clip() / restore_clip(): deleted clips move to a "_deleted" folder, so a wrong
      command can be undone.

HOW TO IMPROVE:
    - Keep several named drafts.
"""

import json
import time
from pathlib import Path

from .. import editor, ingest

EDITS = "Edits"


def _read(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def save_draft(out_dir, draft: dict) -> None:
    folder = Path(out_dir) / "_editor"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "draft.json").write_text(json.dumps(draft), encoding="utf-8")


def load_draft(out_dir) -> dict:
    return _read(Path(out_dir) / "_editor" / "draft.json", {})


def export(out_dir, timeline: dict, title: str = "", log=print, preview: bool = False) -> dict:
    """Render a timeline. Returns {'file': relative path, 'seconds': n, 'project_name': 'Edits'}."""
    out_dir = Path(out_dir)
    if preview:
        target = out_dir / "_editor" / "preview.mp4"
        seconds = editor.render(timeline, target, log=log, preview=True)
        return {"file": "_editor/preview.mp4", "seconds": round(seconds, 2)}
    project = out_dir / EDITS
    entries = _read(project / "shorts.json", [])
    number = 1
    while (project / "clips" / f"edit_{number:03d}.mp4").exists():
        number += 1
    name = f"edit_{number:03d}.mp4"
    seconds = editor.render(timeline, project / "clips" / name, log=log)
    title = str(title or "").strip()[:90] or f"Edit {number}"
    entries.append({"file": name, "start": 0.0, "end": round(seconds, 2), "title": title,
                    "hashtags": ["#shorts", "#reels"], "text": "", "made": time.time(),
                    "score": {"total": 0, "base": 0, "speed": 0, "energy": 0,
                              "reasons": ["made in the editor"]}})
    (project / "shorts.json").write_text(json.dumps(entries, indent=1), encoding="utf-8")
    return {"file": f"{EDITS}/clips/{name}", "seconds": round(seconds, 2), "project_name": EDITS}


def timeline_words(plan: dict, words_of) -> list:
    """Spoken words moved to their time on the finished timeline.

    words_of(source) -> [{"word","start","end"}] with times inside that source video.
    """
    fade = plan["transition"]["seconds"] if plan["transition"]["type"] != "none" else 0.0
    out, offset = [], 0.0
    for seg in plan["segments"]:
        source_length = seg["end"] - seg["start"]
        curve = seg.get("curve", "")
        length = source_length / seg["speed"] * editor.extras.curve_factor(curve)

        def moved(t):                              # source seconds into the piece -> output
            return (editor.extras.curve_time(curve, t, source_length) if curve
                    else t / seg["speed"])

        if not seg.get("freeze") and not seg["reverse"] and seg["volume"] > 0:
            for w in words_of(seg["source"]):
                if seg["start"] - 0.05 <= w["start"] < seg["end"]:
                    a = offset + moved(max(0.0, w["start"] - seg["start"]))
                    b = offset + moved(min(w["end"], seg["end"]) - seg["start"])
                    out.append({"word": w["word"], "start": round(a, 2), "end": round(max(a + 0.05, b), 2)})
        offset += length - fade
    return out


def group_captions(words: list, size: int = 3, pause: float = 0.7) -> list:
    """Short caption lines of a few words, broken at pauses."""
    lines = []
    for w in words:
        last = lines[-1] if lines else None
        if last and last["count"] < size and w["start"] - last["end"] <= pause:
            last["text"] += " " + w["word"]
            last["end"], last["count"] = w["end"], last["count"] + 1
        else:
            lines.append({"text": w["word"], "start": w["start"], "end": w["end"], "count": 1})
    return [{"text": l["text"], "start": l["start"], "end": max(l["end"], l["start"] + 0.3)}
            for l in lines][:editor.MAX_TEXTS]


def captions(out_dir, plan: dict, log=print, transcriber=None) -> list:
    """Auto captions for the whole timeline (offline speech recognition)."""
    from ..find import engine, speech
    if transcriber is None:
        from ..transcribe import transcribe as transcriber
    cache = {}

    def words_of(source):
        if source not in cache:
            log(f"Writing down the speech of {Path(source).name} ...")
            work = engine.work_folder(out_dir, source)
            work.mkdir(parents=True, exist_ok=True)
            cache[source] = speech.flat_words(transcriber(Path(source), work))
        return cache[source]

    result = group_captions(timeline_words(plan, words_of))
    if not result:
        raise ValueError("No speech was found in the timeline.")
    return result


def clip_path(project: Path, number: int) -> Path:
    """File of clip `number` (starting at 1) of a project folder."""
    entries = _read(project / "shorts.json", [])
    if not 1 <= number <= len(entries):
        raise ValueError(f"There is no clip {number}. This project has {len(entries)}.")
    path = project / "clips" / entries[number - 1]["file"]
    if not path.is_file():
        raise ValueError("That clip file is missing.")
    return path


def timeline_for_clips(project: Path, numbers: list, changes: dict = None, text: str = "",
                       transition: str = "none", music: str = "") -> dict:
    """A timeline made of finished clips, with the same changes applied to each."""
    changes = {k: v for k, v in (changes or {}).items() if v not in (None, "")}
    segments, lengths = [], []
    for number in numbers:
        path = clip_path(project, int(number))
        length = ingest.probe(path)["duration"]
        lengths.append(length / float(changes.get("speed") or 1))
        segments.append({"source": str(path), "start": 0.0, "end": length, **changes})
    if not segments:
        raise ValueError("Say which clips to use.")
    timeline = {"aspect": "9:16", "fit": "crop", "segments": segments,
                "transition": {"type": transition or "none", "seconds": 0.5}, "texts": []}
    if text:
        timeline["texts"] = [{"text": text, "start": 0.0, "end": min(4.0, sum(lengths)),
                              "y": 0.18, "size": 90, "color": "#ffe14d"}]
    if music:
        timeline["music"] = {"path": music, "volume": 0.35}
    return timeline


def delete_clip(project: Path, number: int) -> dict:
    """Move a clip out of the list (it can be restored)."""
    entries = _read(project / "shorts.json", [])
    if not 1 <= number <= len(entries):
        raise ValueError(f"There is no clip {number}. This project has {len(entries)}.")
    entry = entries.pop(number - 1)
    trash = project / "_deleted"
    trash.mkdir(exist_ok=True)
    source = project / "clips" / entry["file"]
    stored = f"{int(time.time() * 1000)}_{entry['file']}"
    if source.is_file():
        source.replace(trash / stored)
    removed = _read(trash / "list.json", [])
    removed.append({"stored": stored, "entry": entry})
    (trash / "list.json").write_text(json.dumps(removed), encoding="utf-8")
    (project / "shorts.json").write_text(json.dumps(entries, indent=1), encoding="utf-8")
    return entry


def restore_clip(project: Path) -> dict:
    """Bring back the clip deleted last."""
    trash = project / "_deleted"
    removed = _read(trash / "list.json", [])
    if not removed:
        raise ValueError("There is no deleted clip to bring back.")
    item = removed.pop()
    entry = item["entry"]
    entries = _read(project / "shorts.json", [])
    target = project / "clips" / entry["file"]
    if target.exists():                      # its number was reused meanwhile
        entry["file"] = f"restored_{item['stored']}"
        target = project / "clips" / entry["file"]
    if (trash / item["stored"]).is_file():
        target.parent.mkdir(exist_ok=True)
        (trash / item["stored"]).replace(target)
    entries.append(entry)
    (project / "shorts.json").write_text(json.dumps(entries, indent=1), encoding="utf-8")
    (trash / "list.json").write_text(json.dumps(removed), encoding="utf-8")
    return entry
