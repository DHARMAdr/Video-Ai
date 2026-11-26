"""
report.py - one text report that explains the state of the app when something goes wrong.

WHY it exists:
    "It did not work" is hard to fix. This report shows the versions, which parts are present,
    the graphics card the AI sees, what you taught, and the last log lines. Copy it into a chat
    with Claude (or any helper).

HOW it works:
    Plain text, built from the app's own state. API keys are never included, and your Windows
    user name is replaced by <you>.

HOW TO IMPROVE:
    - Add the report of the last project (kill times, reasons).
"""

import os
import platform
import shutil
import subprocess
from pathlib import Path

from .. import __version__, paths, teach


def _tail(path: Path, lines: int = 40) -> str:
    try:
        with open(path, "rb") as handle:
            handle.seek(0, os.SEEK_END)
            handle.seek(max(0, handle.tell() - 20000))
            text = handle.read().decode("utf-8", "replace")
        return "\n".join(text.splitlines()[-lines:])
    except OSError:
        return "(none)"


def _run(command: list) -> str:
    try:
        out = subprocess.run(command, capture_output=True, text=True, timeout=30)
        return (out.stdout or out.stderr).strip()
    except (OSError, subprocess.SubprocessError) as exc:
        return f"failed: {exc}"


def build(state) -> str:
    ffmpeg = shutil.which("ffmpeg")
    ai = state.local_ai.status()
    jobs = list(state.jobs.jobs.values())
    out = [f"ShortsForge {__version__} report",
           f"System: {platform.system()} {platform.release()}, {os.cpu_count()} processor threads",
           f"ffmpeg: {_run([ffmpeg, '-version']).splitlines()[0] if ffmpeg else 'NOT FOUND'}",
           f"Speech model bundled: {paths.has_bundled_model('small')}",
           f"AI engine present: {ai['engine']}; graphics cards it sees: "
           f"{', '.join(ai['devices']) or 'none (runs on the processor, which is slow)'}",
           f"Assistant: {state.settings.data.get('provider')}",
           f"Teach: {teach.describe(state.out_dir)}"]
    if jobs:
        job = jobs[-1]
        out += [f"\n--- last task: {job.kind} / {job.status} ---", *job.log[-30:]]
    out += ["\n--- app.log (end) ---", _tail(state.out_dir / "app.log"),
            "\n--- AI engine.log (end) ---", _tail(state.local_ai.dir / "engine.log", 25)]
    return "\n".join(str(x) for x in out).replace(str(Path.home()), "<you>")
