"""
ingest.py - gets the source video onto your disk and reads basic facts about it.

WHY it exists:
    Every later step needs a local video file plus its size, length and whether it has sound.
    The user may give a local file OR a link, so this step hides that difference.

HOW it works:
    - If the input starts with http(s):// we call yt-dlp (a free downloader) to fetch it.
    - `probe()` runs ffprobe (comes with ffmpeg) and reads width, height, duration, audio.

IMPORTANT (legal): only download or edit videos you own or have permission to reuse.
    Re-uploading other people's content can get your channel struck.

HOW TO IMPROVE:
    - Support cookies for age-restricted / private videos (yt-dlp --cookies-from-browser).
    - Re-use an already downloaded file instead of downloading again.
    - Support whole playlists / channels in batch mode.
"""

import json
import re
import subprocess
from pathlib import Path


def is_url(text: str) -> bool:
    """True if the text looks like a web link."""
    return bool(re.match(r"^https?://", text.strip(), re.IGNORECASE))


def download(url: str, dest_dir: Path) -> Path:
    """Download a video with yt-dlp into dest_dir and return the file path."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    existing = sorted(dest_dir.glob("source.*"))
    if existing:  # already downloaded on a previous run -> skip, saves time
        return existing[0]
    import yt_dlp   # imported here so the rest of the tool works even without yt-dlp
    options = {
        "format": "bv*[height<=1080]+ba/b",     # best video up to 1080p + best audio
        "merge_output_format": "mp4",
        "noplaylist": True,
        "outtmpl": str(dest_dir / "source.%(ext)s"),
        "quiet": True,
        "no_warnings": True,
    }
    # (We call yt-dlp as a library, not as a separate program, so it also works inside the
    #  packaged app where there is no separate Python to run.)
    with yt_dlp.YoutubeDL(options) as downloader:
        downloader.download([url])
    found = sorted(dest_dir.glob("source.*"))
    if not found:
        raise RuntimeError("yt-dlp finished but no file was created.")
    return found[0]


def probe(video: Path) -> dict:
    """Ask ffprobe about the video. Returns width, height, duration (seconds), has_audio."""
    cmd = [
        "ffprobe", "-v", "error", "-print_format", "json",
        "-show_streams", "-show_format", str(video),
    ]
    out = subprocess.run(cmd, capture_output=True, text=True, check=True).stdout
    data = json.loads(out)
    video_stream = next((s for s in data["streams"] if s["codec_type"] == "video"), None)
    if video_stream is None:
        raise RuntimeError("No video stream found in this file.")
    has_audio = any(s["codec_type"] == "audio" for s in data["streams"])
    return {
        "width": int(video_stream["width"]),
        "height": int(video_stream["height"]),
        "duration": float(data["format"]["duration"]),
        "has_audio": has_audio,
    }
