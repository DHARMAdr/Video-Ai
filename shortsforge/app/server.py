"""
server.py - a tiny web server that lives only on your own computer (127.0.0.1).

WHY it exists:
    The window is a web page. A web page cannot touch your files or run ffmpeg by itself, so it
    asks this server to do it ("make shorts from this video", "give me clip 2", ...).

HOW it works:
    - Python's built-in http.server (nothing to install).
    - SAFETY: it only listens on 127.0.0.1 (this computer), checks a secret token that is
      created fresh every time the app starts, and only checks Host names we expect. So a random
      website open in your browser cannot control the app or read your files.
    - Files can only be served from the output folder (Documents/ShortsForge), never elsewhere.
    - Video preview needs HTTP "Range" requests (so you can jump around in a clip); supported.

ROUTES (all need the token):
    GET  /                 the page            GET  /api/info        version, folders
    GET  /api/projects     past projects       GET  /api/project     one project's clips
    GET  /api/job          progress of a task  GET  /files/...       a clip / picture
    POST /api/pick         file dialog         POST /api/start       make shorts
    POST /api/calibrate    check kill scan     POST /api/rerender    export a clip again
    POST /api/open_folder  show in Explorer

HOW TO IMPROVE:
    - Add routes for new features (delete project, rename, batch queue, AI chat).
    - Add a Cancel route once the work runs in a separate process.
"""

import json
import mimetypes
import os
import secrets
import shutil
import subprocess
import sys
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .. import __version__, paths
from .jobs import JobManager

STATIC_DIR = Path(__file__).parent / "static"
CHUNK = 256 * 1024


class AppState:
    """Everything the handlers share."""

    def __init__(self, out_dir):
        self.out_dir = Path(out_dir).resolve()
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.token = secrets.token_urlsafe(16)    # secret, new on every start
        self.jobs = JobManager()
        self.pick_file = None                     # set by desktop.py when a native dialog exists
        self.port = None


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


# ---------------------------------------------------------------------------
# Jobs (what the buttons start)
# ---------------------------------------------------------------------------
def _project_name(state: AppState, result: dict) -> str:
    """Folder name of the project, relative to the output folder."""
    return Path(result["project"]).resolve().relative_to(state.out_dir).parts[0]


def _check_source(source: str) -> str:
    """Make sure the video exists (or looks like a link)."""
    from .. import ingest
    source = clean_path(source)
    if not source:
        raise ValueError("Choose a video first.")
    if not ingest.is_url(source) and not Path(source).is_file():
        raise ValueError(f"File not found: {source}")
    return source


def make_start_job(state: AppState, payload: dict):
    """Build the function for a 'make shorts' job."""
    source = _check_source(payload.get("source"))
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
            try:
                res = pipeline.run_game(
                    source, game="valorant", out_root=out_root, count=count,
                    min_kills=int(_num(o.get("min_kills"), 1, 1, 5)), layout=layout,
                    facecam=facecam, with_popups=bool(o.get("popups", True)),
                    hook_title=bool(o.get("hook_title", True)),
                    speech_captions=bool(o.get("speech", False)), overrides=overrides, log=log)
            except RuntimeError as exc:
                if "No kills were detected" in str(exc):
                    raise RuntimeError(
                        "No kills were found. Open 'Check kill detection' in the left panel "
                        "to adjust the scan area and colour.")
                raise
            return {"project_name": _project_name(state, res), "count": len(res["shorts"])}
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


def make_calibrate_job(state: AppState, payload: dict):
    """Build the function for a 'check kill detection' job."""
    source = _check_source(payload.get("source"))
    time_s = _num(payload.get("time"), 0, 0)
    roi = _floats(payload.get("roi"), 4)
    out = state.out_dir / "_calibrate"

    def job(log):
        from ..calibrate import calibrate
        res = calibrate(source, time_s, "valorant", None, roi, str(out), log=log)
        return {"rows": res["rows"],
                "images": ["_calibrate/full_frame.png", "_calibrate/roi.png", "_calibrate/mask.png"]}
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


# ---------------------------------------------------------------------------
# HTTP handler
# ---------------------------------------------------------------------------
def make_server(state: AppState, port: int = 0) -> ThreadingHTTPServer:
    """Create the server (port 0 = pick any free port)."""

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args):          # keep the console quiet
            pass

        # ----- helpers -----------------------------------------------------
        def _query(self):
            return urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)

        def _authorized(self) -> bool:
            host = (self.headers.get("Host") or "").split(":")[0]
            if host not in ("127.0.0.1", "localhost"):
                return False                    # blocks "DNS rebinding" tricks
            given = self.headers.get("X-Token") or (self._query().get("t") or [""])[0]
            return secrets.compare_digest(given, state.token)

        def _send(self, status: int, body: bytes, ctype: str, extra=None):
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
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
            return json.loads(self.rfile.read(length).decode("utf-8") or "{}")

        def _project_dir(self, name: str) -> Path:
            if not name or Path(name).name != name or name.startswith("."):
                raise ValueError("Bad project name.")
            folder = state.out_dir / name
            if not folder.is_dir():
                raise ValueError("Project not found.")
            return folder

        # ----- GET -----------------------------------------------------------
        def do_GET(self):
            try:
                self._route_get()
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass                            # the window closed the connection; fine
            except Exception as exc:
                self._fail(500, str(exc))

        def _route_get(self):
            route = urllib.parse.urlparse(self.path).path
            if not self._authorized():
                return self._fail(403, "Not allowed.")
            q = self._query()

            if route == "/":
                page = (STATIC_DIR / "index.html").read_bytes()
                return self._send(200, page, "text/html; charset=utf-8")
            if route == "/api/info":
                return self._json({"version": __version__, "out_dir": str(state.out_dir),
                                   "can_browse": state.pick_file is not None,
                                   "ffmpeg": shutil.which("ffmpeg") is not None,
                                   "model_bundled": paths.has_bundled_model("small")})
            if route == "/api/job":
                try:
                    return self._json(state.jobs.snapshot((q.get("id") or [""])[0],
                                                          int((q.get("since") or ["0"])[0])))
                except KeyError as exc:
                    return self._fail(404, str(exc))
            if route == "/api/projects":
                return self._json(self._list_projects())
            if route == "/api/project":
                folder = self._project_dir((q.get("name") or [""])[0])
                shorts_file = folder / "shorts.json"
                meta_file = folder / "project.json"
                return self._json({
                    "name": folder.name,
                    "shorts": json.loads(shorts_file.read_text("utf-8")) if shorts_file.exists() else [],
                    "meta": json.loads(meta_file.read_text("utf-8")) if meta_file.exists() else {}})
            if route.startswith("/files/"):
                return self._serve_file(urllib.parse.unquote(route[len("/files/"):]))
            return self._fail(404, "Not found.")

        def _list_projects(self) -> list:
            found = []
            for folder in state.out_dir.iterdir():
                shorts = folder / "shorts.json"
                if folder.is_dir() and not folder.name.startswith("_") and shorts.exists():
                    try:
                        count = len(json.loads(shorts.read_text("utf-8")))
                    except ValueError:
                        count = 0
                    found.append({"name": folder.name, "count": count,
                                  "modified": shorts.stat().st_mtime})
            return sorted(found, key=lambda p: p["modified"], reverse=True)

        def _serve_file(self, relative: str):
            target = (state.out_dir / relative).resolve()
            try:
                target.relative_to(state.out_dir)       # must stay inside the output folder
            except ValueError:
                return self._fail(403, "Not allowed.")
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
                self._fail(400, str(exc))
            except Exception as exc:
                self._fail(500, str(exc))

        def _route_post(self):
            route = urllib.parse.urlparse(self.path).path
            if not self._authorized():
                return self._fail(403, "Not allowed.")
            payload = self._body()

            if route == "/api/pick":
                if state.pick_file is None:
                    return self._json({"path": None, "unsupported": True})
                try:
                    return self._json({"path": state.pick_file(payload.get("kind", "video"))})
                except Exception:
                    return self._json({"path": None, "unsupported": True})
            if route == "/api/start":
                job = state.jobs.start("make", make_start_job(state, payload))
                return self._json({"job": job.id})
            if route == "/api/calibrate":
                job = state.jobs.start("calibrate", make_calibrate_job(state, payload))
                return self._json({"job": job.id})
            if route == "/api/rerender":
                job = state.jobs.start("rerender", make_rerender_job(state, payload))
                return self._json({"job": job.id})
            if route == "/api/open_folder":
                folder = self._project_dir(str(payload.get("project", "")))
                _open_in_explorer(folder)
                return self._json({"ok": True})
            return self._fail(404, "Not found.")

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.daemon_threads = True
    state.port = server.server_address[1]
    return server


def _open_in_explorer(folder: Path) -> None:
    """Show a folder in the system file manager."""
    if os.name == "nt":
        os.startfile(str(folder))                                  # noqa: S606 (Windows only)
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(folder)])
    else:
        subprocess.Popen(["xdg-open", str(folder)])
