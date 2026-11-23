"""
shortsforge_app.py - the "start button" of the standalone app.

WHY it exists:
    The packaging tool (PyInstaller) needs ONE script to start from. This file only calls the
    real launcher in shortsforge/app/desktop.py.
HOW it works:
    Double-click ShortsForge.exe  ->  runs this  ->  opens the window.
    From source:  python shortsforge_app.py   (add --browser to use your web browser)
HOW TO IMPROVE:
    Nothing needed here. Put features in the shortsforge/ package.
"""

from shortsforge.app.desktop import main

if __name__ == "__main__":
    raise SystemExit(main())
