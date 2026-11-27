"""
findapi.py - the app side of the Find screen (web requests <-> the shortsforge/find engine).

WHY it exists:
    server.py is already long. Everything about "describe it, find it, cut it" is here.

HOW it works:
    - status(): what the screen shows when it opens.
    - action(): add/delete an example picture, or start a search / cut job.
    - `inside` is set for a phone: then only videos in the app's own folder may be used.

HOW TO IMPROVE:
    - Keep the last few searches, not just one.
"""

from pathlib import Path

from ..find import engine, pictures, query
from . import library
from .assistant import looker

MAX_MOMENTS = 20


def _last(state, inside) -> dict:
    last = engine.last(state.out_dir)
    if last and inside is not None:                    # a phone must not see other PC videos
        try:
            Path(last["video"]).resolve().relative_to(inside)
        except (ValueError, KeyError):
            return {}
    return last


def status(state, inside=None) -> dict:
    items = [{**p, "image": f"_find/{p['file']}"} for p in pictures.load_all(state.out_dir)]
    return {"pictures": items, "agents": sorted(query.load_agents()),
            "vision": looker(state.settings, state.local_ai) is not None, "last": _last(state, inside)}


def search_job(state, video: str, text: str):
    """A job function that runs one search."""
    def job(log):
        look = looker(state.settings, state.local_ai)
        return {"find": engine.search(state.out_dir, video, text, log=log, look=look)}
    return job


def make_job(state, video: str, chosen: list, title: str, layout: str, kill_search: bool):
    def job(log):
        return engine.make_clips(state.out_dir, video, chosen, title, layout, log=log,
                                 kill_search=kill_search)
    return job


def action(state, payload: dict, check_source, inside=None) -> dict:
    """Handle one POST. check_source(path, inside) validates a video path."""
    what = payload.get("action")
    if what == "delete_picture":
        pictures.delete(state.out_dir, str(payload.get("id", "")))
        return status(state, inside)
    source = check_source(payload.get("source"), inside)
    if not Path(source).is_file():
        raise ValueError("Find works with video files on this PC (not links).")
    library.remember(state.out_dir, source)
    if what == "add_picture":
        pictures.add(state.out_dir, source, payload.get("time") or 0, payload.get("box"),
                     payload.get("name"), str(payload.get("kind", "feed")))
        return status(state, inside)
    if what == "search":
        text = str(payload.get("query", "")).strip()[:300]
        if not text:
            raise ValueError("Say what to look for.")
        job = state.jobs.start("find", search_job(state, source, text))
        return {"job": job.id}
    if what == "make":
        chosen = [{"start": float(m["start"]), "end": float(m["end"])}
                  for m in (payload.get("moments") or [])[:MAX_MOMENTS]]
        if not chosen:
            raise ValueError("Tick at least one moment.")
        last = engine.last(state.out_dir)
        job = state.jobs.start("find_make", make_job(
            state, source, chosen, str(payload.get("title", "")), str(payload.get("layout", "auto")),
            bool(last.get("kill_search", True))))
        return {"job": job.id}
    raise ValueError("Unknown action.")
