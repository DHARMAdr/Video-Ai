"""
fetch_assets.py - downloads the two big things the app carries inside it: ffmpeg + the speech model.

WHY it exists:
    The standalone app must work with NOTHING installed. So the build downloads ffmpeg.exe /
    ffprobe.exe and the Whisper speech model once, and puts them in packaging/assets/. The build
    script then copies them next to ShortsForge.exe (folders bin/ and models/).

HOW it works:
    - ffmpeg: a ready-made Windows build (with libx264 and subtitles support) from the
      BtbN/FFmpeg-Builds project on GitHub (a zip file). We take only ffmpeg.exe + ffprobe.exe.
    - model: the converted "faster-whisper" model from Hugging Face (Systran/faster-whisper-<size>).
    Use `--no-model` to skip the model (the app then downloads it on first use, ~460 MB for small).
    Use `--ffmpeg-zip path` if you already downloaded an ffmpeg zip yourself.

LICENSES: FFmpeg is GPL when built with libx264. Shipping it inside your app is allowed, but if
    you SHARE the app with others you must also make the ffmpeg source/licence available
    (link to https://ffmpeg.org and keep the licence files). Whisper models are MIT licensed.

HOW TO IMPROVE:
    - Pin exact versions + check SHA256 so builds are repeatable.
    - Offer a smaller LGPL ffmpeg build + hardware (NVENC) encoders.
"""

import argparse
import shutil
import sys
import urllib.request
import zipfile
from pathlib import Path

ASSETS = Path(__file__).resolve().parent / "assets"
FFMPEG_URL = ("https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/"
              "ffmpeg-master-latest-win64-gpl.zip")


def get_ffmpeg(local_zip=None) -> None:
    """Put ffmpeg.exe and ffprobe.exe into assets/bin."""
    bin_dir = ASSETS / "bin"
    if (bin_dir / "ffmpeg.exe").exists() and (bin_dir / "ffprobe.exe").exists():
        print("ffmpeg already present, skipping.")
        return
    bin_dir.mkdir(parents=True, exist_ok=True)
    archive = Path(local_zip) if local_zip else ASSETS / "ffmpeg.zip"
    if not local_zip:
        print(f"Downloading ffmpeg from {FFMPEG_URL} ...")
        urllib.request.urlretrieve(FFMPEG_URL, archive)
    with zipfile.ZipFile(archive) as bundle:
        for name in bundle.namelist():
            base = Path(name).name
            if base in ("ffmpeg.exe", "ffprobe.exe"):          # ignore everything else
                with bundle.open(name) as src, open(bin_dir / base, "wb") as dst:
                    shutil.copyfileobj(src, dst)
    if not local_zip:
        archive.unlink(missing_ok=True)
    print("ffmpeg ready:", sorted(p.name for p in bin_dir.iterdir()))


def get_model(size: str) -> None:
    """Download the speech model into assets/models/<size>."""
    target = ASSETS / "models" / size
    if (target / "model.bin").exists():
        print(f"Model '{size}' already present, skipping.")
        return
    from huggingface_hub import snapshot_download      # installed with faster-whisper
    print(f"Downloading speech model '{size}' (this is a few hundred MB) ...")
    snapshot_download(repo_id=f"Systran/faster-whisper-{size}", local_dir=str(target))
    print("model ready:", target)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="small", help="tiny, base, small, medium (default small)")
    parser.add_argument("--no-model", action="store_true", help="do not bundle a speech model")
    parser.add_argument("--ffmpeg-zip", default=None, help="use this ffmpeg zip instead of downloading")
    args = parser.parse_args()
    ASSETS.mkdir(parents=True, exist_ok=True)
    get_ffmpeg(args.ffmpeg_zip)
    if not args.no_model:
        get_model(args.model)
    return 0


if __name__ == "__main__":
    sys.exit(main())
