"""
moments.py - turns separate clues ("hits") into moments you can cut.

WHY it exists:
    The kill feed, your speech and the picture AI each report times. Clues close together are
    one moment, and two different clues agreeing makes us more sure.

HOW it works:
    - merge():   joins hits that are close in time. Confidence of different sources combines
                 like independent witnesses: 1 - (1-a)*(1-b).
    - require(): keeps only moments that have every kind of clue you asked for together.
    - bounds():  adds a few seconds before and after, and moves the edges to a nearby shot
                 change so the clip does not start in the middle of a flash.

HOW TO IMPROVE:
    - Learn from the clips you keep which clues deserve more weight.
"""

PRE = {"feed": 5.0, "speech": 3.0, "vision": 3.0, "picture": 2.0, "loud": 5.0}
POST = {"feed": 3.0, "speech": 4.0, "vision": 3.0, "picture": 3.0, "loud": 3.0}
MAX_CLIP = 59.0


def hit(t: float, score: float, source: str, why: str, end=None) -> dict:
    """One clue: at time t, `source` says something matched with confidence `score` (0-1)."""
    return {"t": round(float(t), 2), "end": round(float(t if end is None else end), 2),
            "score": max(0.0, min(0.99, float(score))), "source": source, "why": why}


def merge(hits: list, gap: float = 6.0) -> list:
    """Group hits into moments sorted by time."""
    groups = []
    for h in sorted(hits, key=lambda h: h["t"]):
        if groups and h["t"] - groups[-1]["last"] <= gap and h["end"] - groups[-1]["first"] <= MAX_CLIP:
            groups[-1]["hits"].append(h)
            groups[-1]["last"] = max(groups[-1]["last"], h["end"])
        else:
            groups.append({"first": h["t"], "last": h["end"], "hits": [h]})
    for g in groups:
        best = {}
        for h in g["hits"]:                      # strongest clue of each source
            best[h["source"]] = max(best.get(h["source"], 0.0), h["score"])
        doubt = 1.0
        for score in best.values():
            doubt *= 1.0 - score
        g["confidence"] = round(1.0 - doubt, 3)
        g["sources"] = sorted(best)
        g["why"] = list(dict.fromkeys(h["why"] for h in g["hits"]))[:4]
    return groups


def require(groups: list, needed) -> list:
    """Keep moments that contain every needed source."""
    needed = set(needed)
    return [g for g in groups if needed <= set(g["sources"])]


def bounds(group: dict, duration: float, length=None, cuts=()) -> tuple:
    """(start, end) of the clip for a moment."""
    if length:
        middle = (group["first"] + group["last"]) / 2
        start = max(0.0, middle - length * 0.6)
        return round(start, 2), round(min(duration, start + length), 2)
    pre = max(PRE.get(s, 3.0) for s in group["sources"])
    post = max(POST.get(s, 3.0) for s in group["sources"])
    start, end = max(0.0, group["first"] - pre), min(duration, group["last"] + post)
    earlier = [c for c in cuts if start - 1.5 <= c <= start + 1.5 and c < group["first"] - 0.5]
    later = [c for c in cuts if end - 1.5 <= c <= end + 1.5 and c > group["last"] + 1.0]
    start = earlier[-1] if earlier else start
    end = later[0] if later else end
    if end - start > MAX_CLIP:
        end = start + MAX_CLIP
    if end - start < 3.0:
        end = min(duration, start + 3.0)
    return round(start, 2), round(end, 2)


def choose(groups: list, limit: int, which=None) -> list:
    """The first/last moment, or the `limit` most confident ones in time order."""
    if not groups:
        return []
    if which == "first":
        return groups[:1]
    if which == "last":
        return groups[-1:]
    ranked = sorted(groups, key=lambda g: (-g["confidence"], -len(g["hits"]), g["first"]))[:limit]
    return sorted(ranked, key=lambda g: g["first"])
