"""
engine.py - runs one search from sentence to moments, and cuts the chosen moments into clips.

WHY it exists:
    The other files each do one job. This file decides which jobs a sentence needs, runs them,
    combines the answers, and always says what it could NOT check.

HOW it works:
    1. query.parse reads your sentence.
    2. Each needed clue is collected (kill feed, taught pictures, speech, loudness, picture AI).
       If something is missing (no taught picture, no AI) it is added to "problems" in words
       you can act on - the search never pretends to have checked it.
    3. moments.merge / require / bounds turn clues into clips.
    4. make_clips() renders the moments you ticked into a project in the Clips tab.

HOW TO IMPROVE:
    - Cache each clue per video so a second search is instant.
"""

import hashlib
import json
from pathlib import Path

from .. import analyze, ingest
from . import feed, moments, pictures, query, speech, vision, video as videos

DEFAULT_LIMIT = 8


def work_folder(root, video) -> Path:
    """A private cache folder for one video (the same file always maps to the same folder)."""
    stat = Path(video).stat()
    key = f"{Path(video).resolve()}|{stat.st_size}|{int(stat.st_mtime)}"
    return pictures.folder(root) / "cache" / hashlib.md5(key.encode()).hexdigest()[:12]


def time_window(span: dict, duration: float) -> tuple:
    if span.get("last"):
        return max(0.0, duration - span["last"]), duration
    start = min(duration, span.get("from") or 0.0)
    end = duration if span.get("to") is None else min(duration, span["to"])
    if end - start < 1.0:
        raise ValueError("That time range is empty for this video.")
    return start, end


def loud_hits(video, start: float, end: float, count: int = 12) -> list:
    """The loudest seconds."""
    hop, rms = analyze.audio_energy(Path(video))
    top = float(rms.max()) if len(rms) else 0.0
    if top <= 0.01:
        return []
    order = sorted(((float(v), i * hop) for i, v in enumerate(rms) if start <= i * hop <= end), reverse=True)
    picked = []
    for value, t in order:
        if value < top * 0.5 or len(picked) >= count:
            break
        if all(abs(t - p[1]) > 8 for p in picked):
            picked.append((value, t))
    return [moments.hit(t, 0.4 + 0.5 * value / top, "loud", "loud moment") for value, t in picked]


def _kill_hits(root, video, info, plan, work, start, end, problems, log) -> list:
    """Clues from the kill feed for kill / death searches."""
    agent_names = [n for n in (plan["killer"], plan["victim"]) if n and n != "me"]
    have = {n.lower() for n in pictures.names(root)}
    missing = [n for n in agent_names if n.lower() not in have]
    for name in missing:
        problems.append(f"I don't know what {name} looks like yet. In the Find tab, pause where "
                        f"{name}'s icon is in the kill feed, draw a box around it and name it {name}.")
    if missing:
        return []
    mine = []
    needs_mine = plan["killer"] == "me" or (plan["multi"] and plan["killer"] in (None, "me"))
    if needs_mine:
        mine = [t for t in feed.my_kill_times(root, video, info, work, log=log) if start <= t <= end]
        if not mine:
            problems.append("I could not confirm any of your kills. Use the Teach tab so the app "
                            "knows what your kills look like.")
            return []
    if plan["death"] and not agent_names:
        problems.append("To find your deaths, add a picture of something that only appears when "
                        "you die (for example the combat report) and name it 'death', then search "
                        "again - or use the picture AI.")
        return []
    events = feed.scan_icons(root, video, info, agent_names, start, end, log=log) if agent_names else []

    if agent_names:
        found = feed.match_relation(plan, events, mine)
        if plan["multi"]:
            chains = feed.group_multi([f[0] for f in found], plan["multi"])
            return [moments.hit(a, 0.9, "feed", f"{n} matching kills", end=b) for a, b, n in chains]
        return [moments.hit(t, score, "feed", why) for t, score, why in found]
    if plan["multi"]:
        return [moments.hit(a, 0.9, "feed", f"{n} kills in a row", end=b)
                for a, b, n in feed.group_multi(mine, plan["multi"])]
    return [moments.hit(t, 0.85, "feed", "your kill") for t in mine]


def search(root, video, sentence: str, log=print, look=None, transcriber=None,
           limit: int = DEFAULT_LIMIT, thumbnails: bool = True) -> dict:
    """Run a search.

    look(system, question, image_url) -> text : the picture AI (None = not available)
    transcriber(video, work_dir) -> transcript : speech recognition (None = default)
    Returns {'understood', 'problems', 'notes', 'moments': [...], 'video'}.
    """
    video = Path(video)
    if not video.is_file():
        raise ValueError(f"Video not found: {video}")
    info = ingest.probe(video)
    plan = query.parse(sentence, pictures.names(root))
    understood = query.explain(plan)
    log(understood)
    start, end = time_window(plan["range"], info["duration"])
    work = work_folder(root, video)
    work.mkdir(parents=True, exist_ok=True)
    hits, problems, needed = [], [], []

    taught = {n.lower(): n for n in pictures.names(root)}
    character_names = {str(n).lower() for n in (plan["killer"], plan["victim"]) if n}
    if plan["kill"] or plan["death"] or plan["multi"]:
        if not (plan["death"] and "death" in taught and plan["killer"] is None):
            hits += _kill_hits(root, video, info, plan, work, start, end, problems, log)
            needed.append("feed")
        else:
            hits += pictures.scan_scene(root, video, info, taught["death"], start, end, log=log)
            needed.append("picture")

    # Taught pictures named in the sentence (but not the characters handled above).
    for name in plan["pictures"]:
        if name.lower() in character_names:
            continue
        scene = pictures.scan_scene(root, video, info, name, start, end, log=log)
        icons = feed.scan_icons(root, video, info, [name], start, end, log=log)
        hits += scene + [moments.hit(e["t"], e["score"], "feed" if "feed" in needed else "picture",
                                     f"'{name}' in the kill feed") for e in icons]
        if "feed" not in needed:
            needed.append("picture")

    if plan["said"]:
        log("Writing down the speech (this is slow the first time) ...")
        if transcriber is None:
            from ..transcribe import transcribe as transcriber
        try:
            spoken = speech.search(transcriber(video, work), plan["said"])
            hits += [h for h in spoken if start <= h["t"] <= end]
            needed.append("speech")
        except Exception as exc:                                    # noqa: BLE001
            problems.append(f"Speech search did not work: {exc}")

    if plan["loud"]:
        hits += loud_hits(video, start, end)
        needed.append("loud")

    if plan["description"]:
        if look is None:
            problems.append("Looking for a described scene needs the picture AI: open Settings > "
                            "Built-in AI, download a model and its 'picture reader'.")
        else:
            try:
                if "feed" in needed and hits:
                    # Only look around the kills already found - far faster than the whole video.
                    seen = []
                    for h in list(hits)[:40]:
                        seen += vision.search(look, video, info, plan["description"],
                                              max(start, h["t"] - 3), min(end, h["t"] + 3), log=log, step=2.0)
                    hits += seen
                else:
                    hits += vision.search(look, video, info, plan["description"], start, end, log=log)
                needed.append("vision")
            except Exception as exc:                                # noqa: BLE001
                problems.append(f"The picture AI could not run: {exc}")

    groups = moments.merge(hits)
    # Every kind of clue you asked for must be present in the same moment.
    groups = moments.require(groups, needed)
    chosen = moments.choose(groups, plan["limit"] or limit, plan["which"])
    cuts = []
    if chosen and not plan["length"]:
        for g in chosen:
            cuts += videos.shot_changes(video, info, max(0.0, g["first"] - 7), min(info["duration"], g["last"] + 7))
    results = []
    for number, g in enumerate(chosen, start=1):
        a, b = moments.bounds(g, info["duration"], plan["length"], sorted(set(cuts)))
        item = {"n": number, "start": a, "end": b, "at": round(g["first"], 2),
                "confidence": int(round(g["confidence"] * 100)), "why": g["why"], "thumb": None}
        if thumbnails:
            picture = videos.frame_at(video, info, g["first"] + 0.3, 320)
            if picture is not None:
                name = f"thumb_{number:02d}.jpg"
                (work / name).write_bytes(videos.jpeg_bytes(picture, 80))
                item["thumb"] = (work / name).relative_to(Path(root)).as_posix()
        results.append(item)
    if not results and not problems:
        problems.append("Nothing in this video matched. Try other words, add an example picture, "
                        "or widen the time range.")
    log(f"Found {len(results)} moment(s).")
    answer = {"video": str(video.resolve()), "query": plan["text"], "understood": understood,
              "notes": plan["notes"], "problems": problems, "moments": results,
              "kill_search": bool(plan["kill"] or plan["death"] or plan["multi"])}
    (pictures.folder(root) / "last.json").write_text(json.dumps(answer, indent=1), encoding="utf-8")
    return answer


def last(root) -> dict:
    try:
        return json.loads((pictures.folder(root) / "last.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def make_clips(root, video, chosen: list, title: str = "", layout: str = "auto", log=print,
               kill_search: bool = True) -> dict:
    """Cut the moments [{'start','end'}] into vertical clips in the Clips tab."""
    from .. import pipeline
    video = Path(video)
    if not video.is_file():
        raise ValueError("The video is no longer there.")
    if not chosen:
        raise ValueError("Tick at least one moment.")
    if layout not in ("auto", "center", "blur", "face"):
        layout = "auto"
    base = pipeline._safe_name(video.stem) + "_found"
    project = Path(root) / base
    meta_file = project / "project.json"
    number = 2
    while meta_file.exists() and json.loads(meta_file.read_text("utf-8")).get("video") != str(video.resolve()):
        project = Path(root) / f"{base}{number}"
        meta_file = project / "project.json"
        number += 1
    (project / "work").mkdir(parents=True, exist_ok=True)
    info = ingest.probe(video)
    if kill_search and layout in ("auto", "center", "blur"):
        meta = {"mode": "game", "game": "valorant", "layout": "blur" if layout == "blur" else "center",
                "facecam": None, "with_popups": False, "hook_title": False,
                "popup": {"seconds": 1.4, "y": 780}, "words_file": None}
    else:
        meta = {"mode": "talk", "reframe": layout, "captions": False, "hook_title": False,
                "words_file": None}
    meta.update({"video": str(video.resolve()), "duration": info["duration"]})
    meta_file.write_text(json.dumps(meta, indent=1), encoding="utf-8")
    if not (project / "shorts.json").exists():
        (project / "shorts.json").write_text("[]", encoding="utf-8")
    made = []
    for i, m in enumerate(chosen[:20], start=1):
        name = f"{(title or 'Found moment').strip()[:60]} {i}"
        made.append(pipeline.add_clip(project, float(m["start"]), float(m["end"]), name, log=log))
    return {"project_name": project.name, "count": len(made)}
