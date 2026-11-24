"""
retrieval.py - finds the best-matching sentences for a question (search that understands importance).

WHY it exists:
    "Where did I talk about pricing?" needs a smart search. Counting matching words is weak: it
    treats "the" like "pricing". This file uses BM25, the classic ranking formula used by search
    engines. Rare words count more than common words, and short exact matches beat long vague ones.
    It needs no AI model, no download, and is very fast.

HOW it works:
    1. tokens(): lowercase the text, split into words, drop filler words ("the", "and"...),
       and trim simple endings so "prices" matches "price".
    2. rank(): score every sentence against the question with BM25 and return the best ones.

HOW TO IMPROVE:
    - Add synonyms ("cost" ~ "price") or use a small embedding model for meaning-based search.
    - Remember the index on disk so very long videos are searched instantly.
"""

import math
import re

STOP = set("""a an the and or but if so of to in on at for from with by as is are was were be been being it its
this that these those i you he she we they me my your our their them his her do does did done have has had
not no yes can could should would will just about into over than then there here what which who whom when
where why how all any some more most very also like um uh yeah okay ok really""".split())


def _stem(word: str) -> str:
    """Very light stemming so related forms match: prices/pricing/price -> pric, talking/talked -> talk."""
    if word.endswith(("ches", "shes", "sses", "xes", "zes")):
        word = word[:-2]
    else:
        for ending in ("ing", "ed", "s"):
            if len(word) > len(ending) + 3 and word.endswith(ending) and not word.endswith("ss"):
                word = word[: -len(ending)]
                break
    if len(word) > 4 and word.endswith("e"):
        word = word[:-1]
    return word


def tokens(text: str, keep_stop: bool = False) -> list:
    """Words of a text, ready for matching."""
    words = re.findall(r"[a-z0-9']+", str(text).lower())
    if not keep_stop:
        filtered = [w for w in words if w not in STOP and len(w) > 1]
        words = filtered or [w for w in words if len(w) > 1]    # a query made only of filler words
    return [_stem(w) for w in words]


def rank(query: str, docs: list, limit: int = 8) -> list:
    """Best matches for the query. Returns [(score, index_in_docs), ...], best first."""
    q = set(tokens(query))
    if not q or not docs:
        return []
    doc_tokens = [tokens(d) for d in docs]
    n = len(docs)
    avg = (sum(len(t) for t in doc_tokens) / n) or 1.0
    df = {w: sum(1 for t in doc_tokens if w in t) for w in q}
    results = []
    for i, toks in enumerate(doc_tokens):
        if not toks:
            continue
        score = 0.0
        for w in q:
            tf = toks.count(w)
            if not tf:
                continue
            idf = math.log(1 + (n - df[w] + 0.5) / (df[w] + 0.5))
            score += idf * (tf * 2.2) / (tf + 1.2 * (0.25 + 0.75 * len(toks) / avg))
        if score > 0:
            results.append((score, i))
    results.sort(key=lambda r: -r[0])
    return results[:limit]
