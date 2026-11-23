"""
jobs.py - runs long tasks (making shorts takes minutes) in the background.

WHY it exists:
    If the window waited for the work to finish, it would freeze. Instead the window starts a
    "job", then asks every second "how is it going?" and shows the log lines as they appear.

HOW it works:
    - JobManager.start() creates a Job and runs your function in a new thread.
    - Your function receives a `log(text)` function; every call adds one line to job.log.
    - The window polls snapshot(job_id, since) and gets only the NEW log lines.
    - Only ONE job runs at a time (video work uses a lot of CPU, two at once would be slow).

HOW TO IMPROVE:
    - Add a real Cancel button (run the work in a separate process so it can be stopped).
    - Add a progress percentage (let the pipeline report numbers, not only text).
"""

import threading
import time
import traceback
import uuid


class Job:
    """One background task and everything the window needs to show about it."""

    def __init__(self, kind: str):
        self.id = uuid.uuid4().hex[:10]
        self.kind = kind
        self.status = "running"          # running -> done | error
        self.log = []                    # list of text lines
        self.result = None               # whatever the task returned
        self.error = None                # friendly error text if it failed
        self.started = time.time()
        self.lock = threading.Lock()

    def write(self, text) -> None:
        """Add a log line (this is the `log` function the tasks receive)."""
        with self.lock:
            self.log.append(str(text))


class JobManager:
    """Keeps all jobs of this session."""

    def __init__(self):
        self.jobs = {}
        self._lock = threading.Lock()

    def start(self, kind: str, func) -> Job:
        """Run func(log) in a thread. Refuses if another job is still running."""
        with self._lock:
            if any(j.status == "running" for j in self.jobs.values()):
                raise RuntimeError("Another task is still running. Wait until it finishes.")
            job = Job(kind)
            self.jobs[job.id] = job

        def runner():
            try:
                job.result = func(job.write)
                job.status = "done"
            except Exception as exc:                       # show every failure in the window
                job.error = _friendly(exc)
                job.write(traceback.format_exc())          # full details stay in the log
                job.status = "error"

        threading.Thread(target=runner, daemon=True).start()
        return job

    def snapshot(self, job_id: str, since: int = 0) -> dict:
        """State of a job + only the log lines after index `since`."""
        job = self.jobs.get(job_id)
        if job is None:
            raise KeyError("Unknown task.")
        with job.lock:
            lines = job.log[since:]
            return {"status": job.status, "log": lines, "next": since + len(lines),
                    "result": job.result, "error": job.error}


def _friendly(exc: Exception) -> str:
    """Turn technical errors into one understandable sentence."""
    text = str(exc) or exc.__class__.__name__
    if exc.__class__.__name__ == "CalledProcessError":
        return "ffmpeg could not process this video. The file may be damaged or an unusual format."
    if isinstance(exc, ModuleNotFoundError) and "faster_whisper" in text:
        return "The speech recognition part is missing from this build."
    return text
