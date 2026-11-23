# -*- mode: python ; coding: utf-8 -*-
"""
ShortsForge.spec - the recipe PyInstaller follows to pack the app into ONE folder.

WHY it exists:
    PyInstaller turns Python code into a program that runs WITHOUT Python installed. It finds
    most of what it needs by itself, but some libraries (speech recognition, video decoding)
    hide files it cannot see. `collect_all(...)` tells it to take everything from those libraries.

HOW it works:
    - Entry point: shortsforge_app.py (opens the window).
    - datas: our own non-code files (the web page, game profiles, viral profile).
    - collect_all: copies the libraries' hidden files (models of VAD, native .dll files, ...).
    - Result: dist/ShortsForge/ShortsForge.exe + a folder of libraries.
    - ffmpeg and the speech model are NOT packed here; the build script copies them next to the
      .exe afterwards (folders `bin/` and `models/`). This keeps the build fast and lets you swap
      the model without rebuilding.

HOW TO IMPROVE:
    - Add an icon:  icon="packaging/icon.ico"  in EXE(...).
    - Shrink the app by adding more names to `excludes`.
    - Add version info / code signing so Windows SmartScreen trusts the app more.
"""

import os
from PyInstaller.utils.hooks import collect_all

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))   # SPECPATH = the folder of this file

datas = [
    (os.path.join(ROOT, "shortsforge", "app", "static"), "shortsforge/app/static"),
    (os.path.join(ROOT, "shortsforge", "games"), "shortsforge/games"),
    (os.path.join(ROOT, "shortsforge", "viral_profile.json"), "shortsforge"),
]
binaries, hiddenimports = [], []

# Libraries that carry files PyInstaller cannot discover on its own.
for package in ("faster_whisper", "ctranslate2", "av", "onnxruntime", "tokenizers",
                "huggingface_hub", "cv2", "webview", "yt_dlp", "numpy"):
    try:
        pkg_datas, pkg_binaries, pkg_hidden = collect_all(package)
        datas += pkg_datas
        binaries += pkg_binaries
        hiddenimports += pkg_hidden
    except Exception as error:                      # a missing optional library is not fatal
        print(f"[spec] skipped {package}: {error}")

hiddenimports += ["shortsforge.cli", "shortsforge.pipeline", "shortsforge.calibrate",
                  "shortsforge.learn_profile", "shortsforge.llm"]

a = Analysis(
    [os.path.join(ROOT, "shortsforge_app.py")],
    pathex=[ROOT],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["tkinter", "matplotlib", "pandas", "scipy", "PyQt5", "PyQt6", "PySide2", "PySide6",
              "IPython", "notebook", "pytest"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="ShortsForge",
    console=False,            # no black console window (errors go to Documents/ShortsForge/app.log)
    upx=False,                # UPX makes some AV tools suspicious; size is not our main concern
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="ShortsForge")
