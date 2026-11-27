"""
query.py - turns a sentence such as "top 3 clips where I kill Jett in the last 10 minutes"
into a clear, checkable search plan.

WHY it exists:
    A search must be predictable. These rules never "guess creatively": whatever they
    understood is shown to you in plain words (see explain), so you can correct it.

HOW it works:
    1. Cut out the parts about time ("first 10 minutes"), amount ("top 3") and clip length.
    2. Look for words you want SPOKEN ("where I say ...").
    3. Look for kill / death words and character names, and work out who killed whom.
    4. Anything else is a free description, which the picture AI looks for.

HOW TO IMPROVE:
    - Add words in your own language to the word lists.
    - Add new characters in games/valorant_agents.json (no code change needed).
"""

import json
import re
from pathlib import Path

AGENTS_FILE = Path(__file__).resolve().parent.parent / "games" / "valorant_agents.json"

ME = ("i", "me", "my", "mine", "myself")
MULTI_WORDS = {"ace": 5, "quadra": 4, "quad": 4, "4k": 4, "5k": 5, "triple": 3, "3k": 3,
               "double": 2, "2k": 2, "multi": 2, "multikill": 2}
NUMBER_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
                "eight": 8, "nine": 9, "ten": 10}
# Words that describe the request itself, not the scene we look for.
FILLER = re.compile(
    r"\b(please|can you|could you|find|search|locate|show|give|get|make|cut|crop|extract|me|a|an|"
    r"the|all|every|any|of|from|in|my|this|that|video|videos|clip|clips|short|shorts|scene|scenes|"
    r"moment|moments|part|parts|where|when|there|is|are|and|it|for|i want|want|to|see)\b")


def load_agents() -> dict:
    """{'Jett': ['jett'], 'KAY/O': ['kayo', 'kay/o'], ...}. Empty if the file is damaged."""
    try:
        data = json.loads(AGENTS_FILE.read_text(encoding="utf-8"))
        return {name: [a.lower() for a in aliases] for name, aliases in data["agents"].items()}
    except (OSError, ValueError, KeyError):
        return {}


def to_seconds(text: str, unit: str = "") -> float:
    """'12:30' -> 750, '1:02:00' -> 3720, ('10', 'minutes') -> 600."""
    if ":" in text:
        total = 0.0
        for part in text.split(":"):
            total = total * 60 + float(part)
        return total
    value = float(NUMBER_WORDS.get(text, text))
    if unit.startswith("h"):
        return value * 3600
    if unit.startswith("m"):
        return value * 60
    return value


_AMOUNT = r"(\d+(?::\d\d){0,2}|one|two|three|four|five|six|seven|eight|nine|ten)"
_UNIT = r"(seconds?|secs?|s|minutes?|mins?|m|hours?|h)?"


def _take(pattern: str, text: str):
    """Find a pattern, remove it from the text. Returns (match or None, remaining text)."""
    match = re.search(pattern, text)
    if not match:
        return None, text
    return match, (text[:match.start()] + " " + text[match.end():])


def parse_time_range(text: str):
    """Returns (range dict, text without the time words).
    range: {'from': s or None, 'to': s or None, 'last': s or None}"""
    span = {"from": None, "to": None, "last": None}
    m, text = _take(rf"\bbetween {_AMOUNT}\s*{_UNIT}\s+and\s+{_AMOUNT}\s*{_UNIT}\b", text)
    if m:
        unit_b = m.group(4) or ""
        span["from"] = to_seconds(m.group(1), m.group(2) or unit_b)
        span["to"] = to_seconds(m.group(3), unit_b)
    m, text = _take(rf"\b(?:in the |the )?first {_AMOUNT}\s*(seconds?|secs?|minutes?|mins?|hours?)\b", text)
    if m:
        span["to"] = to_seconds(m.group(1), m.group(2))
    m, text = _take(rf"\b(?:in the |the )?last {_AMOUNT}\s*(seconds?|secs?|minutes?|mins?|hours?)\b", text)
    if m:
        span["last"] = to_seconds(m.group(1), m.group(2))
    m, text = _take(rf"\bafter {_AMOUNT}\s*{_UNIT}(?=\s|$)", text)
    if m:
        span["from"] = to_seconds(m.group(1), m.group(2) or "")
    m, text = _take(rf"\bbefore {_AMOUNT}\s*{_UNIT}(?=\s|$)", text)
    if m:
        span["to"] = to_seconds(m.group(1), m.group(2) or "")
    return span, text


def parse_length(text: str):
    """'20 second clips' or '15 seconds long' -> (seconds, remaining text)."""
    m, text = _take(r"\b(\d{1,3})[\s-]*(?:seconds?|secs?|s)[\s-]*(?:long|clips?|shorts?|each)\b", text)
    return (min(180, max(3, int(m.group(1)))) if m else None), text


def parse_amount(text: str):
    """'top 3', '5 clips', 'first kill', 'last kill' -> (limit, which, remaining text)."""
    limit, which = None, None
    m, text = _take(rf"\b(?:top|best) {_AMOUNT}\b", text)
    if m:
        limit = int(to_seconds(m.group(1)))
    if limit is None:
        m, text = _take(rf"\b{_AMOUNT} (?=(?:best )?(?:clips?|shorts?|scenes?|moments?)\b)", text)
        if m:
            limit = int(to_seconds(m.group(1)))
    m, text = _take(r"\b(?:the |my )?(first|last) (?=(?:time|kill|death|scene|moment|round)\b)", text)
    if m:
        which = m.group(1)
    return limit, which, text


def parse_speech(text: str):
    """Words that must be SPOKEN. Returns (phrase or '', remaining text)."""
    m, rest = _take(r"[\"“']([^\"”']{2,80})[\"”']", text)
    if m:
        return m.group(1).strip(), rest
    m, rest = _take(r"\b(?:say|says|saying|said|mention|mentions|mentioned|talk about|talks about|"
                    r"talking about|shout|shouts|shouted)\s+(.{2,80})$", text)
    if m:
        return m.group(1).strip(" .?!"), rest
    return "", text


def find_agents(text: str, agents: dict) -> list:
    """Character names in the sentence, in order: [(name, start, end), ...]."""
    found = []
    for name, aliases in agents.items():
        for alias in aliases:
            for m in re.finditer(rf"(?<![\w/]){re.escape(alias)}(?:'s|s)?(?![\w/])", text):
                found.append((name, m.start(), m.end()))
    found.sort(key=lambda f: (f[1], -(f[2] - f[1])))
    clean, last_end = [], -1
    for item in found:                       # drop overlapping matches
        if item[1] >= last_end:
            clean.append(item)
            last_end = item[2]
    return clean


def who_did_what(text: str, agents: dict) -> dict:
    """Work out kill relations. Returns {'killer', 'victim', 'note'} (names, 'me' or None)."""
    result = {"killer": None, "victim": None, "note": ""}
    found = find_agents(text, agents)
    if not found:
        return result
    for name, start, end in found:
        before, after = text[:start], text[end:]
        # "Jett kills me", "killed by Jett"
        if re.match(r"\s*(?:kill|kills|killed|eliminates?|eliminated)\s+(?:me|us)\b", after) or \
           re.search(r"\b(?:killed|eliminated|die[ds]?|death)\s+(?:by|to|from)\s+(?:an?\s+|the\s+)?$", before):
            result["killer"], result["victim"] = name, "me"
        # "with Jett", "as Jett", "playing Jett"
        elif re.search(r"\b(?:with|as|using|playing|playing as|on my)\s+$", before):
            result["killer"] = name
        # "kill Jett", "kills on Jett", "kill of a Jett", "against Jett"
        elif re.search(r"\b(?:kill|kills|killed|killing|eliminate[ds]?|frag(?:ged|s)?)\s+"
                       r"(?:on\s+|of\s+|against\s+)?(?:an?\s+|the\s+|enemy\s+)?$", before) or \
             re.search(r"\b(?:against|versus|vs)\s+(?:an?\s+|the\s+)?$", before):
            result["victim"] = name
            if re.search(r"\b(?:kill|kills)\s+of\s+(?:an?\s+|the\s+)?$", before):
                result["note"] = f"I read 'kill of {name}' as {name} getting killed."
        # "Jett kills", "Jett's kill", "Jett getting a kill"
        elif re.match(r"(?:\s+(?:is\s+)?(?:getting|gets|got|doing|does))?(?:\s+an?)?\s*"
                      r"(?:kill|kills|killing|ace|clutch)\b", after):
            result["killer"] = name
        elif result["victim"] is None:
            result["victim"] = name
            result["note"] = f"I assumed you mean kills where {name} gets killed."
    return result


def parse(sentence: str, picture_names=(), agents=None) -> dict:
    """The whole search plan for one sentence."""
    agents = load_agents() if agents is None else agents
    original = " ".join(str(sentence or "").split())[:300]
    if not original:
        raise ValueError("Say what to look for.")
    text = original.lower()
    span, text = parse_time_range(text)
    length, text = parse_length(text)
    limit, which, text = parse_amount(text)
    said, text = parse_speech(text)

    plan = {"text": original, "range": span, "length": length, "limit": limit, "which": which,
            "said": said, "kill": False, "death": False, "multi": 0, "killer": None,
            "victim": None, "mine": False, "loud": False, "pictures": [], "description": "",
            "notes": []}

    for word, count in MULTI_WORDS.items():
        if re.search(rf"\b{word}(?:[\s-]*kills?)?\b", text):
            plan["multi"] = max(plan["multi"], count)
    plan["kill"] = bool(plan["multi"]) or bool(re.search(
        r"\b(kill|kills|killed|killing|frag|frags|eliminat\w+|headshots?)\b", text))
    plan["death"] = bool(re.search(r"\b(die|died|dies|dying|death|deaths)\b|\b(?:kills?|killed) me\b|"
                                   r"\b(?:i|we) (?:get|got|am|was) killed\b|\bkilled by\b", text))
    relation = who_did_what(text, agents)
    plan["killer"], plan["victim"] = relation["killer"], relation["victim"]
    if relation["note"]:
        plan["notes"].append(relation["note"])
    if plan["death"]:
        plan["victim"] = "me"
        if not re.search(r"\bi (?:kill|killed)\b", text):
            plan["kill"] = False
    elif plan["kill"]:
        words = re.findall(r"[a-z]+", text)
        plan["mine"] = any(w in ME for w in words) or plan["killer"] is None
        if plan["mine"] and plan["killer"] is None:
            plan["killer"] = "me"
    if re.search(r"\bhead[\s-]?shots?\b", text):
        plan["notes"].append("The app cannot tell headshots apart unless you teach it the headshot "
                             "icon as a picture named 'headshot'.")
    plan["loud"] = bool(re.search(r"\b(loud|loudest|screams?|screaming|shouting|hype)\b", text))

    lowered = {str(n).lower(): n for n in picture_names}
    for low, name in lowered.items():
        if re.search(rf"(?<!\w){re.escape(low)}(?:'s|s)?(?!\w)", text):
            plan["pictures"].append(name)

    # A character's kill-feed icon is how a kill is recognised, not a second thing to look for.
    if plan["kill"] or plan["death"]:
        people = {str(plan[k]).lower() for k in ("killer", "victim") if plan[k]}
        plan["pictures"] = [n for n in plan["pictures"] if n.lower() not in people]

    # Is there anything left that only "looking" can find?
    rest = text
    for name, aliases in agents.items():
        for alias in aliases:
            rest = re.sub(rf"(?<!\w){re.escape(alias)}(?:'s|s)?(?!\w)", " ", rest)
    for low in lowered:
        rest = rest.replace(low, " ")
    rest = re.sub(r"\b(kill\w*|frag\w*|eliminat\w+|head[\s-]?shots?|die[ds]?|dying|deaths?|ace|quadra|"
                  r"quad|triple|double|multi\w*|[2-5]k|loud\w*|scream\w*|shout\w*|hype|i|gets?|got|"
                  r"getting|with|as|using|playing|by|on|against|vs|versus|enemy|best|top|time)\b", " ", rest)
    rest = FILLER.sub(" ", rest)
    rest = " ".join(re.findall(r"[a-z0-9]{2,}", rest))
    plain_event = plan["kill"] or plan["death"] or plan["loud"] or plan["said"] or plan["pictures"]
    if rest and not plain_event:
        plan["description"] = original
    elif len(rest.split()) >= 2 and not plan["said"]:
        plan["description"] = original       # e.g. "kill while the spike is planted"
    if not (plain_event or plan["description"]):
        plan["description"] = original
    return plan


def explain(plan: dict) -> str:
    """What the app understood, in one plain sentence."""
    parts = []
    who = lambda n: "you" if n == "me" else n
    if plan["multi"]:
        parts.append(f"{plan['multi']} or more kills close together")
    if plan["death"]:
        parts.append(f"moments where you are killed" + (f" by {plan['killer']}" if plan["killer"] not in (None, "me") else ""))
    elif plan["kill"]:
        parts.append(f"kills by {who(plan['killer'] or 'anyone')}" + (f" on {plan['victim']}" if plan["victim"] else ""))
    if plan["said"]:
        parts.append(f"where \"{plan['said']}\" is said")
    if plan["pictures"]:
        parts.append("showing your picture(s) " + ", ".join(plan["pictures"]))
    if plan["loud"]:
        parts.append("loud moments")
    if plan["description"]:
        parts.append(f"a scene that looks like: \"{plan['description']}\"")
    span = plan["range"]
    if span["last"]:
        parts.append(f"in the last {span['last']:.0f} s")
    elif span["from"] is not None or span["to"] is not None:
        parts.append(f"between {span['from'] or 0:.0f} s and {span['to']:.0f} s" if span["to"] is not None
                     else f"after {span['from']:.0f} s")
    return "Looking for " + ", ".join(parts) + "."
