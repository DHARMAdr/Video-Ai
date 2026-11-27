"""
router.py - understands everyday commands WITHOUT any AI model.

WHY it exists:
    Small or offline AI models are slow and often get tool use wrong. But most of what you ask the
    app is simple and predictable: "make 5 shorts from my last video", "trim clip 2 to 0:40-1:10",
    "find where I say pricing". Rules can understand these perfectly, instantly, for free, with
    no internet. Only open questions ("write me a script", "explain...") need a real AI.

HOW it works (two steps, so it is easy to test):
    1. parse(text)   -> a small dict like {"intent": "trim", "clip": 2, "start": 40, "end": 70}
                        or None when the message is not a command (then the AI model answers).
    2. execute(...)  -> runs that intent with the same tools the AI uses, and writes a friendly reply.

COMMANDS (examples; wording is flexible):
    help / what can you do        show my projects / clips        show project <name>
    make 5 shorts from my last video        make valorant shorts with at least 2 kills
    make shorts from https://...            trim clip 2 to 0:40-1:10
    add a clip from 1:05 to 1:40 called Big moment      find where I talk about pricing
    search all my videos for budget         status / is it done        remember that I like blur
    what do you remember / forget everything

HOW TO IMPROVE:
    - Add intents (change layout of a project, delete a clip, export all) = a new branch in parse()
      plus a new branch in execute(), plus rows in tests/test_router.py.
    - Add more phrasings or other languages to the word lists at the top.
"""

import json
import re
from pathlib import Path

from .. import ingest
from ..find import query as find_query
from . import library
from .assistant import mmss

NUMBER_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
                "nine": 9, "ten": 10, "twelve": 12, "fifteen": 15, "twenty": 20}
ORDINALS = {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "sixth": 6, "seventh": 7,
            "eighth": 8, "ninth": 9, "tenth": 10, "last": -1}

TIME = r"(?:\d+:\d{1,2}(?::\d{1,2})?|\d+m\d*s?|\d+(?:\.\d+)?\s*(?:seconds?|secs?|minutes?|mins?|s|m)?)"
RANGE = re.compile(rf"(?P<a>{TIME})\s*(?:to|-|–|—|until|till|and|through)\s*(?P<b>{TIME})", re.I)
START_END = re.compile(rf"start(?:s|ing)?(?:\s+at|\s+from)?\s+(?P<a>{TIME})\s*(?:,|and|then)?\s*(?:end|ends|ending|finish|stop)(?:s|ing)?(?:\s+at)?\s+(?P<b>{TIME})", re.I)
CLIP_REF = re.compile(r"\b(?:clip|short|reel|number|no\.?|#)\s*#?\s*(\d{1,2})\b|#(\d{1,2})\b", re.I)
ORDINAL_REF = re.compile(r"\b(first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth|last)\s+(?:clip|short|reel|one)\b", re.I)
URL = re.compile(r"https?://\S+", re.I)

HELP_TEXT = """Here is what I can do. You can type it in your own words:

**Make shorts**
- make 5 shorts from my last video
- make valorant shorts with at least 2 kills
- make shorts from https://... (a video link)

**Edit clips**
- trim clip 2 to 0:40-1:10
- add a clip from 1:05 to 1:40 called Big moment

**Do more with clips**
- make clip 2 black and white / slow motion / add text "WOW" to clip 1
- join clips 1, 2 and 3
- find where I kill Jett  /  find my triple kills (opens the Find screen)
- delete clip 2  /  restore the clip
- find my valorant video  /  open the editor  /  dark mode

**Look around**
- show my projects  /  show project <name>
- find where I talk about pricing
- search all my videos for budget
- status (is it finished?)

**Memory**
- remember that I prefer the blur layout
- what do you remember  /  forget everything

For anything else (ideas, titles, writing, questions) I use the AI you connect in Settings."""


# ---------------------------------------------------------------------------
# Small parsing helpers
# ---------------------------------------------------------------------------
def parse_time(text: str):
    """'1:05' -> 65, '90s' -> 90, '1m30' -> 90, '2 minutes' -> 120, '45' -> 45. None if unreadable."""
    t = str(text).strip().lower().replace(" ", "")
    try:
        if ":" in t:
            total = 0.0
            for part in t.split(":"):
                total = total * 60 + float(part)
            return total
        m = re.fullmatch(r"(\d+)m(\d*)s?", t)
        if m:
            return int(m.group(1)) * 60 + (int(m.group(2)) if m.group(2) else 0)
        m = re.fullmatch(r"(\d+(?:\.\d+)?)(seconds?|secs?|s|minutes?|mins?|m)?", t)
        if m:
            value = float(m.group(1))
            return value * 60 if (m.group(2) or "").startswith("m") else value
    except ValueError:
        pass
    return None


def _count(text: str):
    """How many shorts did the user ask for? None if not said."""
    m = re.search(r"\b(\d{1,2})\s*(?:short|clip|reel|video|highlight|moment)s?\b", text)
    if m:
        return max(1, min(20, int(m.group(1))))
    m = re.search(r"\b(" + "|".join(NUMBER_WORDS) + r")\s+(?:short|clip|reel|highlight|moment)s?\b", text)
    if m:
        return NUMBER_WORDS[m.group(1)]
    m = re.search(r"\b(?:top|best)\s+(\d{1,2})\b", text)
    return max(1, min(20, int(m.group(1)))) if m else None


def _clip_number(text: str):
    """Which clip does the user mean? 1-based number, -1 for 'last', None if not said."""
    m = CLIP_REF.search(text)
    if m:
        return int(m.group(1) or m.group(2))
    m = ORDINAL_REF.search(text)
    return ORDINALS[m.group(1).lower()] if m else None


def _time_range(text: str):
    """(start, end) seconds from text like '0:40-1:10', or None."""
    cleaned = CLIP_REF.sub(" ", text)
    cleaned = ORDINAL_REF.sub(" ", cleaned)
    m = START_END.search(cleaned) or RANGE.search(cleaned)
    if not m:
        return None
    a, b = parse_time(m.group("a")), parse_time(m.group("b"))
    return (a, b) if a is not None and b is not None else None


def _title(text: str):
    """A title given as: called/titled/named X, or 'quoted'."""
    m = re.search(r"\b(?:called|titled|named|title)\s*[:=]?\s*[\"“']?(.+?)[\"”']?\s*$", text, re.I)
    if m:
        return m.group(1).strip()[:90] or None
    return None


def _quoted(text: str):
    m = re.search(r"[\"“']([^\"”']{2,80})[\"”']", text)
    return m.group(1).strip() if m else None


# Spoken word -> editor setting.
EDIT_WORDS = [
    (r"black and white|\bb&w\b|greyscale|grayscale", "filter", "black and white"),
    (r"\bwarm(?:er)?\b", "filter", "warm"), (r"\bcool(?:er)? (?:filter|look|tone)", "filter", "cool"),
    (r"\bvivid\b|more colou?rful", "filter", "vivid"), (r"\bcinematic\b", "filter", "cinematic"),
    (r"\bvintage\b", "filter", "vintage"), (r"\bsepia\b", "filter", "sepia"),
    (r"slow ?-?mo(?:tion)?|slow (?:it )?down|slower", "speed", 0.5),
    (r"speed (?:it )?up|\bfaster\b", "speed", 1.5), (r"\bshake\b", "effect", "shake"),
    (r"\bglitch\b", "effect", "glitch"), (r"\bvhs\b", "effect", "vhs"),
    (r"zoom punch|punch zoom", "effect", "zoom punch"), (r"\bzoom in\b", "effect", "zoom in"),
    (r"\bvignette\b", "effect", "vignette"), (r"\bmirror|\bflip (?:it )?horizontal", "mirror", True),
    (r"\bmute\b|no sound", "volume", 0.0),
]


def _edit_intent(raw: str, low: str):
    """"make clip 2 black and white", "join clips 1, 2 and 3" -> an edit intent, else None."""
    numbers = []
    for m in re.finditer(r"\b(?:clips?|shorts?|reels?)\s+((?:\d{1,2}(?:\s*(?:,|and|&|\+)\s*)?)+)", low):
        numbers += [int(n) for n in re.findall(r"\d{1,2}", m.group(1))]
    if not numbers:
        return None
    changes = {}
    for pattern, key, value in EDIT_WORDS:
        if re.search(pattern, low):
            changes[key] = value
    speed = re.search(r"\b(\d(?:\.\d+)?)\s*x\b", low)
    if speed:
        changes["speed"] = float(speed.group(1))
    join = bool(re.search(r"\b(?:join|merge|combine|montage|stitch)\b", low)) and len(numbers) > 1
    words = re.search(r"\b(?:add|put|write)\b.*?\btext\b\s*[:=]?\s*[\"“']?(.+?)[\"”']?\s*(?:\b(?:to|on|in)\s+(?:clip|short|reel).*)?$", raw, re.I)
    if words and _quoted(raw):
        text = _quoted(raw)
    elif words:
        text = re.sub(r"\b(?:to|on|in)\s+(?:clip|short|reel)s?\b.*$", "", words.group(1), flags=re.I).strip()
    else:
        text = ""
    if not (changes or join or text):
        return None
    return {"intent": "edit", "clips": numbers, "changes": changes, "text": text, "project": raw}


# ---------------------------------------------------------------------------
# Step 1: parse (pure text -> intent; no side effects)
# ---------------------------------------------------------------------------
def _scene_request(low: str) -> bool:
    """Is this "find me that moment inside a video"? (not a video file, project or spoken words)."""
    if not re.search(r"^(?:please |can you |could you )?(?:find|locate|search|show|cut|crop|get|clip)\b", low):
        return False
    if re.search(r"\b(?:say|said|saying|mention\w*|talk\w*|discuss\w*|speak\w*|transcript|projects?|"
                 r"make|create|generate)\b", low) or re.search(r"\bkills? (?:video|recording)s?\b", low):
        return False
    if find_query.find_agents(low, find_query.load_agents()) and re.search(r"\bkill|\bdie|\bdeath", low):
        return True
    return bool(re.search(r"\b(?:scenes?|moment where|part where|where (?:i|we|the|there)\b.*\b(?:kill|die|plant|defus|win|los)\w*|"
                          r"(?:ace|triple kill|double kill|quadra kill)s?|my (?:kills|deaths))\b", low))


def parse(text: str):
    """Turn a message into an intent dict, or None if it is not a command we know."""
    raw = " ".join(str(text or "").split())
    low = raw.lower().strip(" .!?")
    if not low:
        return None

    # ----- the internet and upload texts need the AI, not the offline commands -----
    if re.search(r"\b(?:web|internet|online|google|wikipedia)\b", low) and \
            re.search(r"\b(?:search|look|find|check|google)\b", low):
        return None
    if re.search(r"\bhashtags?\b|\bdescriptions?\b|\b(?:write|suggest|give)\b.*\btitles?\b", low) and \
            not re.search(r"\b(?:say|said|mention\w*|talk\w*)\b", low) and not _time_range(low):
        return None

    # ----- help -----
    if re.fullmatch(r"(?:help|\?|commands?|menu|(?:what|how) (?:can|do) you (?:do|work)\b.*|what are your (?:commands|features|abilities)|how (?:do|to) (?:i )?use (?:you|this|it))", low):
        return {"intent": "help"}

    # ----- memory -----
    m = re.match(r"(?:please )?remember(?: that| this| :)?\s+(.+)", raw, re.I)
    if m:
        return {"intent": "remember", "text": m.group(1)}
    if re.search(r"\b(?:what|which things?) (?:do you|did you) (?:remember|know about me)\b|\bshow (?:my )?(?:memory|notes)\b|\bwhat have i told you\b", low):
        return {"intent": "recall"}
    if re.search(r"\b(?:forget (?:everything|all|it all)|clear (?:your |the )?memory|wipe (?:your )?memory)\b", low):
        return {"intent": "forget"}

    # ----- status -----
    if re.search(r"\b(?:status|progress|is it (?:done|finished|ready)|are (?:you|we) done|how long|still (?:working|running))\b", low) and len(low) < 60:
        return {"intent": "status"}

    # ----- open a screen / theme -----
    m = re.fullmatch(r"(?:please )?(?:open|go to|switch to)(?: the| my)? (create|clips|find|teach|editor|settings)(?: screen| tab| page)?", low)
    if m:
        return {"intent": "screen", "screen": m.group(1)}
    m = re.fullmatch(r"(?:please )?(?:switch to|turn on|use|set)?\s*(dark|light) (?:mode|theme)", low)
    if m:
        return {"intent": "theme", "theme": m.group(1)}

    # ----- delete / restore a clip -----
    if re.search(r"\b(?:restore|bring back|undo (?:the )?delete)\b", low) and \
            re.search(r"\b(?:clip|short|reel|it|that)\b", low):
        return {"intent": "restore", "project": raw}
    if re.search(r"\b(?:delete|remove)\b", low) and _clip_number(low) is not None \
            and not re.search(r"\b(?:text|effect|filter|music|sound|caption)s?\b", low):
        return {"intent": "delete", "clip": _clip_number(low), "project": raw}

    # ----- edit or join finished clips -----
    edit = _edit_intent(raw, low)
    if edit:
        return edit

    # ----- find a SCENE inside a video (kill on a character, spike, ace ...) -----
    if _scene_request(low):
        return {"intent": "scene", "text": raw}

    # ----- find a video FILE on this PC -----
    if re.search(r"\b(?:find|locate|search for|look for|where(?: is|'s)?)\b.*\b(?:video|videos|recording|recordings|footage|file)\b", low) \
            and not re.search(r"\b(?:say|said|saying|mention\w*|talk\w*|discuss\w*|speak\w*|about|word|phrase|topic|transcript|projects?|shorts?|clips?|part|moment)\b", low) \
            and not re.search(r"\b(?:make|create|generate)\b", low):
        return {"intent": "find_video", "text": raw}

    times = _time_range(low)
    clip = _clip_number(low)
    has_verb_edit = re.search(r"\b(?:trim|cut|shorten|change|set|edit|adjust|fix|move|make|update|re-?export|crop)\b", low)
    has_verb_add = re.search(r"\b(?:add|new|another|create|make|cut|extract|save)\b", low)
    mentions_clip = re.search(r"\b(?:clip|short|reel|part|moment|section|segment)s?\b", low)

    # ----- trim an existing clip: needs a clip number + a time range -----
    if times and clip is not None and has_verb_edit and not re.search(r"\b(?:add|new|another)\b", low):
        return {"intent": "trim", "clip": clip, "start": times[0], "end": times[1],
                "title": _title(raw), "project": raw}

    # ----- add a new clip from a time range -----
    if times and mentions_clip and has_verb_add:
        return {"intent": "add", "start": times[0], "end": times[1], "title": _title(raw), "project": raw}

    # ----- search what was said -----
    if re.search(r"\b(?:find|search|look (?:for|up)|locate|where (?:do|did|does|is|was)|when (?:do|did|does|was)|which (?:part|video|clip))\b", low) and \
            re.search(r"\b(?:say|said|saying|mention\w*|talk\w*|discuss\w*|speak\w*|about|for|word|phrase|topic|transcript|video|videos|projects?)\b", low) and \
            not re.search(r"\b(?:make|create|generate)\b.*\b(?:shorts?|reels?)\b", low):
        query = _quoted(raw)
        if not query:
            m = re.search(r"\b(?:about|for|mention(?:s|ed|ing)?|say(?:s|ing)?|said|discuss(?:es|ed|ing)?|talk(?:s|ed|ing)? about|word|phrase|topic)\s+(.+)$", low)
            if m:
                query = m.group(1)
        if not query:
            return None
        query = re.sub(r"\b(?:in|from|across|inside)\s+(?:all\s+)?(?:my\s+|the\s+|this\s+|last\s+)?(?:\w+\s+)?(?:videos?|projects?|clips?|transcripts?)$", "", query).strip(" .?!")
        query = re.sub(r"^(?:all\s+)?(?:my\s+)?(?:videos?|projects?)\s+(?:for|about)\s+", "", query).strip()
        if len(query) < 2:
            return None
        everywhere = bool(re.search(r"\b(?:all|every|any|each|across|everywhere)\b", low))
        return {"intent": "search", "query": query, "scope": "all" if everywhere else "one", "project": raw}

    # ----- make shorts -----
    if re.search(r"\b(?:make|create|generate|cut|produce|turn|convert|find|get|give me|extract)\b", low) and \
            re.search(r"\b(?:shorts?|reels?|highlights?|clips?|tiktoks?|plays?|moments?|kills?)\b", low) and \
            not re.search(r"\b(?:ideas?|titles?|hashtags?|captions? for|script|description)\b", low):
        game = bool(re.search(r"\b(?:valorant|game|gameplay|kills?|ace|clutch|frag|plays?)\b", low))
        out = {"intent": "make", "mode": "game" if game else "talk", "count": _count(low), "text": raw}
        url = URL.search(raw)
        if url:
            out["source"] = url.group(0).rstrip(".,)")
        if re.search(r"\bblur", low):
            out["layout"], out["framing"] = "blur", "blur"
        elif re.search(r"\b(?:facecam|stack(?:ed)?)\b", low):
            out["layout"] = "stack"
        elif re.search(r"\b(?:center|centre|zoom)\b", low):
            out["layout"], out["framing"] = "center", "center"
        if re.search(r"\b(?:without|no)\s+captions?\b", low):
            out["captions"] = False
        mk = re.search(r"(?:at least|min(?:imum)?|only)\s+(\d)\s*kills?", low)
        if mk:
            out["min_kills"] = max(1, min(5, int(mk.group(1))))
        elif re.search(r"\b(?:doubles?|double kills?)\b", low):
            out["min_kills"] = 2
        elif re.search(r"\b(?:triples?|triple kills?)\b", low):
            out["min_kills"] = 3
        return out

    # ----- show projects / clips -----
    if re.search(r"\b(?:show|list|open|see|view|display|what are|what's|whats)\b", low) and \
            re.search(r"\b(?:projects?|clips?|shorts?|reels?|videos?|results?|work|files?)\b", low):
        return {"intent": "show", "project": raw,
                "all": bool(re.search(r"\b(?:projects|all|everything|videos|files)\b", low)) and
                       not re.search(r"\b(?:project|clips?|shorts?) (?:named|called)\b", low)}
    if re.fullmatch(r"(?:my )?(?:projects|clips|shorts|videos)", low):
        return {"intent": "show", "project": raw, "all": low.endswith(("projects", "videos"))}
    return None


# ---------------------------------------------------------------------------
# Step 2: execute (runs the intent with the app's tools, writes a friendly reply)
# ---------------------------------------------------------------------------
def _call(toolbox, name, **args):
    """Run a tool and return (result dict, label)."""
    text, label = toolbox.run(name, args)
    return json.loads(text), label


def _projects(toolbox):
    return _call(toolbox, "list_projects")[0].get("projects", [])


def _pick_project(toolbox, text: str):
    """The project the user means: named in the text, else the newest. None if there are none."""
    projects = _projects(toolbox)
    if not projects:
        return None
    flat = re.sub(r"[^a-z0-9]+", " ", text.lower())
    for p in projects:
        name = re.sub(r"[^a-z0-9]+", " ", p["name"].lower()).strip()
        if name and name in flat:
            return p["name"]
    for p in projects:                                  # a distinctive word of the name, e.g. "cooking"
        words = [w for w in re.sub(r"[^a-z0-9]+", " ", p["name"].lower()).split() if len(w) > 3 and not w.isdigit()]
        if any(w in flat.split() for w in words):
            return p["name"]
    return projects[0]["name"]                          # newest first


def _newest_video(toolbox, text: str):
    """Video the user means: the file name or words in the text, else the newest one."""
    videos = _call(toolbox, "list_videos")[0].get("videos", [])
    low = text.lower()
    for v in videos:
        if Path(v["path"]).name.lower() in low:
            return v["path"]
    named = re.search(r"\b(?:from|of|using)\s+(?:the\s+|my\s+)?(.+?)(?:\s+with\b|$)", low)
    if named:
        words = [w for w in re.findall(r"[a-z0-9]+", named.group(1)) if w not in library.FILLER]
        if words:                                       # "from my stream recording" -> "stream"
            found = _call(toolbox, "find_videos", name=" ".join(words))[0].get("videos", [])
            return found[0]["path"] if found else None
    used = [v for v in videos if v["where"] != "on this PC"]
    best = max(used or videos, key=lambda v: v["modified"], default=None)
    return best["path"] if best else None


def _clip_lines(clips):
    lines = []
    for c in clips:
        score = f" (score {c['score']})" if c.get("score") is not None else ""
        kills = f", {len(c['kills_at_seconds'])} kills" if c.get("kills_at_seconds") else ""
        lines.append(f"{c['number']}. **{c.get('title') or 'Untitled'}**: {mmss(c['start'])} to {mmss(c['end'])}{score}{kills}")
    return "\n".join(lines)


def execute(intent: dict, toolbox, memory):
    """Run an intent. Returns (reply_text, [action labels])."""
    actions = []

    def run(name, **args):
        result, label = _call(toolbox, name, **args)
        actions.append(label)
        return result

    kind = intent["intent"]

    if kind == "help":
        return HELP_TEXT, actions

    if kind == "remember":
        note = memory.add(intent["text"])
        return f"Okay, I will remember: \"{note}\"", actions
    if kind == "recall":
        notes = memory.texts()
        return ("Here is what I remember:\n" + "\n".join(f"- {n}" for n in notes)) if notes else \
            "I have no notes yet. Say \"remember that ...\" and I will keep it.", actions
    if kind == "forget":
        memory.clear()
        return "Done. I forgot everything I had noted.", actions

    if kind == "screen":
        data = run("open_screen", screen=intent["screen"])
        return data.get("error") or f"Opened {intent['screen']}.", actions
    if kind == "theme":
        data = run("set_options", theme=intent["theme"])
        return data.get("error") or f"Switched to {intent['theme']} mode.", actions
    if kind in ("delete", "restore", "edit"):
        project = _pick_project(toolbox, intent["project"])
        if not project:
            return "You need a project first. Make some shorts, then I can edit them.", actions
        if kind == "delete":
            number = intent["clip"]
            if number == -1:
                number = len(run("get_project", name=project).get("clips", [])) or 1
            data = run("delete_clip", project=project, clip_number=number)
            return data.get("error") or (f"Deleted clip {number} of **{project}**. Say "
                                         "\"restore the clip\" to bring it back."), actions
        if kind == "restore":
            data = run("restore_clip", project=project)
            return data.get("error") or f"Brought back: {data.get('restored')}.", actions
        data = run("edit_clips", project=project, clips=intent["clips"], text=intent["text"],
                   **intent["changes"])
        if "error" in data:
            return data["error"], actions
        return ("Started the edit. Your original clips stay; the new video appears in the project "
                "**Edits**."), actions

    if kind == "find_video":
        data = run("find_videos", name=intent["text"])
        videos = data.get("videos", [])
        if not videos:
            places = ", ".join(data.get("searched", [])[:6])
            return (f"I could not find a matching video. I looked in: {places}.\nPress **Browse** in "
                    "the Create tab, or add your recording folder in Settings > Video folders."), actions
        lines = [f"- **{v['name']}** ({v['size_mb']} MB, {v['date']})\n  {v['path']}" for v in videos[:6]]
        return ("I found these (newest first):\n" + "\n".join(lines) +
                "\n\nSay \"make valorant shorts from <name>\" to use one."), actions

    if kind == "scene":
        video = _newest_video(toolbox, intent["text"])
        if not video:
            return ("I could not find a video to search. Open the **Find** tab and press Browse.",
                    actions)
        # Words about WHICH video are not part of the scene description.
        wanted = re.sub(r"\b(?:in|from)\s+(?:my|the)\s+(?:last\s+|latest\s+|newest\s+)?[\w .-]*?"
                        r"(?:video|recording|stream|footage)\b", " ", intent["text"], flags=re.I)
        result = run("find_scene", video=video, description=" ".join(wanted.split()))
        if result.get("started"):
            return (f"Searching **{Path(video).name}**. The results will appear on the **Find** "
                    "screen, where you tick the ones to cut."), actions
        return result.get("error", "I could not start the search."), actions

    if kind == "status":
        jobs = toolbox.state.jobs.jobs
        if not jobs:
            return "Nothing is running right now.", actions
        job = list(jobs.values())[-1]
        snap = toolbox.state.jobs.snapshot(job.id, 0)
        if snap["status"] == "running":
            tail = snap["log"][-1] if snap["log"] else "starting"
            return f"Still working. Last step: {tail}", actions
        if snap["status"] == "done":
            name = (snap.get("result") or {}).get("project_name")
            return "The last task is finished." + (f" Open the Clips tab and choose **{name}**." if name else ""), actions
        return f"The last task stopped: {snap.get('error') or 'something went wrong'}", actions

    if kind == "show":
        projects = _projects(toolbox)
        actions.append("Looked at your projects")
        if not projects:
            return "You have no projects yet. Open the Create tab, choose a video and press Make shorts. Or tell me: make 5 shorts from my last video.", actions
        named = _pick_project(toolbox, intent["project"])
        flat = re.sub(r"[^a-z0-9]+", " ", intent["project"].lower())
        explicit = any(re.sub(r"[^a-z0-9]+", " ", p["name"].lower()).strip() in flat for p in projects)
        if intent.get("all") and not explicit:
            return "Your projects (newest first):\n" + "\n".join(f"- **{p['name']}**: {p['clips']} clips" for p in projects[:12]), actions
        data = run("get_project", name=named)
        if "error" in data:
            return data["error"], actions
        return f"**{data['name']}** has {len(data['clips'])} clips:\n" + _clip_lines(data["clips"]), actions

    if kind == "search":
        if intent["scope"] == "all":
            data = run("search_all_transcripts", query=intent["query"])
        else:
            project = _pick_project(toolbox, intent["project"])
            if not project:
                return "There is nothing to search yet. Make shorts from a talking video first.", actions
            data = run("search_transcript", project=project, query=intent["query"])
        if "error" in data:
            return data["error"], actions
        matches = data.get("matches", [])
        if not matches:
            return f"I could not find \"{intent['query']}\" in the transcripts.", actions
        lines = []
        for m in matches[:6]:
            where = f" ({m['project']})" if m.get("project") else ""
            lines.append(f"- **{m['at']}**{where}: {m['text']}")
        hint = "\n\nTo turn one into a short, say: add a clip from 1:05 to 1:40"
        return f"Found {len(matches)} place{'s' if len(matches) != 1 else ''}:\n" + "\n".join(lines) + hint, actions

    if kind in ("trim", "add"):
        project = _pick_project(toolbox, intent["project"])
        if not project:
            return "You need a project first. Make some shorts, then I can edit them.", actions
        if intent["end"] <= intent["start"]:
            return "The end time must be after the start time. For example: trim clip 2 to 0:40-1:10.", actions
        if kind == "trim":
            number = intent["clip"]
            if number == -1:
                data = run("get_project", name=project)
                number = len(data.get("clips", [])) or 1
            data = run("trim_clip", project=project, clip_number=number, start_seconds=intent["start"],
                       end_seconds=intent["end"], title=intent.get("title"))
            if "error" in data:
                return data["error"], actions
            return f"Done. Clip {number} of **{project}** now runs {mmss(intent['start'])} to {mmss(intent['end'])}.", actions
        data = run("add_clip", project=project, start_seconds=intent["start"], end_seconds=intent["end"],
                   title=intent.get("title"))
        if "error" in data:
            return data["error"], actions
        return f"Done. I added a new clip ({mmss(intent['start'])} to {mmss(intent['end'])}) to **{project}**. Open it in the Clips tab.", actions

    if kind == "make":
        source = intent.get("source") or _newest_video(toolbox, intent["text"])
        if not source:
            return ("I do not see a video yet. Upload one in the Create tab (or drop it onto the window), "
                    "or paste a video link, then ask me again."), actions
        args = {"source": source, "mode": intent["mode"], "count": intent.get("count") or 5}
        for key in ("layout", "framing", "min_kills", "captions"):
            if key in intent:
                args[key] = intent[key]
        data = run("make_shorts", **args)
        if not data.get("started"):
            return data.get("error", "I could not start that."), actions
        name = source if ingest.is_url(source) else Path(source).name
        kind_word = "Valorant highlights" if intent["mode"] == "game" else "shorts"
        return (f"Started! I am making {args['count']} {kind_word} from **{name}**. It can take several minutes. "
                "Watch the progress strip at the top. I will tell you when it is ready."), actions

    return "Sorry, I did not understand that.", actions
