"""
highlights.py - turns a plain list of kill times into "plays" (the clips worth posting).

WHY it exists:
    Kill times alone are not clips. Viewers love a double / triple / ace, so kills that happen
    close together must be grouped into ONE play, with a bit of lead-in (to build tension) and
    a bit of aftermath (to show the reaction). Then the plays must be ranked.

HOW it works:
    1. group_plays(): walk through the kills in time order. If the next kill is within
       `chain_gap` seconds of the previous one, it belongs to the same play.
    2. Each play gets start = first kill - pre_roll, end = last kill + post_roll. Too short?
       It is stretched to `min_clip_seconds`. Never longer than `max_clip_seconds`
       (a very long chain is split).
    3. score_play(): base points by kill count (1K=30 ... ACE=100) + a bonus for FAST chains
       + a bonus for loud audio (gunfights). Max 100.
    4. select_plays(): drop plays under `min_kills`, keep the best N that do not overlap.

HOW TO IMPROVE:
    - Detect clutches (low teammates alive) and round-winning kills for extra points.
    - Add a bonus for headshot sounds, weapon type (Operator flicks) or ability combos.
    - Learn the weights from your own analytics (which plays got the most views).
"""

LABELS = {1: "KILL", 2: "DOUBLE KILL", 3: "TRIPLE KILL", 4: "QUADRA KILL", 5: "ACE"}


def label_for(kill_count: int) -> str:
    """Friendly name for a play with this many kills."""
    return LABELS.get(kill_count, f"{kill_count} KILLS")


def _make_play(kills: list, gp: dict, duration: float) -> dict:
    """Build one play dict from its kill times (adds the lead-in / aftermath)."""
    start = max(0.0, kills[0] - gp["pre_roll"])
    end = min(duration, kills[-1] + gp["post_roll"])
    if end - start < gp["min_clip_seconds"]:                 # stretch very short plays
        end = min(duration, start + gp["min_clip_seconds"])
        start = max(0.0, end - gp["min_clip_seconds"])
    return {"kills": list(kills), "count": len(kills), "start": start, "end": end,
            "label": label_for(len(kills))}


def group_plays(kill_times: list, gp: dict, duration: float) -> list:
    """Group nearby kills into plays (see module notes)."""
    # A chain may not be so long that the clip would exceed the maximum clip length.
    max_chain = gp["max_clip_seconds"] - gp["pre_roll"] - gp["post_roll"]
    plays, current = [], []
    for t in sorted(kill_times):
        too_far = current and (t - current[-1] > gp["chain_gap"])
        too_long = current and (t - current[0] > max_chain)
        if too_far or too_long:
            plays.append(_make_play(current, gp, duration))
            current = []
        current.append(t)
    if current:
        plays.append(_make_play(current, gp, duration))
    return plays


def score_play(play: dict, signals, gp: dict) -> dict:
    """Give the play a 0-100 score and explain it. Adds play['score'] and returns the play."""
    n = play["count"]
    table = {int(k): v for k, v in gp["base_score"].items()}
    base = table.get(n, max(table.values()))
    reasons = [f"{n} kill(s) in one play"]

    speed = 0.0
    if n > 1:
        average_gap = (play["kills"][-1] - play["kills"][0]) / (n - 1)
        speed = max(0.0, min(1.0, (gp["chain_gap"] - average_gap) / gp["chain_gap"]))
        speed *= gp["speed_bonus_max"]
        if speed >= gp["speed_bonus_max"] * 0.6:
            reasons.append(f"fast chain ({average_gap:.1f}s between kills)")

    energy = 0.0
    if signals is not None:
        level, _, _ = signals.energy_stats(play["kills"][0] - 1.0, play["kills"][-1] + 1.0)
        energy = level * gp["energy_bonus_max"]
        if level > 0.6:
            reasons.append("loud, intense audio")

    play["score"] = {"total": round(min(100.0, base + speed + energy), 1),
                     "base": base, "speed": round(speed, 1), "energy": round(energy, 1),
                     "reasons": reasons}
    return play


def select_plays(plays: list, count: int, min_kills: int = 1) -> list:
    """Best `count` plays with at least `min_kills`, never overlapping, in video order."""
    pool = [p for p in plays if p["count"] >= min_kills]
    chosen = []
    for play in sorted(pool, key=lambda p: p["score"]["total"], reverse=True):
        if not any(play["start"] < c["end"] and play["end"] > c["start"] for c in chosen):
            chosen.append(play)
        if len(chosen) == count:
            break
    return sorted(chosen, key=lambda p: p["start"])


def hashtags_for(play: dict, game: str = "valorant") -> list:
    """Starter hashtags (you can edit them before posting)."""
    tags = [f"#{game}", f"#{game}clips", "#gaming", "#fps", "#shorts", "#reels"]
    if play["count"] >= 2:
        tags.insert(2, "#" + play["label"].lower().replace(" ", ""))
    return tags
