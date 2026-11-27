"""
topics.py - finds where the TOPIC changes in what is said, so clips begin and end with a thought.

WHY it exists:
    A clip that starts in the middle of one subject and ends in the middle of the next feels
    broken, even when both ends are full sentences.

HOW it works (the "TextTiling" method by Marti Hearst, 1997):
    1. Turn every sentence into numbers: how often each meaningful word appears.
    2. At every gap between sentences, compare the words just BEFORE with the words just AFTER.
    3. A deep dip in that similarity means the subject changed there.
    The idea of using it to find clips comes from ClipsAI (https://github.com/DHARMAdr/clipsai,
    MIT licence, (c) 2023 Clips AI, Inc. - see THIRD_PARTY_NOTICES.md). ClipsAI compares
    sentences with a large AI model (needs PyTorch, several GB). This file is our own small
    version that compares the words themselves, so the app stays small and fast.

HOW TO IMPROVE:
    - Compare meanings instead of words (sentence embeddings from a small local model).
    - Word lists for more languages than English.
"""

import math
import re

import numpy as np

STOPWORDS = set("""a about after again all also am an and any are as at be because been before being
but by can could did do does doing don down for from get go going got had has have having he her here
hers him his how i if in into is it its just know like me more most my no not now of off ok okay on
one only or other our out over really right said say see she so some such than that the their them
then there these they thing things think this those through to too um uh up us very was we well were
what when where which while who why will with would yeah yes you your""".split())


def _words(text: str) -> list:
    """Meaningful words only, with simple endings removed so "jumps" matches "jump"."""
    found = []
    for word in re.findall(r"[^\W\d_]{2,}", text.lower()):
        if word not in STOPWORDS:
            found.append(re.sub(r"(ing|ed|es|s)$", "", word) if len(word) > 4 else word)
    return found


def _vectors(sentences: list) -> np.ndarray:
    """One row per sentence, one column per word. Rare words count for more."""
    bags = [_words(s["text"]) for s in sentences]
    vocabulary = {w: i for i, w in enumerate(sorted({w for bag in bags for w in bag}))}
    table = np.zeros((len(bags), max(1, len(vocabulary))))
    for row, bag in enumerate(bags):
        for word in bag:
            table[row, vocabulary[word]] += 1
    used_in = (table > 0).sum(axis=0)
    return table * np.log(1 + len(bags) / np.maximum(1, used_in))


def boundaries(sentences: list, window: int = 6) -> dict:
    """{gap number: strength 0..1}. Gap i is between sentence i and sentence i+1."""
    count = len(sentences)
    if count < 8:                                    # too little speech to talk about topics
        return {}
    window = min(window, count // 3)
    table = _vectors(sentences)

    similar = []
    for gap in range(count - 1):
        left = table[max(0, gap - window + 1):gap + 1].sum(axis=0)
        right = table[gap + 1:gap + 1 + window].sum(axis=0)
        size = math.sqrt(float(left @ left) * float(right @ right))
        similar.append(float(left @ right) / size if size else 0.0)
    smooth = [sum(similar[max(0, i - 1):i + 2]) / len(similar[max(0, i - 1):i + 2])
              for i in range(len(similar))]

    depths = []
    for i, value in enumerate(smooth):               # how far below the hills on both sides
        left = right = value
        for j in range(i, -1, -1):
            if smooth[j] < left:
                break
            left = smooth[j]
        for j in range(i, len(smooth)):
            if smooth[j] < right:
                break
            right = smooth[j]
        depths.append((left - value) + (right - value))

    cutoff = float(np.mean(depths) + np.std(depths) * 0.5)
    deepest = max(depths) or 1.0
    return {i: round(d / deepest, 3) for i, d in enumerate(depths)
            if d > cutoff and d >= depths[max(0, i - 1)] and d >= depths[min(len(depths) - 1, i + 1)]}


def apply(candidates: list, sentences: list, weight: float = 6.0) -> int:
    """Raise or lower each candidate's total score. Returns how many topic changes were found.

    + starts right where a topic starts, + ends right where it ends, - swallows a change.
    """
    found = boundaries(sentences)
    if not found:
        return 0
    starts = {round(s["start"], 3): i for i, s in enumerate(sentences)}
    ends = {round(s["end"], 3): i for i, s in enumerate(sentences)}
    for cand in candidates:
        first, last = starts.get(round(cand["start"], 3)), ends.get(round(cand["end"], 3))
        if first is None or last is None:
            continue
        bonus = found.get(first - 1, 0) + found.get(last, 0)
        bonus -= sum(strength for gap, strength in found.items() if first <= gap < last)
        cand["score"]["topic"] = round(bonus * weight, 1)
        cand["score"]["total"] = round(cand["score"]["total"] + bonus * weight, 1)
    return len(found)
