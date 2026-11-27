"""
feed.py - reads the kill feed: WHEN a kill happened, WHO did it and WHO died.

WHY it exists:
    "Find my kill on Jett" needs two facts together: it is MY kill, and the victim is Jett.

HOW it works:
    - My kills come from the same detector the automatic shorts use (your taught name, a
      taught colour, or the built-in rule).
    - A character or weapon is found by the example picture you taught (pictures.py).
    - A feed line reads   [killer icon] killer  weapon  victim [victim icon]
      and ends near the right edge of the screen. So an icon close to the right edge belongs to
      the VICTIM, an icon further left belongs to the KILLER, a middle one is the weapon.
    - Lines stay on screen for several seconds. We follow each line while it moves, and count
      it once, at the moment it first appears.

HOW TO IMPROVE:
    - Read player names as text (OCR) to also search by a friend's name.
"""

from .. import killfeed, namefeed, teach
from ..config import load_game_profile
from . import pictures

VICTIM_ZONE = 120          # pixels (at 1080p) from the right edge that belong to the victim
SCAN_FPS = 4
GONE_AFTER = 1.0           # seconds a line may be missed before we treat it as a new one
SAME_LINE_PX = 18


def my_kill_times(root, video, info: dict, work, log=print, game: str = "valorant") -> list:
    """Times of your own kills, using whatever you taught the app."""
    gp = teach.apply(root, load_game_profile(game), game)
    return killfeed.detect(video, info, gp, work, log=log)


def side_of(x: float, width: float, geometry: dict) -> str:
    """'victim' or 'killer', from where the icon sits."""
    right_gap = geometry["frame_w"] - (geometry["x0"] + x + width)
    return "victim" if right_gap < VICTIM_ZONE else "killer"


class Tracker:
    """Follows feed lines from picture to picture, so each line is counted once."""

    def __init__(self):
        self.live = []                     # [x, y, last_seen_time, event]
        self.events = []

    def see(self, t: float, x: float, y: float, event: dict) -> None:
        for line in self.live:
            # A line moves up or down when others appear, so allow some vertical movement.
            if abs(line[0] - x) <= SAME_LINE_PX and abs(line[1] - y) <= SAME_LINE_PX * 3 \
                    and t - line[2] <= GONE_AFTER and line[3]["name"] == event["name"] \
                    and line[3]["side"] == event["side"] and line[2] < t:
                line[0], line[1], line[2] = x, y, t
                line[3]["seen"] += 1
                line[3]["score"] = max(line[3]["score"], event["score"])
                return
        event = {**event, "t": round(t, 2), "seen": 1, "y": y}
        self.live.append([x, y, t, event])
        self.events.append(event)

    def result(self, min_seen: int = 2) -> list:
        """Only lines seen in at least two pictures (one-picture matches are usually mistakes)."""
        return [e for e in self.events if e["seen"] >= min_seen]


def scan_icons(root, video, info: dict, names: list, start: float, end: float, log=print,
               game: str = "valorant") -> list:
    """Every feed line showing one of the named pictures:
    [{'t', 'name', 'side': 'killer'|'victim', 'score'}]."""
    wanted = {n.lower() for n in names}
    items = [p for p in pictures.load_all(root) if p["name"].lower() in wanted and p["kind"] == "feed"]
    if not items:
        return []
    gp = teach.apply(root, load_game_profile(game), game)
    roi = gp["roi"]
    geometry = namefeed.ref_geometry(info, roi)
    templates = {}
    for item in items:
        templates.setdefault(item["name"], []).extend(
            pictures.variants(pictures.load_image(root, item), mirrored=True))
    log("Reading the kill feed for " + ", ".join(sorted(templates)) + " ...")
    tracker = Tracker()
    frames = namefeed.scan(video, info, roi, SCAN_FPS, start=start, duration=max(0.5, end - start))
    for index, frame in enumerate(frames):
        t = start + index / SCAN_FPS
        for name, versions in templates.items():
            for x, y, w, h, score in pictures.matches(frame, versions, pictures.THRESHOLDS["feed"]):
                tracker.see(t, x, y, {"name": name, "side": side_of(x, w, geometry), "score": score})
    return tracker.result()


def near(times: list, t: float, window: float = 1.5):
    """The time in `times` closest to t within the window, or None."""
    close = [x for x in times if abs(x - t) <= window]
    return min(close, key=lambda x: abs(x - t)) if close else None


def match_relation(plan: dict, events: list, mine: list) -> list:
    """Combine icon events with the plan. Returns [(time, score, why)].

    events: from scan_icons. mine: times of your kills.
    """
    out = []
    killer, victim = plan["killer"], plan["victim"]
    if victim and victim != "me":
        for e in events:
            if e["name"].lower() != victim.lower() or e["side"] != "victim":
                continue
            if killer == "me":
                if near(mine, e["t"]) is None:
                    continue
                out.append((e["t"], e["score"], f"your kill on {e['name']}"))
            elif killer:
                partner = [k for k in events if k["name"].lower() == killer.lower()
                           and k["side"] == "killer" and abs(k["t"] - e["t"]) <= 0.6
                           and abs(k["y"] - e["y"]) <= SAME_LINE_PX * 2]
                if partner:
                    out.append((e["t"], min(e["score"], partner[0]["score"]),
                                f"{partner[0]['name']} killed {e['name']}"))
            else:
                out.append((e["t"], e["score"], f"{e['name']} was killed"))
    elif killer and killer != "me":
        for e in events:
            if e["name"].lower() == killer.lower() and e["side"] == "killer":
                why = f"{e['name']} got a kill" + (" (check that it was you who died)" if victim == "me" else "")
                out.append((e["t"], e["score"], why))
    return sorted(out)


def group_multi(times: list, need: int, gap: float = 8.0) -> list:
    """Chains of kills close together: [(first, last, count)] with at least `need` kills."""
    chains = []
    for t in sorted(times):
        if chains and t - chains[-1][1] <= gap:
            chains[-1][1] = t
            chains[-1][2] += 1
        else:
            chains.append([t, t, 1])
    return [tuple(c) for c in chains if c[2] >= need]
