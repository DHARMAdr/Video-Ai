"""
config.py - loads the "viral profile" (the rulebook that decides what a good short looks like).

WHY it exists:
    We do not hard-code the rules inside the scoring code. Keeping them in a JSON file means
    you can tune "what is viral" without touching Python. It also lets the `learn` command
    overwrite the numbers with values measured from reference viral videos you collect.

HOW it works:
    1. Loads viral_profile.json (the defaults that ship with the tool).
    2. If viral_profile.learned.json exists (made by `python -m shortsforge learn`), its values
       are merged on top.
    3. If you pass --profile my.json, that file is merged on top of both.
    "Merge" means: values in the later file replace the same keys in the earlier file.

HOW TO IMPROVE:
    - Add per-platform profiles (youtube_shorts.json, reels.json, tiktok.json).
    - Add per-niche profiles (gaming, podcast, education), each with their own hook phrases.
    - Validate the JSON (check that weights are numbers, ranges have two values).
"""

import json
from pathlib import Path

# Folder where this file lives. Used to find the JSON files next to it.
PACKAGE_DIR = Path(__file__).parent
DEFAULT_PROFILE_PATH = PACKAGE_DIR / "viral_profile.json"
LEARNED_PROFILE_PATH = PACKAGE_DIR / "viral_profile.learned.json"


def _merge(base: dict, extra: dict) -> dict:
    """Return `base` updated with `extra`. Nested dicts are merged key by key."""
    result = dict(base)  # copy so we never change the original by accident
    for key, value in extra.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _merge(result[key], value)  # go one level deeper
        else:
            result[key] = value  # simple value: just replace
    return result


def _read_json(path: Path) -> dict:
    """Read a JSON file and return it as a dict."""
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def load_profile(extra_path=None) -> dict:
    """Load the final profile (defaults + learned + optional user file)."""
    profile = _read_json(DEFAULT_PROFILE_PATH)
    if LEARNED_PROFILE_PATH.exists():
        profile = _merge(profile, _read_json(LEARNED_PROFILE_PATH))
    if extra_path:
        profile = _merge(profile, _read_json(Path(extra_path)))
    return profile


# ---------------------------------------------------------------------------
# Game profiles (added in v0.2.0): one JSON file per game inside the games/ folder.
# WHY: the kill-feed position/colour differs per game, so each game gets its own settings.
# HOW: load games/<name>.json, merge an optional user file, then merge CLI overrides.
# HOW TO IMPROVE: add games/apex.json, games/cs2.json ... (the detector code is generic).
# ---------------------------------------------------------------------------
GAMES_DIR = PACKAGE_DIR / "games"


def load_game_profile(name: str = "valorant", extra_path=None, overrides=None) -> dict:
    """Load a game profile (+ optional user JSON + optional dict of overrides)."""
    path = GAMES_DIR / f"{name}.json"
    if not path.exists():
        known = ", ".join(sorted(p.stem for p in GAMES_DIR.glob("*.json")))
        raise FileNotFoundError(f"Unknown game '{name}'. Available: {known}")
    profile = _read_json(path)
    if extra_path:
        profile = _merge(profile, _read_json(Path(extra_path)))
    if overrides:
        profile = _merge(profile, overrides)
    return profile
