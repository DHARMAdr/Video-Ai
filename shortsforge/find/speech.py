"""
speech.py - finds moments by what was SAID.

WHY it exists:
    "The part where I say clutch" is easy to find if the speech is written down first.

HOW it works:
    The transcript has a time for every word. We compare your phrase with every run of words of
    the same length. Small spelling differences are allowed, because speech recognition is not
    perfect ("clutch" / "cluch").

HOW TO IMPROVE:
    - Search by meaning (embeddings), so "money" also finds "salary".
"""

import re
from difflib import SequenceMatcher

from .moments import hit

CLOSE_ENOUGH = 0.80


def normalise(text: str) -> list:
    """Lower-case words without punctuation."""
    return re.findall(r"\w+", str(text).lower())


def similarity(a: list, b: list) -> float:
    return SequenceMatcher(None, " ".join(a), " ".join(b)).ratio()


def flat_words(transcript: dict) -> list:
    words = []
    for segment in transcript.get("segments", []):
        words.extend(segment.get("words") or [])
    return words


def search(transcript: dict, phrase: str) -> list:
    """Hits where the phrase (or something very close) is spoken."""
    wanted = normalise(phrase)
    if not wanted:
        return []
    words = [w for w in flat_words(transcript) if normalise(w["word"])]
    spoken = [normalise(w["word"])[0] for w in words]
    size = len(wanted)
    found, i = [], 0
    while i + size <= len(spoken):
        score = similarity(wanted, spoken[i:i + size])
        short_exact_only = size == 1 and len(wanted[0]) <= 3
        if score >= (1.0 if short_exact_only else CLOSE_ENOUGH):
            start, end = words[i]["start"], words[i + size - 1]["end"]
            said = " ".join(w["word"] for w in words[max(0, i - 4): i + size + 4])
            found.append(hit(start, score, "speech", f"said: \"{said.strip()}\"", end=end))
            i += size
        else:
            i += 1
    return found
