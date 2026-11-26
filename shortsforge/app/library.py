"""
library.py - knows where your videos are, so you (and Forge) can find them by name.

WHY it exists:
    The assistant used to know only uploaded videos and videos of FINISHED projects. If a first
    run failed (for example "no kills"), that video was forgotten and Forge could not find it.

HOW it works:
    - remember(): every video you choose or process is written to Documents/ShortsForge/
      _videos.json straight away, even if the work fails afterwards.
    - find(): looks through that list AND the usual folders (Videos, Desktop, Downloads,
      Documents, Pictures, also their OneDrive copies, plus folders you add in Settings).
      Only video files are listed; nothing is opened or changed.
    - From a phone (remote=True) only videos inside the app's own folder are shown.

HOW TO IMPROVE:
    - Cache the folder scan and watch for new files.
    - Search by date ("yesterday's recording").
"""

import json
import os
import re
import time
from pathlib import Path

EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v", ".flv", ".wmv", ".ts"}
FOLDER_NAMES = ("Videos", "Desktop", "Downloads", "Documents", "Pictures")
MAX_DEPTH = 4                 # how many folders deep we look
MAX_FILES = 3000              # safety limit
MAX_SECONDS = 8.0             # never make you wait long
MIN_SIZE = 200 * 1024         # smaller files are thumbnails or broken pieces
SKIP = {"node_modules", "appdata", "$recycle.bin", "_calibrate", "_teach", "_editor", "clips"}


def _recent_file(out_dir) -> Path:
    return Path(out_dir) / "_videos.json"


def recent(out_dir) -> list:
    """Videos used before (newest first), only those that still exist."""
    try:
        data = json.loads(_recent_file(out_dir).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [p for p in data if isinstance(p, str) and Path(p).is_file()]


def remember(out_dir, path) -> None:
    """Put a video at the top of the 'used before' list."""
    path = str(path or "")
    if not path or Path(path).suffix.lower() not in EXTENSIONS or not Path(path).is_file():
        return
    items = [path] + [p for p in recent(out_dir) if p != path]
    try:
        _recent_file(out_dir).write_text(json.dumps(items[:50]), encoding="utf-8")
    except OSError:
        pass                                          # forgetting is not fatal


def search_folders(extra=()) -> list:
    """The folders that are searched."""
    home = Path.home()
    bases = [home]
    bases += [Path(os.environ[k]) for k in ("OneDrive", "OneDriveConsumer") if os.environ.get(k)]
    folders = [base / name for base in bases for name in FOLDER_NAMES]
    folders += [Path(str(p).strip().strip('"')) for p in extra if str(p).strip()]
    seen, out = set(), []
    for f in folders:
        if f.is_dir() and str(f) not in seen:
            seen.add(str(f))
            out.append(f)
    return out


def scan(folders, out_dir) -> list:
    """All video files in the folders (the app's own output folder is skipped)."""
    own = Path(out_dir).resolve()
    found, seen, stop_at = [], set(), time.time() + MAX_SECONDS
    for top in folders:
        for current, subfolders, files in os.walk(top):
            here = Path(current)
            depth = len(here.parts) - len(top.parts)
            subfolders[:] = [d for d in subfolders if depth < MAX_DEPTH
                             and not d.startswith(".") and d.lower() not in SKIP
                             and (here / d).resolve() != own]
            for name in files:
                path = here / name
                if path.suffix.lower() not in EXTENSIONS or str(path) in seen:
                    continue
                try:
                    stat = path.stat()
                except OSError:
                    continue
                if stat.st_size >= MIN_SIZE:
                    seen.add(str(path))
                    found.append(str(path))
            if len(found) >= MAX_FILES or time.time() > stop_at:
                return found
    return found


def _words(text: str) -> list:
    return re.findall(r"[a-z0-9]+", str(text).lower())


# Words people say that are not part of a file name.
FILLER = set("find locate search show where is are my the a an video videos recording recordings "
             "file files footage gameplay clip please can you called named for of in on from me "
             "last latest newest recent new that this one it with".split())


def describe(path: str, where: str) -> dict:
    p = Path(path)
    try:
        stat = p.stat()
        size, modified = stat.st_size, stat.st_mtime
    except OSError:
        size, modified = 0, 0
    return {"path": str(p), "name": p.name, "where": where, "size_mb": round(size / 1e6, 1),
            "modified": modified,
            "date": time.strftime("%d %b %Y %H:%M", time.localtime(modified)) if modified else ""}


def _inside(path: str, root: Path) -> bool:
    try:
        Path(path).resolve().relative_to(root)
        return True
    except (ValueError, OSError):
        return False


def find(out_dir, query: str = "", extra=(), remote: bool = False, limit: int = 20) -> list:
    """Videos matching the words of `query` (empty = all), newest first."""
    out_dir = Path(out_dir).resolve()
    where = {}
    uploads = out_dir / "_uploads"
    if uploads.is_dir():
        for f in uploads.iterdir():
            if f.is_file() and f.suffix.lower() in EXTENSIONS:
                where[str(f)] = "uploaded"
    for folder in out_dir.iterdir():
        meta = folder / "project.json"
        if folder.is_dir() and meta.exists():
            try:
                video = json.loads(meta.read_text(encoding="utf-8")).get("video")
            except (OSError, ValueError):
                continue
            if video and Path(video).is_file():
                where.setdefault(video, f"source of project {folder.name}")
    for path in recent(out_dir):
        where.setdefault(path, "used before")
    if not remote:
        for path in scan(search_folders(extra), out_dir):
            where.setdefault(path, "on this PC")
    else:
        where = {p: w for p, w in where.items() if _inside(p, out_dir)}

    wanted = [w for w in _words(query) if w not in FILLER]
    items = []
    for path, place in where.items():
        text = " ".join(_words(path))
        matched = sum(1 for w in wanted if w in text)
        if wanted and not matched:
            continue
        items.append((matched, describe(path, place)))
    items.sort(key=lambda m: (m[0], m[1]["modified"]), reverse=True)
    return [item for _, item in items[:limit]]
