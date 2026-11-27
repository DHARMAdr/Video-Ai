"""
server.py - the small web server that connects the window to the real work.

WHY it exists:
    The window is a web page. A web page cannot touch your files or run ffmpeg by itself, so it
    asks this server ("make shorts from this video", "chat with the assistant", ...).

HOW it works:
    - Python's built-in http.server (nothing to install).
    - TWO possible doors into the same app:
        1. The LOCAL door: 127.0.0.1 only (this computer). Always on. Full power.
        2. The PHONE door ("phone access"): listens on your home Wi-Fi so a phone/tablet can use
           the app. OFF until you turn it on in Settings. It has LESS power: it cannot change
           settings, open folders on the PC, use the PC file picker, or read any PC path -
           it can only upload videos, make shorts, watch clips and chat.
    - SAFETY for both doors: a secret token (new at every start) is required, the Host name must
      be one we expect (stops "DNS rebinding"), and files are only served from the output folder
      (Documents/ShortsForge).
    - Video preview needs HTTP "Range" requests (jumping around in a clip); supported.

ROUTES (all need the token):
    GET  /                  the page              GET  /api/info        version, folders, mode
    GET  /api/projects      past projects         GET  /api/project     one project's clips
    GET  /api/job           progress of a task    GET  /files/...       a clip / picture
    GET  /api/chat          saved chat            GET  /api/settings    assistant settings (keys hidden)
    GET  /api/lan           phone-access status + QR code            (local door only)
    GET  /api/localai       built-in AI: models, download progress   (local door only)
    POST /api/localai       download / cancel / remove a model       (local door only)
    POST /api/posttext      AI writes titles + hashtags for a project
    GET  /api/videos        videos found on the PC     GET  /api/video   play one of them
    GET  /api/teach         what was taught            POST /api/teach   area / name / learn / reset
    GET  /api/find          example pictures, last search   POST /api/find  picture / search / make
    GET  /api/report        troubleshooting report (local door only)
    POST /api/voice         microphone recording -> text
    GET  /api/editor        editor choices + saved draft   GET /api/probe  video length/size
    POST /api/editor        save draft / preview / export
    POST /api/pick          file dialog           (local only)       POST /api/start       make shorts
    POST /api/calibrate     check kill scan       POST /api/rerender   export a clip again
    POST /api/open_folder   show in Explorer      (local only)       POST /api/upload      send a video
    POST /api/chat          talk to the assistant (built-in commands first, then the AI)
    POST /api/chat/clear    forget the chat       GET/POST /api/memory(/clear) the assistant's notes
    POST /api/feedback      thumbs up/down on an answer (saved to _feedback.jsonl for future training)
    POST /api/settings      save settings (local only)               POST /api/settings/test  try the AI
    POST /api/lan           turn phone access on/off (local only)

HOW TO IMPROVE:
    - Stream chat answers (Server-Sent Events) so words appear while the AI writes.
    - Add https + a pairing code for the phone door.
    - Add a Cancel route once the work runs in a separate process.
"""

import json
import mimetypes
import os
import re
import secrets
import shutil
import subprocess
import sys
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .. import __version__, paths
from .. import editor, ingest
from . import lan as lan_tools
from . import edits, findapi, library, report, voice
from .jobs import JobManager
from .localai import LocalAI, LocalAIError
from .memory import Memory
from .settings import Settings

STATIC_DIR = Path(__file__).parent / "static"
CHUNK = 256 * 1024
VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v", ".flv", ".wmv", ".ts"}
MAX_UPLOAD = 20 * 1024 ** 3            # 20 GB, a safety limit
MAX_CHAT_TEXT = 4000                   # characters per chat message
MAX_STORED_CHAT = 200                  # messages kept in the chat file
NO_AI_REPLY = ("I can do video commands without any AI. Type **help** to see them, for example "
               "\"make 5 shorts from my last video\" or \"show my projects\".\n\n"
               "For open questions (ideas, writing, explanations) I need an AI connected. "
               "Open **Settings** and choose Built-in (free, offline), Claude or another AI.")


class AppState:
    """Everything the handlers share."""

    def __init__(self, out_dir):
        self.out_dir = Path(out_dir).resolve()
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.token = secrets.token_urlsafe(16)    # secret, new on every start
        self.jobs = JobManager()
        self.settings = Settings(self.out_dir / "_settings.json")
        self.local_ai = LocalAI()                 # the built-in offline model
        self.settings.local_ready = self.local_ai.installed
        self.pick_file = None                     # set by desktop.py when a native dialog exists
        self.port = None                          # local door port
        self.lan_server = None                    # phone-door server (None = off)
        self.lan_port = None
        self.chat_lock = threading.Lock()         # one chat answer at a time
        self.chat_file = self.out_dir / "_chat.json"
        self.memory = Memory(self.out_dir / "_memory.json")
        self.feedback_file = self.out_dir / "_feedback.jsonl"


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------
def clean_path(text) -> str:
    """Remove spaces and the quotes Windows adds when you use 'Copy as path'."""
    return str(text or "").strip().strip('"').strip("'").strip()


def _num(value, default, low=None, high=None):
    """Read a number from user input safely."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = default
    if low is not None:
        number = max(low, number)
    if high is not None:
        number = min(high, number)
    return number


def _floats(value, n):
    """List/str of n numbers -> list of floats, or None."""
    if value in (None, "", []):
        return None
    if isinstance(value, str):
        value = value.split(",")
    try:
        numbers = [float(v) for v in value]
    except (TypeError, ValueError):
        return None
    return numbers if len(numbers) == n else None


def project_dir(state: AppState, name: str) -> Path:
    """Folder of a project; the name must be a plain folder name inside the output folder."""
    if not name or Path(name).name != name or name.startswith("."):
        raise ValueError("Bad project name.")
    folder = state.out_dir / name
    if not folder.is_dir():
        raise ValueError("Project not found.")
    return folder


def list_projects(state: AppState) -> list:
    """All finished projects, newest first."""
    found = []
    for folder in state.out_dir.iterdir():
        shorts = folder / "shorts.json"
        if folder.is_dir() and not folder.name.startswith("_") and shorts.exists():
            try:
                count = len(json.loads(shorts.read_text("utf-8")))
            except ValueError:
                count = 0
            found.append({"name": folder.name, "count": count, "modified": shorts.stat().st_mtime})
    return sorted(found, key=lambda p: p["modified"], reverse=True)


def read_project(state: AppState, name: str) -> dict:
    """The clips list + details of one project."""
    folder = project_dir(state, name)
    shorts_file, meta_file = folder / "shorts.json", folder / "project.json"
    return {"name": folder.name,
            "shorts": json.loads(shorts_file.read_text("utf-8")) if shorts_file.exists() else [],
            "meta": json.loads(meta_file.read_text("utf-8")) if meta_file.exists() else {}}


def load_chat(state: AppState) -> list:
    try:
        data = json.loads(state.chat_file.read_text("utf-8"))
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def save_chat(state: AppState, messages: list) -> None:
    try:
        state.chat_file.write_text(json.dumps(messages[-MAX_STORED_CHAT:], ensure_ascii=False),
                                   encoding="utf-8")
    except OSError:
        pass                                          # losing chat history is not fatal


def safe_upload_name(name: str) -> str:
    """Make an uploaded file name safe: no folders, no odd characters, a known video extension."""
    name = Path(urllib.parse.unquote(name or "")).name
    stem, ext = os.path.splitext(name)
    ext = ext.lower()
    if ext not in VIDEO_EXTENSIONS:
        raise ValueError("That does not look like a video file (mp4, mov, mkv, webm, avi...).")
    stem = re.sub(r"[^\w.\- ()]", "_", stem).strip(" .") or "video"
    return stem[:80] + ext


# ---------------------------------------------------------------------------
# Jobs (what the buttons start)
# ---------------------------------------------------------------------------
def _project_name(state: AppState, result: dict) -> str:
    """Folder name of the project, relative to the output folder."""
    return Path(result["project"]).resolve().relative_to(state.out_dir).parts[0]


def _check_source(source: str, only_inside: Path = None) -> str:
    """Make sure the video exists (or looks like a link).

    only_inside: when set (phone door), a file path must be inside that folder.
    """
    source = clean_path(source)
    if not source:
        raise ValueError("Choose a video first.")
    if ingest.is_url(source):
        return source
    path = Path(source)
    if not path.is_file():
        raise ValueError(f"File not found: {source}")
    if only_inside is not None:
        try:
            path.resolve().relative_to(only_inside)
        except ValueError:
            raise ValueError("From a phone you can only use videos you uploaded or links.")
    return source


def make_start_job(state: AppState, payload: dict, only_inside: Path = None):
    """Build the function for a 'make shorts' job."""
    source = _check_source(payload.get("source"), only_inside)
    library.remember(state.out_dir, source)           # so it can be found again, even if this fails
    mode = payload.get("mode", "talk")
    o = payload.get("options") or {}
    count = int(_num(o.get("count"), 5, 1, 20))
    out_root = str(state.out_dir)

    if mode == "game":
        facecam = _floats(o.get("facecam"), 4)
        layout = o.get("layout") or "center"
        if layout not in ("center", "blur", "stack"):
            raise ValueError("Unknown layout.")
        overrides = {"roi": _floats(o.get("roi"), 4)} if _floats(o.get("roi"), 4) else None

        def job(log):
            from .. import pipeline
            res = pipeline.run_game(
                source, game="valorant", out_root=out_root, count=count,
                min_kills=int(_num(o.get("min_kills"), 1, 1, 5)), layout=layout,
                facecam=facecam, with_popups=bool(o.get("popups", True)),
                hook_title=bool(o.get("hook_title", True)),
                speech_captions=bool(o.get("speech", False)), overrides=overrides,
                fallback=bool(o.get("fallback", True)), log=log)
            return {"project_name": _project_name(state, res), "count": len(res["shorts"]),
                    "note": res.get("note", "")}
        return job

    reframe_mode = o.get("reframe") or "auto"
    if reframe_mode not in ("auto", "face", "center", "blur"):
        raise ValueError("Unknown framing.")

    def job(log):
        from .. import pipeline
        res = pipeline.run(source, out_root=out_root, count=count, reframe_mode=reframe_mode,
                           with_captions=bool(o.get("captions", True)),
                           hook_title=bool(o.get("hook_title", True)), log=log)
        return {"project_name": _project_name(state, res), "count": len(res["shorts"])}
    return job


def make_calibrate_job(state: AppState, payload: dict, only_inside: Path = None):
    """Build the function for a 'check kill detection' job."""
    source = _check_source(payload.get("source"), only_inside)
    time_s = _num(payload.get("time"), 0, 0)
    roi = _floats(payload.get("roi"), 4)
    out = state.out_dir / "_calibrate"

    def job(log):
        from ..calibrate import calibrate
        res = calibrate(source, time_s, "valorant", None, roi, str(out), log=log)
        return {"rows": res["rows"],
                "images": ["_calibrate/full_frame.png", "_calibrate/roi.png", "_calibrate/mask.png"]}
    return job


def make_teach_job(state: AppState, payload: dict, only_inside: Path = None):
    """Build the function for 'learn from my marked kills'."""
    source = _check_source(payload.get("source"), only_inside)
    library.remember(state.out_dir, source)
    marks = [_num(m, 0, 0) for m in (payload.get("marks") or [])][:20]
    if not marks:
        raise ValueError("Mark at least one moment where you got a kill.")

    def job(log):
        from .. import teach
        return {"teach": teach.learn(state.out_dir, source, marks, log=log)}
    return job


def make_rerender_job(state: AppState, payload: dict):
    """Build the function for 'export this clip again'."""
    name = str(payload.get("project", ""))
    if Path(name).name != name or not (state.out_dir / name / "project.json").exists():
        raise ValueError("This project cannot be edited (it was made by an older version).")
    index = int(_num(payload.get("index"), 0, 0))
    start, end = _num(payload.get("start"), 0, 0), _num(payload.get("end"), 0, 0)
    title = payload.get("title")

    def job(log):
        from .. import pipeline
        pipeline.rerender(state.out_dir / name, index, start, end, title, log=log)
        return {"project_name": name}
    return job


def make_add_clip_job(state: AppState, payload: dict):
    """Build the function for 'make a new clip from this time range'."""
    name = str(payload.get("project", ""))
    if Path(name).name != name or not (state.out_dir / name / "project.json").exists():
        raise ValueError("This project cannot be edited (it was made by an older version).")
    start, end = _num(payload.get("start"), 0, 0), _num(payload.get("end"), 0, 0)
    title = payload.get("title")

    def job(log):
        from .. import pipeline
        pipeline.add_clip(state.out_dir / name, start, end, title, log=log)
        return {"project_name": name}
    return job


# File types the window may read from the output folder.
SERVED_TYPES = {".mp4", ".mov", ".mkv", ".webm", ".m4v", ".avi", ".png", ".jpg", ".srt", ".vtt",
                ".ass", ".txt", ".md"}


def build_page() -> bytes:
    """index.html with the other screens' scripts (static/*.js) placed inside it.

    WHY: one single page needs one token check, and each screen's code stays in its own file.
    """
    page = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    scripts = "".join(f"<script>\n{p.read_text(encoding='utf-8')}\n</script>\n"
                      for p in sorted(STATIC_DIR.glob("*.js")))
    return page.replace("<!--EXTRA-SCRIPTS-->", scripts).encode("utf-8")


# ---------------------------------------------------------------------------
# HTTP handler
# ---------------------------------------------------------------------------
def make_server(state: AppState, port: int = 0, lan: bool = False) -> ThreadingHTTPServer:
    """Create a server. lan=False: this computer only. lan=True: the phone door (Wi-Fi)."""

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args):          # keep the console quiet
            pass

        # ----- helpers -----------------------------------------------------
        def _query(self):
            return urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)

        def _authorized(self) -> bool:
            host = (self.headers.get("Host") or "").rsplit(":", 1)[0].strip("[]")
            if lan:
                if not lan_tools.is_private_host(host):
                    return False                # the phone door only answers private addresses
            elif host not in ("127.0.0.1", "localhost"):
                return False                    # blocks "DNS rebinding" tricks
            given = self.headers.get("X-Token") or (self._query().get("t") or [""])[0]
            return secrets.compare_digest(given, state.token)

        def _send(self, status: int, body: bytes, ctype: str, extra=None):
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            for key, value in (extra or {}).items():
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(body)

        def _json(self, data, status: int = 200):
            self._send(status, json.dumps(data).encode("utf-8"), "application/json")

        def _fail(self, status: int, message: str):
            self._json({"error": message}, status)

        def _body(self) -> dict:
            length = int(self.headers.get("Content-Length") or 0)
            if length <= 0:
                return {}
            if length > 2_000_000:
                raise ValueError("Request too large.")
            return json.loads(self.rfile.read(length).decode("utf-8") or "{}")

        def _local_only(self) -> bool:
            """Refuse (and say so) when a phone tries a PC-only action."""
            if lan:
                self._fail(403, "This can only be done on the computer itself.")
                return False
            return True

        # ----- GET -----------------------------------------------------------
        def do_GET(self):
            try:
                self._route_get()
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass                            # the window closed the connection; fine
            except ValueError as exc:
                self._fail(400, str(exc))
            except Exception as exc:
                self._fail(500, str(exc))

        def _route_get(self):
            route = urllib.parse.urlparse(self.path).path
            if not self._authorized():
                return self._fail(403, "Not allowed.")
            q = self._query()

            if route == "/":
                page = build_page()
                return self._send(200, page, "text/html; charset=utf-8")
            if route == "/api/info":
                return self._json({"version": __version__, "out_dir": str(state.out_dir),
                                   "can_browse": state.pick_file is not None and not lan,
                                   "remote": lan,
                                   "ffmpeg": shutil.which("ffmpeg") is not None,
                                   "model_bundled": paths.has_bundled_model("small"),
                                   "assistant_ready": state.settings.configured(),
                                   "assistant_name": state.settings.data.get("name", "Forge")})
            if route == "/api/job":
                try:
                    return self._json(state.jobs.snapshot((q.get("id") or [""])[0],
                                                          int((q.get("since") or ["0"])[0])))
                except KeyError as exc:
                    return self._fail(404, str(exc))
            if route == "/api/projects":
                return self._json(list_projects(state))
            if route == "/api/project":
                return self._json(read_project(state, (q.get("name") or [""])[0]))
            if route == "/api/videos":
                from .assistant import ToolBox
                box = ToolBox(state, remote=lan)
                return self._json(box.t_find_videos((q.get("q") or [""])[0]))
            if route == "/api/video":
                return self._serve_video((q.get("path") or [""])[0])
            if route == "/api/teach":
                from .. import teach
                return self._json(teach.describe(state.out_dir))
            if route == "/api/find":
                return self._json(findapi.status(state, state.out_dir if lan else None))
            if route == "/api/editor":
                return self._json({"filters": list(editor.FILTERS), "effects": list(editor.EFFECTS),
                                   "animations": list(editor.TEXT_ANIMATIONS),
                                   "stickers": list(editor.layers.STICKERS),
                                   "transitions": list(editor.TRANSITIONS),
                                   "aspects": list(editor.SIZES), "draft": edits.load_draft(state.out_dir)})
            if route == "/api/probe":
                path = _check_source((q.get("path") or [""])[0], state.out_dir if lan else None)
                if Path(path).suffix.lower() not in library.EXTENSIONS:
                    raise ValueError("That is not a video file.")
                library.remember(state.out_dir, path)
                return self._json({**ingest.probe(Path(path)), "path": path})
            if route == "/api/report":
                if not self._local_only():
                    return
                return self._json({"text": report.build(state)})
            if route == "/api/chat":
                return self._json({"messages": load_chat(state)})
            if route == "/api/settings":
                if not self._local_only():
                    return
                return self._json(state.settings.public())
            if route == "/api/memory":
                return self._json({"notes": state.memory.texts()})
            if route == "/api/lan":
                if not self._local_only():
                    return
                return self._json(lan_status(state))
            if route == "/api/localai":
                if not self._local_only():
                    return
                return self._json(state.local_ai.status())
            if route.startswith("/files/"):
                return self._serve_file(urllib.parse.unquote(route[len("/files/"):]))
            return self._fail(404, "Not found.")

        def _post_texts(self, payload):
            from . import posttext
            from .assistant import AssistantError, ToolBox, complete
            box = ToolBox(state)
            folder = box._project(payload.get("project"))       # ValueError for a bad name
            if box._busy():
                raise ValueError("Another task is still running. Try again when it finishes.")
            if not state.chat_lock.acquire(blocking=False):
                raise ValueError("The AI is busy answering. Try again in a moment.")
            try:
                result = posttext.write_post_texts(
                    folder, lambda s, p: complete(state.settings, state.local_ai, s, p))
            except AssistantError as exc:
                raise ValueError(str(exc))
            finally:
                state.chat_lock.release()
            return self._json({"written": len(result["written"]), "failed": result["failed"]})

        def _serve_file(self, relative: str):
            target = (state.out_dir / relative).resolve()
            try:
                target.relative_to(state.out_dir)       # must stay inside the output folder
            except ValueError:
                return self._fail(403, "Not allowed.")
            # Only media and result texts. Never .json: the settings file holds your API key, and
            # a list of "forbidden names" can be tricked ("./_settings.json", other letter case).
            if target.suffix.lower() not in SERVED_TYPES:
                return self._fail(403, "Not allowed.")
            return self._stream(target)

        def _serve_video(self, path: str):
            """Play one of your videos inside the window (for Teach and the editor)."""
            target = Path(clean_path(path))
            # The editor also previews the pictures and sounds you add to the timeline.
            playable = library.EXTENSIONS | editor.AUDIO_TYPES | editor.layers.IMAGE_TYPES
            if target.suffix.lower() not in playable or not target.is_file():
                return self._fail(404, "Video not found.")
            if lan:                                    # phone: only files inside the app folder
                try:
                    target.resolve().relative_to(state.out_dir)
                except ValueError:
                    return self._fail(403, "Not allowed.")
            return self._stream(target)

        def _stream(self, target: Path):
            """Send a file, or the part of it the video player asked for."""
            if not target.is_file():
                return self._fail(404, "File not found.")
            size = target.stat().st_size
            ctype = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
            start, end, status = 0, size - 1, 200
            header = self.headers.get("Range")
            if header and header.startswith("bytes="):
                first, _, last = header[6:].partition("-")
                try:
                    if first == "":                      # "last N bytes"
                        start = max(0, size - int(last))
                    else:
                        start = int(first)
                        end = min(int(last), size - 1) if last else size - 1
                except ValueError:
                    return self._fail(416, "Bad range.")
                if start > end or start >= size:
                    return self._fail(416, "Bad range.")
                status = 206
            length = end - start + 1
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Length", str(length))
            self.send_header("Cache-Control", "no-store")
            if status == 206:
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            self.end_headers()
            with open(target, "rb") as handle:
                handle.seek(start)
                left = length
                while left > 0:
                    chunk = handle.read(min(CHUNK, left))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    left -= len(chunk)

        # ----- POST ----------------------------------------------------------
        def do_POST(self):
            try:
                self._route_post()
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass
            except (ValueError, RuntimeError) as exc:
                self.close_connection = True            # an unread body must not confuse the next request
                self._fail(400, str(exc))
            except Exception as exc:
                self.close_connection = True
                self._fail(500, str(exc))

        def _route_post(self):
            route = urllib.parse.urlparse(self.path).path
            if not self._authorized():
                return self._fail(403, "Not allowed.")
            if route == "/api/upload":
                return self._upload()
            if route == "/api/voice":
                return self._voice()
            payload = self._body()
            inside = (state.out_dir) if lan else None   # phone: only files inside the app folder

            if route == "/api/pick":
                if not self._local_only():
                    return
                if state.pick_file is None:
                    return self._json({"path": None, "unsupported": True})
                try:
                    chosen = state.pick_file(payload.get("kind", "video"))
                    library.remember(state.out_dir, chosen)
                    return self._json({"path": chosen})
                except Exception:
                    return self._json({"path": None, "unsupported": True})
            if route == "/api/start":
                job = state.jobs.start("make", make_start_job(state, payload, inside))
                return self._json({"job": job.id})
            if route == "/api/calibrate":
                job = state.jobs.start("calibrate", make_calibrate_job(state, payload, inside))
                return self._json({"job": job.id})
            if route == "/api/teach":
                from .. import teach
                action = payload.get("action")
                if action == "reset":
                    teach.reset(state.out_dir)
                elif action == "area":
                    teach.save_area(state.out_dir, payload.get("box"))
                elif action == "name":
                    source = _check_source(payload.get("source"), inside)
                    library.remember(state.out_dir, source)
                    teach.save_name(state.out_dir, source, _num(payload.get("time"), 0, 0),
                                    payload.get("box"))
                elif action == "learn":
                    job = state.jobs.start("teach", make_teach_job(state, payload, inside))
                    return self._json({"job": job.id})
                else:
                    raise ValueError("Unknown action.")
                return self._json(teach.describe(state.out_dir))
            if route == "/api/editor":
                return self._editor(payload)
            if route == "/api/find":
                return self._json(findapi.action(state, payload, _check_source, inside))
            if route == "/api/rerender":
                job = state.jobs.start("rerender", make_rerender_job(state, payload))
                return self._json({"job": job.id})
            if route == "/api/add_clip":
                job = state.jobs.start("add_clip", make_add_clip_job(state, payload))
                return self._json({"job": job.id})
            if route == "/api/open_folder":
                if not self._local_only():
                    return
                _open_in_explorer(project_dir(state, str(payload.get("project", ""))))
                return self._json({"ok": True})
            if route == "/api/chat":
                return self._chat(payload)
            if route == "/api/posttext":
                return self._post_texts(payload)
            if route == "/api/memory/clear":
                state.memory.clear()
                return self._json({"notes": []})
            if route == "/api/feedback":
                rating = payload.get("rating")
                if rating not in ("up", "down"):
                    raise ValueError("Bad rating.")
                record = {"time": time.time(), "rating": rating, "via": str(payload.get("via", ""))[:10],
                          "user": str(payload.get("user", ""))[:MAX_CHAT_TEXT],
                          "reply": str(payload.get("reply", ""))[:8000]}
                with open(state.feedback_file, "a", encoding="utf-8") as handle:
                    handle.write(json.dumps(record, ensure_ascii=False) + "\n")
                return self._json({"ok": True})
            if route == "/api/chat/clear":
                save_chat(state, [])
                return self._json({"ok": True})
            if route == "/api/settings":
                if not self._local_only():
                    return
                state.settings.update(payload)
                return self._json(state.settings.public())
            if route == "/api/settings/test":
                if not self._local_only():
                    return
                from .assistant import AssistantError, ping
                try:
                    return self._json({"ok": True, "reply": ping(state.settings, state.local_ai)})
                except AssistantError as exc:
                    return self._json({"ok": False, "error": str(exc)})
            if route == "/api/localai":
                if not self._local_only():
                    return
                action, model = payload.get("action"), str(payload.get("model", ""))
                try:
                    if action == "download":
                        state.local_ai.start_download(model)
                    elif action == "cancel":
                        state.local_ai.cancel_download()
                    elif action == "remove":
                        state.local_ai.remove(model)
                    else:
                        raise ValueError("Unknown action.")
                except LocalAIError as exc:
                    raise ValueError(str(exc))
                return self._json(state.local_ai.status())
            if route == "/api/lan":
                if not self._local_only():
                    return
                if payload.get("enabled"):
                    start_lan(state)
                else:
                    stop_lan(state)
                return self._json(lan_status(state))
            return self._fail(404, "Not found.")

        def _voice(self):
            """A microphone recording (raw bytes) -> {"text": ...}."""
            length = int(self.headers.get("Content-Length") or 0)
            if not 0 < length <= voice.MAX_AUDIO:
                self.close_connection = True
                raise ValueError("The recording is empty or too long.")
            return self._json({"text": voice.transcribe_audio(self.rfile.read(length))})

        def _editor(self, payload: dict):
            """Save the draft, or render it (preview or final)."""
            action, timeline = payload.get("action"), payload.get("timeline") or {}
            if action == "save":
                edits.save_draft(state.out_dir, timeline)
                return self._json({"ok": True})
            if action == "captions":                       # words of the timeline, from speech
                if lan:
                    for s in timeline.get("segments", []):
                        _check_source(s.get("source"), state.out_dir)
                plan = editor.clean(timeline)
                job = state.jobs.start("captions", lambda log: {
                    "captions": edits.captions(state.out_dir, plan, log=log)})
                return self._json({"job": job.id})
            if action not in ("preview", "export"):
                raise ValueError("Unknown action.")
            if lan:                                       # phone: only files inside the app folder
                used = [s.get("source") for s in timeline.get("segments", [])]
                used.append((timeline.get("music") or {}).get("path"))
                used += [o.get("source") for o in timeline.get("overlays") or []
                         if o.get("kind") != "sticker"]
                used += [a.get("path") for a in timeline.get("audio") or []]
                for path in filter(None, used):
                    _check_source(path, state.out_dir)
            plan = editor.clean(timeline)                 # fail now with a clear message
            title, small = payload.get("title", ""), action == "preview"
            job = state.jobs.start("edit", lambda log: edits.export(
                state.out_dir, plan, title, log=log, preview=small))
            return self._json({"job": job.id})

        def _chat(self, payload: dict):
            """One chat turn with the assistant."""
            from . import router
            from .assistant import AssistantError, ToolBox, ask
            text = str(payload.get("text", "")).strip()[:MAX_CHAT_TEXT]
            if not text:
                raise ValueError("Type a message first.")
            if not state.chat_lock.acquire(blocking=False):
                return self._fail(409, "The assistant is still answering the last message.")
            try:
                history = load_chat(state)
                toolbox = ToolBox(state, remote=lan)
                intent = router.parse(text)
                via = "rules"                              # answered by built-in rules, no AI needed
                try:
                    if intent is not None:
                        reply, actions = router.execute(intent, toolbox, state.memory)
                    elif not state.settings.configured():
                        reply, actions = NO_AI_REPLY, []
                    else:
                        via = "ai"
                        reply, actions = ask(state.settings, history, text, toolbox)
                except AssistantError as exc:
                    return self._fail(400, str(exc))
                now = time.time()
                history.append({"role": "user", "text": text, "time": now})
                ui = toolbox.ui
                history.append({"role": "assistant", "text": reply, "actions": actions, "via": via,
                                "jobs": toolbox.started_jobs, "time": time.time()})
                save_chat(state, history)
                return self._json({"reply": reply, "actions": actions, "jobs": toolbox.started_jobs,
                                   "via": via, "ui": ui})
            finally:
                state.chat_lock.release()

        def _upload(self):
            """Receive a video sent from the phone (raw body, name in the X-Filename header)."""
            length = int(self.headers.get("Content-Length") or 0)
            if length <= 0:
                raise ValueError("The file is empty.")
            if length > MAX_UPLOAD:
                raise ValueError("The file is too large (limit 20 GB).")
            name = safe_upload_name(self.headers.get("X-Filename", ""))
            folder = state.out_dir / "_uploads"
            folder.mkdir(parents=True, exist_ok=True)
            target = folder / name
            n = 1
            while target.exists():                      # never overwrite an earlier upload
                target = folder / f"{Path(name).stem}-{n}{Path(name).suffix}"
                n += 1
            part = target.with_suffix(target.suffix + ".part")
            left = length
            try:
                with open(part, "wb") as handle:
                    while left > 0:
                        chunk = self.rfile.read(min(CHUNK, left))
                        if not chunk:
                            raise ValueError("The upload was interrupted.")
                        handle.write(chunk)
                        left -= len(chunk)
                part.replace(target)
                library.remember(state.out_dir, target)
            finally:
                if part.exists():
                    part.unlink()
            self._json({"path": str(target), "name": target.name})

    server = ThreadingHTTPServer(("0.0.0.0" if lan else "127.0.0.1", port), Handler)
    server.daemon_threads = True
    if not lan:
        state.port = server.server_address[1]
    return server


# ---------------------------------------------------------------------------
# Phone access (the second door)
# ---------------------------------------------------------------------------
def start_lan(state: AppState) -> None:
    """Open the phone door (idempotent)."""
    if state.lan_server is not None:
        return
    server = make_server(state, 0, lan=True)
    state.lan_server = server
    state.lan_port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()


def stop_lan(state: AppState) -> None:
    """Close the phone door."""
    server, state.lan_server, state.lan_port = state.lan_server, None, None
    if server is not None:
        server.shutdown()
        server.server_close()


def lan_status(state: AppState) -> dict:
    """What the Settings window shows about phone access."""
    if state.lan_server is None:
        return {"enabled": False}
    ip = lan_tools.local_ip()
    if not ip:
        return {"enabled": True, "url": "", "qr": "",
                "problem": "This computer does not seem to be on a Wi-Fi/network."}
    url = f"http://{ip}:{state.lan_port}/?t={state.token}"
    return {"enabled": True, "url": url, "qr": lan_tools.qr_svg(url)}


def _open_in_explorer(folder: Path) -> None:
    """Show a folder in the system file manager."""
    if os.name == "nt":
        os.startfile(str(folder))                                  # noqa: S606 (Windows only)
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(folder)])
    else:
        subprocess.Popen(["xdg-open", str(folder)])
