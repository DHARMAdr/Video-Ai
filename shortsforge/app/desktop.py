"""
desktop.py - starts the app: server first, then the window.

WHY it exists:
    This is what runs when you double-click ShortsForge.exe.

HOW it works:
    1. paths.setup_environment() makes the bundled ffmpeg findable.
    2. The local server starts on a free port (see server.py).
    3. A native window (pywebview, which uses the Edge WebView2 that Windows already has) opens
       the page. If pywebview is missing, your normal browser opens instead; it works the same.
    4. `--selftest` (used by the automatic build) starts everything without a window, checks
       that all parts are inside the package, writes selftest.txt and exits.

NOTE: a packaged "windowed" app has no console, so print() output would be lost. We send it
      to a log file (Documents/ShortsForge/app.log) so errors can still be found.

HOW TO IMPROVE:
    - Add a tray icon and "open output folder" menu item.
    - Add an auto-update check that downloads a newer version from your GitHub releases.
    - Remember window size and last used settings.
"""

import argparse
import json
import multiprocessing
import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser

from .. import __version__, paths
from . import localai, server


def _redirect_streams(log_path) -> None:
    """In the windowed app stdout/stderr are None; give them a log file so nothing crashes."""
    if sys.stdout is None or sys.stderr is None:
        handle = open(log_path, "a", encoding="utf-8", buffering=1)
        if sys.stdout is None:
            sys.stdout = handle
        if sys.stderr is None:
            sys.stderr = handle


def _selftest(state, url: str) -> int:
    """Check that everything needed is inside this build. Returns 0 when all is fine."""
    lines, failed = [], False

    def check(name, ok, detail="", required=True):
        nonlocal failed
        lines.append(f"[{'OK' if ok else ('FAIL' if required else 'warn')}] {name} {detail}".rstrip())
        if required and not ok:
            failed = True

    check("version", True, __version__)
    for module, required in (("numpy", True), ("faster_whisper", True), ("yt_dlp", True),
                             ("cv2", False), ("webview", False)):
        try:
            __import__(module)
            check(f"import {module}", True, required=required)
        except Exception as exc:                                   # noqa: BLE001
            check(f"import {module}", False, f"({exc})", required=required)

    ffmpeg = shutil.which("ffmpeg")
    check("ffmpeg found", ffmpeg is not None, ffmpeg or "")
    if ffmpeg:
        try:
            out = subprocess.run([ffmpeg, "-version"], capture_output=True, text=True, timeout=30)
            check("ffmpeg runs", out.returncode == 0, out.stdout.splitlines()[0] if out.stdout else "")
            filters = subprocess.run([ffmpeg, "-hide_banner", "-filters"], capture_output=True,
                                     text=True, timeout=30).stdout
            check("ffmpeg has subtitles filter", " subtitles " in filters)
            encoders = subprocess.run([ffmpeg, "-hide_banner", "-encoders"], capture_output=True,
                                      text=True, timeout=30).stdout
            check("ffmpeg has libx264", "libx264" in encoders)
        except Exception as exc:                                   # noqa: BLE001
            check("ffmpeg runs", False, str(exc))
    engine = localai.find_engine()
    packaged = paths.is_frozen()                 # the engine is only required in the built app
    check("AI engine found", engine is not None, engine or "", required=packaged)
    if engine:
        try:
            out = subprocess.run([engine, "--version"], capture_output=True, text=True, timeout=60)
            text = (out.stderr or out.stdout).strip().splitlines()
            check("AI engine runs", out.returncode == 0, text[0] if text else f"code {out.returncode}",
                  required=packaged)
        except Exception as exc:                                   # noqa: BLE001
            check("AI engine runs", False, str(exc), required=packaged)
    check("speech model bundled", paths.has_bundled_model("small"),
          "(it will download on first use if not bundled)", required=False)

    try:
        request = urllib.request.Request(url.replace("/?t=", "/api/info?t="))
        info = json.loads(urllib.request.urlopen(request, timeout=10).read())
        check("local server answers", info.get("version") == __version__)
        page = urllib.request.urlopen(urllib.request.Request(url), timeout=10).read()
        check("window page is packaged", b"ShortsForge" in page)
    except Exception as exc:                                       # noqa: BLE001
        check("local server answers", False, str(exc))

    try:
        from .. import config
        config.load_game_profile("valorant")
        config.load_profile()
        check("profiles are packaged", True)
    except Exception as exc:                                       # noqa: BLE001
        check("profiles are packaged", False, str(exc))

    (state.out_dir / "selftest.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    return 1 if failed else 0


def main(argv=None) -> int:
    multiprocessing.freeze_support()          # needed by some packaged libraries
    paths.setup_environment()

    parser = argparse.ArgumentParser(prog="ShortsForge")
    parser.add_argument("--selftest", action="store_true", help="check the build and exit")
    parser.add_argument("--browser", action="store_true", help="use the web browser, not a window")
    parser.add_argument("--no-open", action="store_true",
                        help="only start the server and print its address (for tests / servers)")
    parser.add_argument("--out", default=None, help="folder for finished shorts")
    args = parser.parse_args(argv)

    out_dir = paths.user_output_dir() if not args.out else args.out
    state = server.AppState(out_dir)
    _redirect_streams(state.out_dir / "app.log")

    httpd = server.make_server(state)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{state.port}/?t={state.token}"

    if args.selftest:
        code = _selftest(state, url)
        httpd.shutdown()
        return code

    window = None
    if not args.browser and not args.no_open:
        try:
            import webview
            window = webview.create_window("ShortsForge", url, width=1280, height=840,
                                           min_size=(980, 640))

            def pick(kind):
                """Native 'open file' dialog (called by the page through the server)."""
                dialog = getattr(getattr(webview, "FileDialog", None), "OPEN", None) \
                    or webview.OPEN_DIALOG
                chosen = window.create_file_dialog(
                    dialog, allow_multiple=False,
                    file_types=("Video files (*.mp4;*.mov;*.mkv;*.webm;*.m4v;*.avi)",
                                "All files (*.*)"))
                return chosen[0] if chosen else None
            state.pick_file = pick
        except Exception:                                          # noqa: BLE001
            window = None                                          # fall back to the browser

    if window is not None:
        import webview
        webview.start()                       # blocks until the window is closed
    else:
        if not args.no_open:
            try:
                webbrowser.open(url)
            except Exception:                                      # noqa: BLE001
                pass
        print(f"ShortsForge is running. Open this address in a browser if it did not open:\n{url}",
              flush=True)
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass
    state.local_ai.stop()                     # close the AI engine with the app
    httpd.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
