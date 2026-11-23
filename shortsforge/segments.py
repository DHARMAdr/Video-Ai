"""
segments.py - builds CANDIDATE clips and picks the best non-overlapping ones.

WHY it exists:
    A good short must start at the beginning of a thought and stop at the end of one. If we
    cut at random seconds, the clip starts or ends mid-sentence and feels broken. So we only
    cut on sentence boundaries.

HOW it works:
    1. to_sentences(): flatten all words, then split into sentences (at . ? ! , long pauses,
       or if a sentence runs more than 12 seconds).
    2. build_candidates(): for every start sentence, try ending on each later sentence. If the
       length is inside [min_seconds, max_seconds] it becomes a candidate.
    3. pick_top(): sort by score, then take the best ones that do not overlap in time.

HOW TO IMPROVE:
    - Allow candidates that jump over boring parts (stitching two good moments).
    - Add a "diversity" rule so the 5 shorts are about different topics, not 5 similar ones.
    - Use semantic embeddings (sentence-transformers) to detect topic changes.
"""

import re


def _words_from_segment(seg: dict) -> list:
    """Get word timings from a segment. If missing, spread the words evenly over the segment."""
    if seg.get("words"):
        return [dict(w) for w in seg["words"]]
    tokens = seg["text"].split()
    if not tokens:
        return []
    step = (seg["end"] - seg["start"]) / len(tokens)
    return [
        {"word": t, "start": seg["start"] + i * step, "end": seg["start"] + (i + 1) * step}
        for i, t in enumerate(tokens)
    ]


def to_sentences(transcript: dict, max_gap: float = 0.8, max_len: float = 12.0) -> list:
    """Split the transcript into sentences. Each has start, end, text, words."""
    words = []
    for seg in transcript["segments"]:
        words.extend(_words_from_segment(seg))

    sentences, current = [], []

    def flush():
        if current:
            text = re.sub(r"\s+", " ", " ".join(w["word"] for w in current)).strip()
            sentences.append({
                "start": current[0]["start"], "end": current[-1]["end"],
                "text": text, "words": list(current),
            })
            current.clear()

    for w in words:
        if current and w["start"] - current[-1]["end"] > max_gap:
            flush()                                   # long pause = new sentence
        if current and w["end"] - current[0]["start"] > max_len:
            flush()                                   # too long = force a split
        current.append(w)
        if w["word"].rstrip().endswith((".", "?", "!")):
            flush()                                   # punctuation = end of sentence
    flush()
    return sentences


def _make_candidate(group: list) -> dict:
    """Merge a run of sentences into one candidate clip."""
    all_words = [w for s in group for w in s["words"]]
    return {
        "start": group[0]["start"], "end": group[-1]["end"],
        "duration": group[-1]["end"] - group[0]["start"],
        "text": " ".join(s["text"] for s in group),
        "first_sentence": group[0]["text"],
        "words": all_words,
    }


def build_candidates(sentences: list, profile: dict) -> list:
    """Create every valid candidate clip (see module notes)."""
    min_s = profile["min_seconds"]
    max_s = profile["max_seconds"] - 1.0   # leave 1 s spare for the small padding added later
    candidates = []
    for i in range(len(sentences)):
        start = sentences[i]["start"]
        for j in range(i, len(sentences)):
            length = sentences[j]["end"] - start
            if length > max_s:
                break                       # longer ends only get longer, so stop
            if length >= min_s:
                candidates.append(_make_candidate(sentences[i:j + 1]))
    return candidates


def pick_top(scored: list, count: int) -> list:
    """Return the best `count` candidates that do not overlap each other."""
    chosen = []
    for cand in sorted(scored, key=lambda c: c["score"]["total"], reverse=True):
        overlaps = any(cand["start"] < c["end"] and cand["end"] > c["start"] for c in chosen)
        if not overlaps:
            chosen.append(cand)
        if len(chosen) == count:
            break
    return sorted(chosen, key=lambda c: c["start"])  # present them in video order
