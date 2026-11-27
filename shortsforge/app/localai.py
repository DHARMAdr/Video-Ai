"""
localai.py - the built-in offline AI: downloads a model once, then runs it on YOUR PC.

WHY it exists:
    Before this, the assistant needed Claude (paid API key) or a separate program such as Ollama.
    Now ShortsForge can chat and operate your videos by itself: no account, no key, and no
    internet after the one-time model download.

HOW it works:
    - The ENGINE is "llama-server" from the llama.cpp project (MIT licence). The Windows build
      puts it in the app folder `llama/`. The Vulkan version runs on NVIDIA, AMD and Intel
      graphics cards, and falls back to the processor when no usable card is found.
    - The MODEL is a Qwen3.5 file in GGUF format (Apache-2.0 licence), downloaded when you press
      the button. Downloads can resume, and the file is only accepted if its SHA-256 checksum
      matches the one written below (so a damaged or swapped file is never used).
    - Each model can have a second small file, the "picture reader". With it the model can look
      at video frames (used by the Find tab). It is a separate download.
    - When you chat, we start the engine on 127.0.0.1 (this PC only) with a random password.
      It speaks the same "OpenAI format" the assistant already understands.
    - After 10 minutes without a question the engine is stopped, to free graphics memory.

WHERE the files are:
    %LOCALAPPDATA%\\ShortsForge\\ai  (not in Documents, so OneDrive does not try to upload GBs).

HOW TO IMPROVE:
    - Add more models to MODELS (copy one entry; get size and sha256 from the model's page).
    - Add a CUDA engine build for a bit more speed on NVIDIA cards.
    - Stream the answer word by word.
"""

import atexit
import hashlib
import json
import os
import re
import secrets
import shutil
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

from .. import paths

_HF = "https://huggingface.co/{repo}/resolve/{revision}/{file}"


def _model(label, note, size_name, revision, size, sha256):
    """Build one catalogue entry. The revision pins the exact version of the file."""
    repo = f"unsloth/Qwen3.5-{size_name}-GGUF"
    file = f"Qwen3.5-{size_name}-Q4_K_M.gguf"
    return {"label": label, "note": note, "file": file, "size": size, "sha256": sha256,
            "url": _HF.format(repo=repo, revision=revision, file=file)}


def _eyes(model: dict, size_name: str, revision: str, size: int, sha256: str) -> dict:
    """Add the "picture reader" (llama.cpp calls it mmproj) that lets a model see images."""
    repo = f"unsloth/Qwen3.5-{size_name}-GGUF"
    model["vision"] = {"file": f"mmproj-Qwen3.5-{size_name}-F16.gguf", "size": size, "sha256": sha256,
                       "url": _HF.format(repo=repo, revision=revision, file="mmproj-F16.gguf")}
    return model


MODELS = {
    "qwen3.5-9b": _model(
        "Qwen3.5 9B (smartest)", "For a graphics card with 8 GB or more.", "9B",
        "3885219b6810b007914f3a7950a8d1b469d598a5", 5680522464,
        "03b74727a860a56338e042c4420bb3f04b2fec5734175f4cb9fa853daf52b7e8"),
    "qwen3.5-4b": _model(
        "Qwen3.5 4B (lighter, faster)", "For 4-6 GB cards, or if the 9B is slow.", "4B",
        "e87f176479d0855a907a41277aca2f8ee7a09523", 2740937888,
        "00fe7986ff5f6b463e62455821146049db6f9313603938a70800d1fb69ef11a4"),
}
_eyes(MODELS["qwen3.5-9b"], "9B", "3885219b6810b007914f3a7950a8d1b469d598a5", 918166080,
      "f70dc3509053962b0d0d3ee8a7eacebf5d60aa560cad78254ae8698516ae029f")
_eyes(MODELS["qwen3.5-4b"], "4B", "e87f176479d0855a907a41277aca2f8ee7a09523", 672423616,
      "cd88edcf8d031894960bb0c9c5b9b7e1fea6ebee02b9f7ce925a00d12891f864")
EYES = "+eyes"                  # "qwen3.5-9b+eyes" means: the picture reader of that model
VISION_CONTEXT_TOKENS = 8192    # smaller memory of text, so pictures also fit on 8 GB cards
DEFAULT_MODEL = "qwen3.5-9b"

CONTEXT_TOKENS = 16384          # how much text the model can keep in mind (more = more memory)
START_TIMEOUT = 240             # seconds to wait while the model loads
IDLE_SECONDS = 600              # stop the engine after this long without a question
CHUNK = 1024 * 1024

# Requests to our own engine must never go through a system proxy.
_DIRECT = urllib.request.build_opener(urllib.request.ProxyHandler({}))


class LocalAIError(Exception):
    """A problem with a message that is safe and understandable to show to the user."""


def default_data_dir() -> Path:
    """Where models are stored."""
    base = os.environ.get("LOCALAPPDATA")
    return (Path(base) / "ShortsForge" if base else Path.home() / ".shortsforge") / "ai"


def find_engine():
    """Path of llama-server: the copy inside the app first, then one installed on the PC."""
    name = "llama-server.exe" if os.name == "nt" else "llama-server"
    override = os.environ.get("SHORTSFORGE_LLAMA_SERVER")        # used by tests / developers
    if override:
        return override if Path(override).is_file() else None
    for root in paths._roots():
        candidate = root / "llama" / name
        if candidate.is_file():
            return str(candidate)
    return shutil.which(name)


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _tie_to_parent(process) -> None:
    """Windows only: make the engine close even if ShortsForge crashes or is force-closed.

    A "job object" with the kill-on-close flag does that. If anything here fails we simply
    carry on; the normal stop() on exit still works.
    """
    if os.name != "nt":
        return
    try:
        import ctypes
        from ctypes import wintypes

        class Basic(ctypes.Structure):
            _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64),
                        ("PerJobUserTimeLimit", ctypes.c_int64), ("LimitFlags", wintypes.DWORD),
                        ("MinimumWorkingSetSize", ctypes.c_size_t),
                        ("MaximumWorkingSetSize", ctypes.c_size_t),
                        ("ActiveProcessLimit", wintypes.DWORD), ("Affinity", ctypes.c_size_t),
                        ("PriorityClass", wintypes.DWORD), ("SchedulingClass", wintypes.DWORD)]

        class Extended(ctypes.Structure):
            _fields_ = [("BasicLimitInformation", Basic), ("IoInfo", ctypes.c_uint64 * 6),
                        ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                        ("PeakProcessMemoryUsed", ctypes.c_size_t),
                        ("PeakJobMemoryUsed", ctypes.c_size_t)]

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.CreateJobObjectW.restype = wintypes.HANDLE
        kernel.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int,
                                                   ctypes.c_void_p, wintypes.DWORD]
        kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        job = kernel.CreateJobObjectW(None, None)
        info = Extended()
        info.BasicLimitInformation.LimitFlags = 0x2000          # KILL_ON_JOB_CLOSE
        kernel.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info))
        kernel.AssignProcessToJobObject(job, int(process._handle))
        process._shortsforge_job = job                          # keep the handle open
    except Exception:                                            # noqa: BLE001
        pass


class LocalAI:
    """One object that knows about the model files, the download and the running engine."""

    def __init__(self, data_dir=None, models=None):
        self.dir = Path(data_dir) if data_dir else default_data_dir()
        self.models = models or MODELS
        self._lock = threading.Lock()                # protects the engine process
        self._dl_lock = threading.Lock()             # protects the download state
        self._cancel = threading.Event()
        self.download = {"state": "idle", "model": "", "done": 0, "total": 0, "error": ""}
        self.process = None
        self.running_model = None
        self.running_vision = False
        self._devices = None
        self.url = self.key = None
        self.idle_seconds = IDLE_SECONDS
        self._last_used = 0.0
        self._active = 0                             # chats being answered right now
        self._watching = False
        atexit.register(self.stop)

    # ----- model files ---------------------------------------------------------------------
    def _entry(self, model_id: str) -> dict:
        if str(model_id).endswith(EYES):                     # the picture reader of a model
            model = self.models.get(model_id[:-len(EYES)])
            if not model or "vision" not in model:
                raise LocalAIError("This model has no picture reader.")
            return {**model["vision"], "label": f"The picture reader of {model['label']}"}
        if model_id not in self.models:
            raise LocalAIError("Unknown model.")
        return self.models[model_id]

    def model_path(self, model_id: str) -> Path:
        return self.dir / self._entry(model_id)["file"]

    def installed(self, model_id: str) -> bool:
        """True when the file is there and complete (the checksum was checked at download)."""
        try:
            entry = self._entry(model_id)
        except LocalAIError:
            return False
        path = self.model_path(model_id)
        return path.is_file() and path.stat().st_size == entry["size"]

    def status(self) -> dict:
        """Everything the Settings window needs."""
        with self._dl_lock:
            download = dict(self.download)
        return {"engine": find_engine() is not None, "folder": str(self.dir),
                "devices": self.devices(),
                "running": self.running_model if self._alive() else None, "download": download,
                "models": [{"id": key, "label": m["label"], "note": m["note"], "size": m["size"],
                            "installed": self.installed(key),
                            "vision_size": m.get("vision", {}).get("size", 0),
                            "vision_installed": self.installed(key + EYES)}
                           for key, m in self.models.items()]}

    # ----- downloading ---------------------------------------------------------------------
    def start_download(self, model_id: str) -> None:
        """Begin downloading in the background. Video tasks can keep running meanwhile."""
        entry = self._entry(model_id)
        with self._dl_lock:
            if self.download["state"] in ("downloading", "checking"):
                raise LocalAIError("A model is already downloading.")
            if self.installed(model_id):
                raise LocalAIError("That model is already downloaded.")
            self._cancel.clear()
            self.download = {"state": "downloading", "model": model_id, "done": 0,
                             "total": entry["size"], "error": ""}
        threading.Thread(target=self._download, args=(model_id,), daemon=True).start()

    def cancel_download(self) -> None:
        self._cancel.set()

    def _set(self, **values) -> None:
        with self._dl_lock:
            self.download.update(values)

    def _download(self, model_id: str) -> None:
        entry = self._entry(model_id)
        final = self.model_path(model_id)
        part = final.with_name(final.name + ".part")
        try:
            self.dir.mkdir(parents=True, exist_ok=True)
            have = part.stat().st_size if part.exists() else 0
            if have > entry["size"]:
                part.unlink()
                have = 0
            free = shutil.disk_usage(self.dir).free
            if free < entry["size"] - have + 500 * 1024 ** 2:
                raise LocalAIError(f"Not enough disk space: need about "
                                   f"{(entry['size'] - have) / 1e9 + 0.5:.1f} GB free.")
            if have < entry["size"]:
                headers = {"User-Agent": "ShortsForge"}
                if have:
                    headers["Range"] = f"bytes={have}-"          # resume where we stopped
                request = urllib.request.Request(entry["url"], headers=headers)
                with urllib.request.urlopen(request, timeout=60) as response:
                    if have and response.status != 206:          # server ignored the range
                        have = 0
                    with open(part, "ab" if have else "wb") as out:
                        self._set(done=have)
                        while True:
                            if self._cancel.is_set():
                                self._set(state="cancelled")
                                return                           # keep .part for resuming
                            chunk = response.read(CHUNK)
                            if not chunk:
                                break
                            out.write(chunk)
                            have += len(chunk)
                            if have > entry["size"]:
                                break
                            self._set(done=have)
            if have < entry["size"]:
                raise LocalAIError("The download stopped early. Press Download to continue it.")
            self._set(state="checking", done=have)
            digest = hashlib.sha256()
            with open(part, "rb") as handle:
                for chunk in iter(lambda: handle.read(CHUNK), b""):
                    digest.update(chunk)
            if have != entry["size"] or digest.hexdigest() != entry["sha256"]:
                part.unlink()
                raise LocalAIError("The downloaded file failed its safety check and was deleted. "
                                   "Please download it again.")
            part.replace(final)
            self._set(state="done")
        except LocalAIError as exc:
            self._set(state="error", error=str(exc))
        except Exception as exc:                                   # noqa: BLE001
            self._set(state="error", error=f"Download failed ({exc}). Check your internet and "
                                           "press Download to continue.")

    def remove(self, model_id: str) -> None:
        """Delete a downloaded model to get the disk space back."""
        path = self.model_path(model_id)
        with self._dl_lock:
            if self.download["model"] == model_id and self.download["state"] in ("downloading",
                                                                                "checking"):
                raise LocalAIError("Cancel the download first.")
            self.download = {"state": "idle", "model": "", "done": 0, "total": 0, "error": ""}
        if self.running_model == model_id.replace(EYES, ""):
            self.stop()
        targets = [path, path.with_name(path.name + ".part")]
        if model_id in self.models and "vision" in self.models[model_id]:   # remove its eyes too
            eyes = self.model_path(model_id + EYES)
            targets += [eyes, eyes.with_name(eyes.name + ".part")]
        for target in targets:
            if target.exists():
                target.unlink()

    # ----- running the engine ----------------------------------------------------------------
    def _alive(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def devices(self) -> list:
        """Graphics cards the engine can use (empty list = it runs on the processor only)."""
        if self._devices is None:
            engine = find_engine()
            if not engine:
                return []
            try:
                out = subprocess.run([engine, "--list-devices"], capture_output=True, text=True,
                                     timeout=60)
                text = (out.stdout or "") + "\n" + (out.stderr or "")
                self._devices = [line.strip() for line in text.split("Available devices:")[-1]
                                 .splitlines() if re.match(r"\s*\w+\d+:", line)]
            except (OSError, subprocess.SubprocessError):
                return []
        return self._devices

    def command(self, engine: str, model_id: str, port: int, vision: bool = False) -> list:
        """The command line that starts the engine."""
        command = [engine, "-m", str(self.model_path(model_id)),
                "--host", "127.0.0.1", "--port", str(port),
                "--ctx-size", str(VISION_CONTEXT_TOKENS if vision else CONTEXT_TOKENS),
                "--parallel", "1",                                  # one user, one chat at a time
                "--jinja",                                          # needed for tool calls
                "--reasoning", "off",                               # answer directly
                "--alias", model_id]
        if vision:
            command += ["--mmproj", str(self.model_path(model_id + EYES))]
        return command

    def ensure_running(self, model_id: str, vision: bool = False) -> dict:
        """Start the engine if needed. Returns the settings the assistant uses to talk to it."""
        entry = self._entry(model_id)
        with self._lock:
            if not (self._alive() and self.running_model == model_id
                    and (self.running_vision or not vision)):
                self._stop_locked()
                engine = find_engine()
                if not engine:
                    raise LocalAIError("The AI engine is missing from this copy of ShortsForge. "
                                       "Download the app again.")
                if not self.installed(model_id):
                    raise LocalAIError(f"Download {entry['label']} first (Settings > Built-in AI).")
                if vision and not self.installed(model_id + EYES):
                    raise LocalAIError("Download the picture reader first (Settings > Built-in AI).")
                self._start_locked(engine, model_id, vision)
            self._last_used = time.time()
            return {"base_url": self.url + "/v1", "api_key": self.key, "model": model_id}

    def _start_locked(self, engine: str, model_id: str, vision: bool = False) -> None:
        port = _free_port()
        self.key = secrets.token_urlsafe(24)
        self.url = f"http://127.0.0.1:{port}"
        self.dir.mkdir(parents=True, exist_ok=True)
        log_path = self.dir / "engine.log"
        # The password goes through the environment so it does not show in the process list.
        env = dict(os.environ, LLAMA_API_KEY=self.key)
        with open(log_path, "wb") as log:
            try:
                self.process = subprocess.Popen(self.command(engine, model_id, port, vision), env=env,
                                                stdout=log, stderr=subprocess.STDOUT,
                                                stdin=subprocess.DEVNULL)
            except OSError as exc:
                raise LocalAIError(f"The AI engine could not start ({exc}).") from exc
        _tie_to_parent(self.process)
        deadline = time.time() + START_TIMEOUT
        while time.time() < deadline:
            if self.process.poll() is not None:
                code, self.process = self.process.returncode, None
                raise LocalAIError(
                    f"The AI engine stopped while loading (code {code}). Try the smaller model, "
                    f"close other games or programs, or send me this file: {log_path}")
            try:
                with _DIRECT.open(self.url + "/health", timeout=5) as response:
                    if json.loads(response.read()).get("status") == "ok":
                        self.running_model = model_id
                        self.running_vision = vision
                        self._last_used = time.time()
                        self._watch()
                        return
            except (urllib.error.URLError, OSError, ValueError):
                pass                                            # still loading
            time.sleep(0.3)
        self._stop_locked()
        raise LocalAIError(f"The model took too long to load. Details: {log_path}")

    def busy(self, active: bool) -> None:
        """The assistant calls this around a chat so we never stop the engine mid-answer."""
        with self._lock:
            self._active = max(0, self._active + (1 if active else -1))
            self._last_used = time.time()

    def _watch(self) -> None:
        """Background check that stops an unused engine."""
        if self._watching:
            return
        self._watching = True

        def loop():
            while True:
                time.sleep(min(30.0, max(0.2, self.idle_seconds / 4)))
                with self._lock:
                    if not self._alive():
                        break
                    if not self._active and time.time() - self._last_used > self.idle_seconds:
                        self._stop_locked()
                        break
            self._watching = False

        threading.Thread(target=loop, daemon=True).start()

    def stop(self) -> None:
        with self._lock:
            self._stop_locked()

    def _stop_locked(self) -> None:
        process, self.process, self.running_model = self.process, None, None
        if process is None or process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)
