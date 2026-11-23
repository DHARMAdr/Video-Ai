"""
render.py - cuts the final vertical MP4 with ffmpeg.

WHY it exists:
    This is where the plan becomes a real file: cut -> reframe to 9:16 -> burn captions ->
    normalise loudness -> encode in a format every platform accepts.

HOW it works:
    One ffmpeg command does everything:
      -ss/-t          cut the time range
      -vf             reframe filter (+ subtitles filter if captions are on)
      loudnorm        sets loudness near -14 LUFS (typical for YouTube/Instagram)
      libx264 + aac   the safe, universal video/audio codecs
    We run ffmpeg INSIDE the folder that holds the .ass file and refer to it by plain file
    name, because file paths with "C:\\" confuse ffmpeg's subtitle filter on Windows.

HOW TO IMPROVE:
    - Use GPU encoding (h264_nvenc) when an NVIDIA card exists, for much faster renders.
    - Add intro/outro, background music ducking, zoom-punch on emphasis, progress bar.
    - Show a real progress percentage by parsing ffmpeg's -progress output.
"""

import subprocess
from pathlib import Path


def render_clip(video: Path, start: float, end: float, out_file: Path,
                reframe_filter: str, ass_file=None) -> None:
    """Create one finished short at out_file."""
    out_file.parent.mkdir(parents=True, exist_ok=True)
    video, out_file = Path(video).resolve(), Path(out_file).resolve()

    vf = reframe_filter
    cwd = None
    if ass_file is not None:
        ass_file = Path(ass_file).resolve()
        vf = f"{vf},subtitles={ass_file.name}"   # plain name, see module notes
        cwd = ass_file.parent

    cmd = [
        "ffmpeg", "-y", "-v", "error",
        "-ss", f"{start:.3f}", "-t", f"{end - start:.3f}", "-i", str(video),
        "-vf", vf,
        "-af", "loudnorm=I=-14:TP=-1.5:LRA=11",
        "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "160k",
        "-movflags", "+faststart",               # lets the video start playing before it fully loads
        str(out_file),
    ]
    subprocess.run(cmd, check=True, cwd=cwd)
