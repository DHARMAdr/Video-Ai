"""
find - "describe it, find it, cut it": search a video for a moment you describe in words.

WHY it exists:
    Automatic shorts only know about YOUR kills and loud moments. You also want to ask for
    one special thing: "when I kill Jett", "where I say clutch", "the spike being planted".

HOW it works (one file per step):
    query.py    - turns your sentence into a clear search (what, who, when, how many)
    video.py    - reads frames, sound and shot changes
    pictures.py - the example pictures you taught (agent icons, weapons, screens)
    feed.py     - reads the kill feed: who killed whom, and when
    speech.py   - searches what was said
    vision.py   - asks the built-in AI to LOOK at frames
    moments.py  - combines all clues into moments with a start, an end and a confidence
    engine.py   - runs the whole search and cuts the clips

HOW TO IMPROVE:
    - Add a new kind of clue as a new file that returns "hits" (see moments.hit).
"""
