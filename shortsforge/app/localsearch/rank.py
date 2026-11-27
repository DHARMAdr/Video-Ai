"""
rank.py - mixes the result lists and finds the paragraphs that answer the question.

WHY: each service orders results differently and some results are junk. And a page is long,
    while the AI can only read a little.
HOW:
    1. Fusion: a link scores points for every list it appears in, more when near the top
       ("reciprocal rank fusion"). Links that several services agree on rise.
    2. BM25: the classic search formula. A word counts more when it is rare, and repeating
       it helps less and less. Used on titles/snippets, then on page paragraphs.
    3. Small bonuses and penalties: official or reference sites up, content farms down,
       at most two links from one website.
HOW TO IMPROVE: compare meanings with a small embedding model instead of only words.
"""

import math
import re
import urllib.parse
from collections import Counter

from .query import stem, words

K = 60                      # fusion constant: how fast points fade down a list
GOOD_SITES = ("wikipedia.org", "github.com", "stackoverflow.com", "python.org",
              "mozilla.org", "microsoft.com", "playvalorant.com", "pubg.com", "ffmpeg.org", "fandom.com")
WEAK_SITES = ("pinterest.", "quora.com", "facebook.com", "instagram.com", "tiktok.com",
              "merriam-webster.com", "dictionary.", "thesaurus.")        # word meanings
BAD_ENDINGS = (".pdf", ".zip", ".exe", ".msi", ".mp4", ".jpg", ".png", ".apk")
TRACKING = re.compile(r"^(utm_|fbclid|gclid|ref$|ref_|source$)")


def same_page(url: str) -> str:
    """One spelling for one page, so the same link from two services is joined."""
    parts = urllib.parse.urlsplit(url)
    host = (parts.hostname or "").lower()
    for prefix in ("www.", "m.", "amp."):
        if host.startswith(prefix):
            host = host[len(prefix):]
    query = [(k, v) for k, v in urllib.parse.parse_qsl(parts.query) if not TRACKING.match(k)]
    return host + parts.path.rstrip("/") + ("?" + urllib.parse.urlencode(sorted(query))
                                            if query else "")


def site(url: str) -> str:
    return ".".join((urllib.parse.urlsplit(url).hostname or "").lower().split(".")[-2:])


def tokens(text: str) -> list:
    return [stem(w) for w in words(text)]


def bm25(keywords: list, documents: list, k1: float = 1.4, b: float = 0.7) -> list:
    """One score per document (a document = a list of tokens)."""
    wanted = {stem(w) for w in keywords}
    if not documents or not wanted:
        return [0.0] * len(documents)
    average = sum(len(d) for d in documents) / len(documents) or 1.0
    in_how_many = Counter(w for d in documents for w in set(d) & wanted)
    scores = []
    for document in documents:
        counts, total = Counter(document), 0.0
        for word in wanted:
            seen = counts.get(word, 0)
            if seen:
                n = in_how_many[word]
                rarity = math.log(1 + (len(documents) - n + 0.5) / (n + 0.5))
                total += rarity * seen * (k1 + 1) / (
                    seen + k1 * (1 - b + b * len(document) / average))
        scores.append(total)
    return scores


def coverage(keywords: list, text_tokens: list) -> float:
    """How many of the question's words appear at all (0 to 1)."""
    wanted = {stem(w) for w in keywords}
    return len(wanted & set(text_tokens)) / len(wanted) if wanted else 0.0


def fuse(lists: list, keywords: list, limit: int = 8) -> list:
    """lists = [(weight, [items])] -> best items, each with a "score"."""
    merged = {}
    for weight, items in lists:
        for place, item in enumerate(items):
            key = same_page(item["url"])
            entry = merged.setdefault(key, {**item, "score": 0.0})
            entry["score"] += weight / (K + place)
            if len(item["text"]) > len(entry["text"]):
                entry["text"] = item["text"]
    entries = list(merged.values())
    if not entries:
        return []
    documents = [tokens(f"{e['title']} {e['title']} {e['text']} {e['url']}") for e in entries]
    word_scores = bm25(keywords, documents)
    top_word = max(word_scores) or 1.0
    top_fused = max(e["score"] for e in entries)
    for entry, document, word_score in zip(entries, documents, word_scores):
        score = (0.5 * entry["score"] / top_fused + 0.25 * word_score / top_word +
                 0.25 * coverage(keywords, document))
        score *= 0.4 + coverage(keywords, document)       # off-topic results sink
        host = urllib.parse.urlsplit(entry["url"]).hostname or ""
        if any(host == s or host.endswith("." + s) for s in GOOD_SITES):
            score *= 1.15
        if any(s in host for s in WEAK_SITES):
            score *= 0.7
        if urllib.parse.urlsplit(entry["url"]).path.lower().endswith(BAD_ENDINGS):
            score *= 0.5
        entry["score"] = round(score, 4)
    entries.sort(key=lambda e: -e["score"])
    chosen, per_site = [], Counter()
    for entry in entries:
        if per_site[site(entry["url"])] < 2:
            per_site[site(entry["url"])] += 1
            chosen.append(entry)
        if len(chosen) == limit:
            break
    return chosen


def passages(text: str, size: int = 420) -> list:
    """Cut page text into pieces of about `size` letters, at line or sentence ends."""
    pieces, current = [], ""
    for line in str(text).splitlines():
        for sentence in re.split(r"(?<=[.!?।])\s+", line.strip()):
            if not sentence:
                continue
            if current and len(current) + len(sentence) > size:
                pieces.append(current)
                current = ""
            current = f"{current} {sentence}".strip()[:size * 2]
    if current:
        pieces.append(current)
    return pieces


def best_passages(keywords: list, text: str, count: int = 3, intro: bool = False) -> list:
    """The paragraphs that best answer the question, in page order.

    intro=True also keeps the first real paragraph: reference pages state the basics there.
    """
    pieces = passages(text)
    documents = [tokens(p) for p in pieces]
    scores = bm25(keywords, documents)
    ranked = []
    for i, (piece, document, score) in enumerate(zip(pieces, documents, scores)):
        value = score * (0.5 + coverage(keywords, document))
        if re.search(r"\d", piece):
            value *= 1.1                  # facts often carry numbers and dates
        if len(piece) < 60:
            value *= 0.5                  # menus and headings
        if value > 0:
            ranked.append((value, i))
    chosen = {i for _, i in sorted(ranked, reverse=True)[:count]}
    if intro:
        chosen |= set(next(([i] for i, p in enumerate(pieces) if len(p) > 120), []))
    chosen = sorted(chosen)
    return [pieces[i] for i in chosen]
