"""
pipeline.py - the conductor: runs every step in order from video to finished shorts.

WHY it exists:
    Each module does one small job. This file connects them so the user needs ONE command.
    Keeping the order in one place makes it easy to add or remove a step later.

HOW it works (the steps):
    1. ingest     get the video (download or local) and read its size/length
    2. transcribe speech -> words with times (cached)
    3. analyze    loudness + scene cuts (cached)
    4. candidates every sentence-aligned clip between min and max seconds
    5. score      0-100 per candidate using the viral profile
    6. (optional) a local LLM re-rates the best candidates
    7. pick       best non-overlapping clips
    8. render     reframe 9:16 + captions + loudness -> MP4, plus a .json and a report.md

HOW TO IMPROVE:
    - Run render jobs in parallel; add a progress bar.
    - Add a review step (a small web page) where you approve clips before rendering.
    - Add auto-upload (YouTube Data API) after rendering.
"""

import hashlib
import json
import re
from pathlib import Path

from . import (analyze, captions, highlights, ingest, killfeed, llm, metadata, reframe,
               render, scoring, segments)
from .config import load_game_profile, load_profile
from .transcribe import transcribe

PAD_START, PAD_END = 0.25, 0.40   # small breathing room so words are not clipped


def _safe_name(text: str) -> str:
    """Make a string safe to use as a folder name."""
    return re.sub(r"[^A-Za-z0-9_-]+", "_", text).strip("_")[:50] or "video"


def _open_source(source: str, out_root: str, log):
    """Get the video (download if it is a link), make folders, read its info.
    Returns (video_path, project_folder, work_folder, info). Shared by both modes."""
    if ingest.is_url(source):
        project = Path(out_root) / ("url_" + hashlib.md5(source.encode()).hexdigest()[:8])
        log("Downloading video ...")
        video = ingest.download(source, project / "work")
    else:
        video = Path(source)
        if not video.exists():
            raise FileNotFoundError(f"Video not found: {video}")
        project = Path(out_root) / _safe_name(video.stem)
    work = project / "work"
    work.mkdir(parents=True, exist_ok=True)
    info = ingest.probe(video)
    log(f"Video: {info['width']}x{info['height']}, {info['duration']:.0f}s")
    return video, project, work, info


def run(source: str, out_root: str = "output", count: int = 5, model: str = "small",
        reframe_mode: str = "auto", with_captions: bool = True, hook_title: bool = True,
        llm_model=None, profile_path=None, language=None, dry_run: bool = False,
        transcript_file=None, log=print) -> dict:
    """Run the whole pipeline. Returns a dict with the chosen clips."""
    profile = load_profile(profile_path)

    # ---- 1. ingest ---------------------------------------------------------
    video, project, work, info = _open_source(source, out_root, log)

    # ---- 2. transcript -----------------------------------------------------
    if transcript_file:                                   # user supplied their own
        transcript = json.loads(Path(transcript_file).read_text(encoding="utf-8"))
    else:
        log("Transcribing speech (first run downloads the model) ...")
        transcript = transcribe(video, work, model_size=model, language=language)
    sentences = segments.to_sentences(transcript)
    log(f"Found {len(sentences)} sentences.")

    # ---- 3. signals (cached) ----------------------------------------------
    cache = work / "signals.json"
    if cache.exists():
        signals = analyze.Signals.from_dict(json.loads(cache.read_text()))
    else:
        log("Measuring audio energy and scene cuts ...")
        signals = analyze.compute_signals(video)
        cache.write_text(json.dumps(signals.to_dict()))

    # ---- 4 + 5. candidates and scores -------------------------------------
    candidates = segments.build_candidates(sentences, profile)
    log(f"Scoring {len(candidates)} candidate clips ...")
    for cand in candidates:
        cand["score"] = scoring.score_candidate(cand, signals, profile)
    if not candidates:
        raise RuntimeError("No clips of the right length were found. Is there speech in the "
                           "video? Try lowering min_seconds in viral_profile.json.")

    # ---- 6. optional LLM re-rating ----------------------------------------
    if llm_model:
        log(f"Asking local LLM ({llm_model}) to re-rate the top clips ...")
        top = sorted(candidates, key=lambda c: c["score"]["total"], reverse=True)[:count * 3]
        for cand in top:
            rating = llm.rate_clip(cand["text"], llm_model)
            if rating is not None:
                cand["score"]["llm"] = rating
                # 70% rules + 30% LLM opinion (rating is 1-10 so multiply by 10)
                cand["score"]["total"] = round(0.7 * cand["score"]["total"] + 3.0 * rating, 1)

    # ---- 7. pick -----------------------------------------------------------
    chosen = segments.pick_top(candidates, count)
    log(f"Selected {len(chosen)} shorts.")

    # ---- 8. render ---------------------------------------------------------
    meta = {"mode": "talk", "video": str(Path(video).resolve()), "duration": info["duration"],
            "reframe": reframe_mode, "captions": with_captions, "hook_title": hook_title,
            "words_file": str(work / "transcript.json")}
    if transcript_file:     # keep the transcript inside the project so re-exports can use it
        (work / "transcript.json").write_text(json.dumps(transcript), encoding="utf-8")
    results = []
    for n, cand in enumerate(chosen, start=1):
        start = max(0.0, cand["start"] - PAD_START)
        end = min(info["duration"], cand["end"] + PAD_END)
        title = (llm.make_title(cand["text"], llm_model) if llm_model else None) \
            or metadata.make_title(cand["first_sentence"])
        entry = {
            "file": f"short_{n:02d}.mp4", "start": round(start, 2), "end": round(end, 2),
            "score": cand["score"], "title": title,
            "hashtags": metadata.make_hashtags(cand["text"]), "text": cand["text"],
        }
        if not dry_run:
            log(f"Rendering short {n}/{len(chosen)}  ({start:.0f}s-{end:.0f}s, "
                f"score {cand['score']['total']}) ...")
            _render_short(meta, info, profile, project, entry, start, end, title)
        results.append(entry)
    (project / "project.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")

    _write_report(project, source, results, candidates, dry_run)
    (project / "shorts.json").write_text(json.dumps(results, indent=1), encoding="utf-8")
    log(f"Done. Open: {project.resolve()}")
    return {"project": str(project), "shorts": results}


def _write_report(project: Path, source: str, results: list, candidates: list, dry: bool):
    """Write a human-readable report.md so you can see WHY each clip was chosen."""
    lines = [f"# ShortsForge report\n", f"Source: `{source}`\n",
             "(dry run - nothing was rendered)\n" if dry else ""]
    for r in results:
        s = r["score"]
        lines += [
            f"## {r['file']} - score {s['total']}",
            f"- Time: {r['start']}s to {r['end']}s",
            f"- Title idea: {r['title']}",
            f"- Hashtags: {' '.join(r['hashtags'])}",
            f"- Sub-scores: hook {s['hook']:.2f}, energy {s['energy']:.2f}, pace {s['pace']:.2f}, "
            f"emotion {s['emotion']:.2f}, completeness {s['completeness']:.2f}, "
            f"visual {s['visual']:.2f}",
            f"- Why: {', '.join(s['reasons']) or 'balanced scores'}",
            f"- Text: {r['text'][:300]}...\n",
        ]
    (project / "report.md").write_text("\n".join(lines), encoding="utf-8")


# ===========================================================================
# GAME MODE (added in v0.2.0) - gameplay video -> kill highlights -> vertical shorts
# WHY: gameplay has no speech to analyse; the "viral moment" is the kill. We detect kills from
#      the on-screen kill feed (killfeed.py), group them into plays (highlights.py), then render
#      each play with kill popups and a gameplay layout (center / blur / stack with facecam).
# HOW TO IMPROVE: add a review page to approve plays, kill-synced zoom punch, background music.
# ===========================================================================
def _flat_words(transcript: dict) -> list:
    """All words of a transcript in one list (used for optional speech captions)."""
    words = []
    for seg in transcript["segments"]:
        words.extend(segments._words_from_segment(seg))
    return words


def _audio_signals(video: Path, work: Path):
    """Loudness over time (cached). Gunfights are loud, so it adds a small score bonus."""
    cache = work / "audio_energy.json"
    if cache.exists():
        data = json.loads(cache.read_text())
        return analyze.Signals(data["hop"], data["rms"], [])
    hop, rms = analyze.audio_energy(video)
    cache.write_text(json.dumps({"hop": hop, "rms": [round(float(x), 5) for x in rms]}))
    return analyze.Signals(hop, rms, [])


def detect_only(source: str, game: str = "valorant", out_root: str = "output",
                game_profile_path=None, overrides=None, debug: bool = False, log=print) -> list:
    """Run ONLY the kill detection and print the timeline (fast way to test your settings)."""
    gp = load_game_profile(game, game_profile_path, overrides)
    video, project, work, info = _open_source(source, out_root, log)
    kills = killfeed.detect(video, info, gp, work, log=log, force=True,
                            debug_dir=(project / "debug") if debug else None)
    for n, t in enumerate(kills, start=1):
        log(f"  kill {n:>3}: {int(t // 60):02d}:{t % 60:05.2f}")
    (project / "kills.json").write_text(json.dumps(kills))
    if debug:
        log(f"Debug pictures: {(project / 'debug').resolve()}")
    return kills


def run_game(source: str, game: str = "valorant", out_root: str = "output", count: int = 5,
             min_kills: int = 1, layout=None, facecam=None, with_popups: bool = True,
             hook_title: bool = True, speech_captions: bool = False, model: str = "small",
             language=None, transcript_file=None, game_profile_path=None, overrides=None,
             dry_run: bool = False, debug: bool = False, log=print) -> dict:
    """Run game mode. Returns {'project': folder, 'shorts': [...], 'kills': [...]}."""
    gp = load_game_profile(game, game_profile_path, overrides)
    profile = load_profile()
    layout = layout or gp.get("layout", "center")
    facecam = facecam or gp.get("facecam")
    if layout == "stack" and not facecam:
        log("Layout 'stack' needs --facecam x,y,w,h ; using 'center' instead.")
        layout = "center"

    video, project, work, info = _open_source(source, out_root, log)
    kills = killfeed.detect(video, info, gp, work, log=log,
                            debug_dir=(project / "debug") if debug else None)
    if not kills:
        raise RuntimeError(
            "No kills were detected. Run:  python -m shortsforge calibrate <video> --time <seconds "
            "just after one of your kills>  and follow the printed advice (area / colour).")

    signals = _audio_signals(video, work)
    plays = highlights.group_plays(kills, gp, info["duration"])
    for play in plays:
        highlights.score_play(play, signals, gp)
    chosen = highlights.select_plays(plays, count, min_kills)
    log(f"{len(kills)} kills -> {len(plays)} plays -> keeping {len(chosen)}.")
    if not chosen:
        raise RuntimeError(f"No play has {min_kills}+ kills. Try a lower --min-kills.")

    words = []
    if speech_captions:
        if transcript_file:
            transcript = json.loads(Path(transcript_file).read_text(encoding="utf-8"))
        else:
            log("Transcribing your voice for captions ...")
            transcript = transcribe(video, work, model_size=model, language=language)
        words = _flat_words(transcript)

    meta = {"mode": "game", "game": game, "video": str(Path(video).resolve()),
            "duration": info["duration"], "layout": layout, "facecam": facecam,
            "with_popups": with_popups, "hook_title": hook_title, "popup": gp["popup"],
            "words_file": str(work / "transcript.json") if speech_captions else None}
    if speech_captions and transcript_file:
        (work / "transcript.json").write_text(json.dumps(transcript), encoding="utf-8")
    results = []
    for n, play in enumerate(chosen, start=1):
        start, end = play["start"], play["end"]
        entry = {"file": f"short_{n:02d}.mp4", "start": round(start, 2), "end": round(end, 2),
                 "kills": play["kills"], "label": play["label"], "score": play["score"],
                 "title": play["label"].title() + "!",
                 "hashtags": highlights.hashtags_for(play, game)}
        if not dry_run:
            log(f"Rendering short {n}/{len(chosen)}: {play['label']} "
                f"({start:.0f}s-{end:.0f}s, score {play['score']['total']}) ...")
            _render_short(meta, info, profile, project, entry, start, end, entry["title"])
        results.append(entry)
    (project / "project.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")

    (project / "shorts.json").write_text(json.dumps(results, indent=1), encoding="utf-8")
    _write_game_report(project, source, kills, results, dry_run)
    log(f"Done. Open: {project.resolve()}")
    return {"project": str(project), "shorts": results, "kills": kills}


def _write_game_report(project: Path, source: str, kills: list, results: list, dry: bool):
    """report.md for game mode: every kill time + why each play was chosen."""
    lines = ["# ShortsForge game report\n", f"Source: `{source}`\n",
             "(dry run - nothing was rendered)\n" if dry else "",
             "All detected kills (mm:ss): " + ", ".join(
                 f"{int(t // 60):02d}:{t % 60:04.1f}" for t in kills) + "\n"]
    for r in results:
        s = r["score"]
        lines += [f"## {r['file']} - {r['label']} - score {s['total']}",
                  f"- Time: {r['start']}s to {r['end']}s", f"- Kills at: {r['kills']}",
                  f"- Why: {', '.join(s['reasons'])}",
                  f"- Score parts: base {s['base']}, speed +{s['speed']}, energy +{s['energy']}",
                  f"- Hashtags: {' '.join(r['hashtags'])}\n"]
    (project / "report.md").write_text("\n".join(lines), encoding="utf-8")


# ===========================================================================
# SHARED RENDER + RE-EXPORT (added in v0.3.0)
# WHY: the app window lets you trim a clip and export it again. Both the first render and the
#      re-export must produce the SAME look, so they share one function (_render_short).
#      project.json remembers the settings used (layout, captions, source video ...).
# HOW TO IMPROVE: add more editable things (caption style, music, speed, crop position).
# ===========================================================================
def _load_words(meta: dict) -> list:
    """Words of the saved transcript (empty list when the project has no speech captions)."""
    words_file = meta.get("words_file")
    if not words_file or not Path(words_file).exists():
        return []
    return _flat_words(json.loads(Path(words_file).read_text(encoding="utf-8")))


def _render_short(meta: dict, info: dict, profile: dict, project: Path, entry: dict,
                  start: float, end: float, title) -> None:
    """Render ONE short for the project (used by run, run_game and rerender)."""
    video = Path(meta["video"])
    clips_dir = project / "clips"
    clips_dir.mkdir(parents=True, exist_ok=True)
    out_file = clips_dir / entry["file"]
    ass_path = clips_dir / (Path(entry["file"]).stem + ".ass")

    if meta["mode"] == "game":
        vf = reframe.build_game_filter(meta["layout"], info["width"], info["height"],
                                       meta.get("facecam"))
        popups = captions.kill_events(entry["kills"], start, end, meta["popup"]["seconds"],
                                      meta["popup"]["y"]) if meta["with_popups"] else []
        headline = title if (meta["hook_title"] and len(entry["kills"]) > 1) else None
        ass_text = captions.build_ass(_load_words(meta), start, end, headline,
                                      profile["caption"], extra_events=popups)
    else:
        face_x = None
        if meta["reframe"] in ("auto", "face"):
            face_x = reframe.detect_face_x(video, start, end, info["width"])
        vf = reframe.build_filter(meta["reframe"], info["width"], info["height"], face_x)
        ass_text = None
        if meta["captions"]:
            ass_text = captions.build_ass(_load_words(meta), start, end,
                                          title if meta["hook_title"] else None,
                                          profile["caption"])

    if ass_text is not None:
        ass_path.write_text(ass_text, encoding="utf-8")
    else:
        ass_path = None
    render.render_clip(video, start, end, out_file, vf, ass_path)


def rerender(project_dir, index: int, start: float, end: float, title=None, log=print) -> dict:
    """Export short number `index` again with a new start / end / title. Returns the entry."""
    project = Path(project_dir)
    meta = json.loads((project / "project.json").read_text(encoding="utf-8"))
    shorts = json.loads((project / "shorts.json").read_text(encoding="utf-8"))
    if not 0 <= index < len(shorts):
        raise ValueError("That clip does not exist.")
    entry = shorts[index]

    info = ingest.probe(Path(meta["video"]))
    start = max(0.0, float(start))
    end = min(info["duration"], float(end))
    if end - start < 1.0:
        raise ValueError("The clip must be at least 1 second long (check Start and End).")
    if end - start > 180.0:
        raise ValueError("The clip is longer than 3 minutes. Shorts should be under 60 seconds.")
    title = entry["title"] if title is None else title

    log(f"Exporting {entry['file']} again ({start:.1f}s to {end:.1f}s) ...")
    _render_short(meta, info, load_profile(), project, entry, start, end, title)
    entry.update({"start": round(start, 2), "end": round(end, 2), "title": title})
    (project / "shorts.json").write_text(json.dumps(shorts, indent=1), encoding="utf-8")
    log("Done.")
    return entry
