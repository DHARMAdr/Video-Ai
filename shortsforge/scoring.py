"""
scoring.py - the "virality brain": gives every candidate clip a score from 0 to 100.

WHY it exists:
    Out of hundreds of possible clips we must find the ones most likely to hold attention.
    Short-form platforms reward: a strong first 3 seconds (hook), energy, fast pace,
    emotion, and a clip that feels complete.

HOW it works:
    Six sub-scores, each 0 to 1:
        hook         - does the first sentence grab attention? (question, number, hook phrase)
        energy       - is the audio loud and varied, not silent?
        pace         - words per second inside the ideal range?
        emotion      - emotional words and exclamations/questions
        completeness - starts cleanly, ends on a full sentence, near the ideal length
        visual       - scene cuts per 10 s inside the ideal range
    They are combined with the weights from viral_profile.json into one 0-100 number.
    This is HEURISTIC (rules of thumb), not a magic predictor. Nobody can guarantee virality.

HOW TO IMPROVE:
    - Train a small model on your own channel analytics (views / retention vs these sub-scores).
    - Replace the hook rules with an LLM judge (see llm.py, already supported via Ollama).
    - Add face / emotion / motion signals to the visual score.
"""

import re

# Words that make a clip start badly ("and then he said..." is missing its setup).
BAD_STARTS = ("and", "but", "so", "because", "or", "then", "which", "that", "also")


def _tokens(text: str) -> list:
    """Lowercase words only (letters, digits, apostrophes)."""
    return re.findall(r"[a-z0-9']+", text.lower())


def score_hook(first_sentence: str, profile: dict):
    """How attention-grabbing is the opening line? Returns (0-1, reasons)."""
    text, low = first_sentence.strip(), first_sentence.lower()
    points, reasons = 0.0, []
    if "?" in text:
        points += 0.30
        reasons.append("opens with a question")
    if any(re.search(p, low) for p in profile["hook_patterns"]):
        points += 0.35
        reasons.append("uses a proven hook phrase")
    if re.search(r"\d", text):
        points += 0.15
        reasons.append("contains a number")
    n = len(_tokens(text))
    if 0 < n <= 16:
        points += 0.10
        reasons.append("short, punchy opening")
    if re.search(r"\b(you|your|you're)\b", low):
        points += 0.10
        reasons.append("speaks directly to the viewer")
    return min(1.0, points), reasons


def score_pace(words: int, duration: float, profile: dict) -> float:
    """1.0 when words-per-second is inside the ideal range, fading to 0 outside it."""
    lo, hi = profile["ideal_words_per_second"]
    wps = words / max(duration, 0.1)
    if lo <= wps <= hi:
        return 1.0
    distance = (lo - wps) if wps < lo else (wps - hi)
    return max(0.0, 1.0 - distance / lo)


def score_emotion(text: str, profile: dict) -> float:
    """Emotion words + exclamation/question marks, scaled to 0-1."""
    toks = _tokens(text)
    if not toks:
        return 0.0
    emo = set(profile["emotion_words"])
    emo_count = sum(1 for t in toks if t in emo)
    marks = text.count("!") + text.count("?")
    sentences = max(1, len(re.findall(r"[.!?]", text)))
    return min(1.0, emo_count / len(toks) * 12 + marks / sentences * 0.4)


def score_completeness(cand: dict, profile: dict) -> float:
    """Clean start + finished ending + length close to ideal."""
    ends_ok = cand["text"].rstrip().endswith((".", "?", "!"))
    first = _tokens(cand["first_sentence"])[:1]
    clean_start = not (first and first[0] in BAD_STARTS)
    ideal = profile["ideal_seconds"]
    length_fit = 1 - min(1.0, abs(cand["duration"] - ideal) / ideal)
    return 0.4 * ends_ok + 0.3 * clean_start + 0.3 * length_fit


def score_visual(signals, cand: dict, profile: dict) -> float:
    """Scene cuts per 10 seconds, compared with the ideal range."""
    if signals is None:
        return 0.5   # unknown -> neutral
    lo, hi = profile["ideal_cuts_per_10s"]
    cuts = signals.cuts_per_10s(cand["start"], cand["end"])
    if lo <= cuts <= hi:
        return 1.0
    distance = (lo - cuts) if cuts < lo else (cuts - hi)
    return max(0.0, 1.0 - distance / max(lo, 1.0))


def score_candidate(cand: dict, signals, profile: dict) -> dict:
    """Compute every sub-score and the weighted total (0-100)."""
    hook, reasons = score_hook(cand["first_sentence"], profile)

    if signals is None:
        energy = 0.5
    else:
        level, dynamics, silence = signals.energy_stats(cand["start"], cand["end"])
        energy = (0.7 * level + 0.3 * dynamics) * (1 - 0.8 * silence)
        if level > 0.6:
            reasons.append("loud, energetic audio")

    parts = {
        "hook": hook,
        "energy": energy,
        "pace": score_pace(len(cand["words"]), cand["duration"], profile),
        "emotion": score_emotion(cand["text"], profile),
        "completeness": score_completeness(cand, profile),
        "visual": score_visual(signals, cand, profile),
    }
    weights = profile["weights"]
    total = sum(weights[k] * parts[k] for k in parts) / sum(weights.values()) * 100
    parts["total"] = round(total, 1)
    parts["reasons"] = reasons
    return parts
