"""
paths.py - finds the files ShortsForge needs, whether it runs as normal Python code OR as the
packaged standalone app (the .exe).

WHY it exists:
    In the standalone app nothing is installed on the PC. ffmpeg and the speech model are
    shipped inside the app folder (next to ShortsForge.exe). The rest of the code just says
    "ffmpeg" or "small", so this file makes sure those names resolve to the bundled copies.

HOW it works:
    - is_frozen(): True when running as the packaged app (PyInstaller sets sys.frozen).
    - setup_environment(): puts <app>/bin first on PATH (so "ffmpeg" finds the bundled one),
      and on Windows hides the black console windows that would flash when ffmpeg starts.
    - bundled_model(): returns the folder of a speech model shipped in <app>/models/<size>/,
      otherwise just the model NAME (the library then downloads it on first use).
    - user_output_dir(): where finished shorts are saved (Documents/ShortsForge).

HOW TO IMPROVE:
    - Add a settings file so the user can change the output folder inside the app.
    - Support a shared model folder so several app versions do not duplicate 460 MB.
"""

import os
import sys
from pathlib import Path


def is_frozen() -> bool:
    """True when running as the packaged standalone app."""
    return bool(getattr(sys, "frozen", False))


def app_dir() -> Path:
    """Folder that holds the app: the .exe folder when packaged, the project folder otherwise."""
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def _roots() -> list:
    """Places to look for bundled files (the app folder, and PyInstaller's inner folder)."""
    roots = [app_dir()]
    inner = getattr(sys, "_MEIPASS", None)
    if inner:
        roots.append(Path(inner))
    return roots


def setup_environment() -> None:
    """Make the bundled ffmpeg visible and keep Windows from flashing console windows."""
    for root in _roots():
        bin_dir = root / "bin"
        if bin_dir.is_dir():
            os.environ["PATH"] = str(bin_dir) + os.pathsep + os.environ.get("PATH", "")

    if os.name == "nt":
        import subprocess
        original = subprocess.Popen.__init__

        def quiet_init(self, *args, **kwargs):
            # 0x08000000 = CREATE_NO_WINDOW: start ffmpeg without opening a black window
            kwargs["creationflags"] = kwargs.get("creationflags", 0) | 0x08000000
            original(self, *args, **kwargs)

        subprocess.Popen.__init__ = quiet_init


def bundled_model(size: str) -> str:
    """Folder of the shipped speech model, or the plain model name if none is shipped."""
    for root in _roots():
        folder = root / "models" / size
        if (folder / "model.bin").exists():
            return str(folder)
    return size


def has_bundled_model(size: str = "small") -> bool:
    """True if the speech model is inside the app (so no download is needed)."""
    return bundled_model(size) != size


def model_file(name: str):
    """A small model file shipped with the app (or downloaded by packaging/fetch_assets.py)."""
    for root in [*_roots(), app_dir() / "packaging" / "assets"]:
        if (root / "models" / name).is_file():
            return root / "models" / name
    override = os.environ.get("SHORTSFORGE_MODELS")           # used by the tests
    if override and (Path(override) / name).is_file():
        return Path(override) / name
    return None


def user_output_dir() -> Path:
    """Default folder for finished shorts."""
    docs = Path.home() / "Documents"
    return (docs if docs.is_dir() else Path.home()) / "ShortsForge"
