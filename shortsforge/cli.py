"""
cli.py - the command-line "front door" (what you type in the terminal).

WHY it exists:
    Turns typed commands into calls to the pipeline. Three commands:
        make      video (file or link) -> shorts (speech videos: podcasts, vlogs, talks)
        valorant  gameplay video -> kill highlights -> shorts (v0.2.0)
        kills     only detect kills and list them (fast way to test settings)
        calibrate tune the kill detector on one frame of YOUR footage
        learn     measure reference viral shorts and tune the profile
        doctor    check that everything is installed correctly

HOW it works:
    Python's built-in argparse reads the words you type, checks them, and calls our functions.

HOW TO IMPROVE:
    - Replace/add a simple desktop window (Tkinter / PySide) or a local web page (Streamlit).
    - Add a `batch` command that processes a whole folder of videos.
    - Add a config file for your favourite options so you do not retype them.
"""

import argparse
import importlib.util
import shutil
import sys

from . import __version__


def _doctor() -> int:
    """Check required tools and print a friendly checklist."""
    problems = 0
    print(f"ShortsForge {__version__} - system check\n")
    for tool in ("ffmpeg", "ffprobe"):
        ok = shutil.which(tool) is not None
        print(f"[{'OK' if ok else 'MISSING'}] {tool}")
        problems += not ok
    for module, needed in (("numpy", True), ("faster_whisper", True),
                           ("yt_dlp", False), ("cv2", False)):
        ok = importlib.util.find_spec(module) is not None
        label = "OK" if ok else ("MISSING" if needed else "optional, not installed")
        print(f"[{label}] python package: {module}")
        problems += (not ok) and needed
    if problems:
        print("\nFix the MISSING items (see PROJECT.md, section 'Install').")
    else:
        print("\nAll good. Try:  python -m shortsforge make your_video.mp4")
    return 1 if problems else 0


def _floats(text: str, n: int, name: str) -> list:
    """Parse '0.1,0.2,0.3,0.4' into a list of n floats (used by --roi and --facecam)."""
    try:
        values = [float(x) for x in text.split(",")]
    except ValueError:
        raise SystemExit(f"{name}: use {n} numbers separated by commas, e.g. 0.6,0.03,1,0.45")
    if len(values) != n:
        raise SystemExit(f"{name}: need exactly {n} numbers")
    return values


def _game_overrides(args) -> dict:
    """Turn the command-line options into a dict that is merged over the game profile."""
    over = {}
    if getattr(args, "roi", None):
        over["roi"] = _floats(args.roi, 4, "--roi")
    for key, flag in (("pre_roll", "pre"), ("post_roll", "post"), ("chain_gap", "chain_gap")):
        value = getattr(args, flag, None)
        if value is not None:
            over[key] = value
    return over


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="shortsforge",
                                     description="Turn long videos into viral-style shorts.")
    sub = parser.add_subparsers(dest="command", required=True)

    make = sub.add_parser("make", help="create shorts from a video file or link")
    make.add_argument("source", help="path to a video file, or a YouTube/other link")
    make.add_argument("--count", type=int, default=5, help="how many shorts (default 5)")
    make.add_argument("--out", default="output", help="output folder (default: output)")
    make.add_argument("--model", default="small",
                      help="whisper model: tiny, base, small, medium, large-v3")
    make.add_argument("--reframe", default="auto", choices=["auto", "face", "center", "blur"])
    make.add_argument("--no-captions", action="store_true", help="do not burn captions")
    make.add_argument("--no-hook-title", action="store_true", help="no title at the top")
    make.add_argument("--llm", default=None, help="Ollama model name for re-rating, e.g. llama3.1:8b")
    make.add_argument("--profile", default=None, help="extra profile JSON to merge")
    make.add_argument("--language", default=None, help="speech language code, e.g. en, hi")
    make.add_argument("--transcript", default=None, help="use your own transcript JSON")
    make.add_argument("--dry-run", action="store_true", help="analyse only, do not render")

    learn = sub.add_parser("learn", help="learn the profile from reference shorts")
    learn.add_argument("folder", help="folder containing 3+ reference videos")
    learn.add_argument("--with-speech", action="store_true", help="also measure speaking speed")


    def game_options(p, full: bool):
        """Options shared by the game commands."""
        p.add_argument("source", help="gameplay video file (or link)")
        p.add_argument("--game", default="valorant", help="game profile name (default valorant)")
        p.add_argument("--out", default="output", help="output folder (default: output)")
        p.add_argument("--game-profile", default=None, help="your own JSON (e.g. from calibrate)")
        p.add_argument("--roi", default=None, help="kill-feed area as x0,y0,x1,y1 fractions")
        p.add_argument("--debug", action="store_true", help="save a picture of every detected kill")
        if full:
            p.add_argument("--count", type=int, default=5, help="how many shorts (default 5)")
            p.add_argument("--min-kills", type=int, default=1, help="only plays with N+ kills")
            p.add_argument("--layout", choices=["center", "blur", "stack"], default=None,
                           help="center = zoom on action, blur = full view, stack = gameplay + facecam")
            p.add_argument("--facecam", default=None, help="facecam area x,y,w,h fractions (for stack)")
            p.add_argument("--pre", type=float, default=None, help="seconds before the first kill")
            p.add_argument("--post", type=float, default=None, help="seconds after the last kill")
            p.add_argument("--chain-gap", dest="chain_gap", type=float, default=None,
                           help="max seconds between kills of ONE play (default 8)")
            p.add_argument("--no-popups", action="store_true", help="no DOUBLE KILL popups")
            p.add_argument("--no-hook-title", action="store_true", help="no title at the top")
            p.add_argument("--speech-captions", action="store_true",
                           help="also caption your voice (needs faster-whisper)")
            p.add_argument("--model", default="small", help="whisper model for --speech-captions")
            p.add_argument("--language", default=None, help="speech language code")
            p.add_argument("--transcript", default=None, help="use your own transcript JSON")
            p.add_argument("--dry-run", action="store_true", help="detect + plan only, no render")

    game = sub.add_parser("valorant", help="gameplay video -> kill highlight shorts")
    game_options(game, True)
    kills = sub.add_parser("kills", help="detect kills only and list them")
    game_options(kills, False)
    cal = sub.add_parser("calibrate", help="check/tune kill detection on one frame")
    cal.add_argument("source", help="gameplay video file")
    cal.add_argument("--time", type=float, required=True,
                     help="second just AFTER one of your kills (kill feed visible)")
    cal.add_argument("--game", default="valorant")
    cal.add_argument("--game-profile", default=None)
    cal.add_argument("--roi", default=None, help="kill-feed area x0,y0,x1,y1 fractions")
    cal.add_argument("--out", default="output/_calibrate")

    sub.add_parser("doctor", help="check the installation")

    args = parser.parse_args(argv)

    if args.command == "doctor":
        return _doctor()
    if args.command == "learn":
        from .learn_profile import learn as do_learn
        do_learn(args.folder, with_speech=args.with_speech)
        return 0

    if args.command == "calibrate":
        from .calibrate import calibrate
        calibrate(args.source, args.time, args.game, args.game_profile,
                  _floats(args.roi, 4, "--roi") if args.roi else None, args.out)
        return 0
    if args.command == "kills":
        from .pipeline import detect_only
        detect_only(args.source, args.game, args.out, args.game_profile,
                    _game_overrides(args), args.debug)
        return 0
    if args.command == "valorant":
        from .pipeline import run_game
        run_game(args.source, game=args.game, out_root=args.out, count=args.count,
                 min_kills=args.min_kills, layout=args.layout,
                 facecam=_floats(args.facecam, 4, "--facecam") if args.facecam else None,
                 with_popups=not args.no_popups, hook_title=not args.no_hook_title,
                 speech_captions=args.speech_captions, model=args.model, language=args.language,
                 transcript_file=args.transcript, game_profile_path=args.game_profile,
                 overrides=_game_overrides(args), dry_run=args.dry_run, debug=args.debug)
        return 0

    from .pipeline import run   # imported late so `doctor` works even if things are missing
    run(args.source, out_root=args.out, count=args.count, model=args.model,
        reframe_mode=args.reframe, with_captions=not args.no_captions,
        hook_title=not args.no_hook_title, llm_model=args.llm, profile_path=args.profile,
        language=args.language, dry_run=args.dry_run, transcript_file=args.transcript)
    return 0


if __name__ == "__main__":
    sys.exit(main())
