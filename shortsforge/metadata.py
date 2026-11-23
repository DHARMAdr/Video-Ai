"""
metadata.py - creates a title and hashtags for each short (no AI needed).

WHY it exists:
    A finished short still needs a title/description to be uploaded. This gives you a decent
    starting point you can edit (or upgrade with the optional LLM from llm.py).

HOW it works:
    - Title: the opening sentence, shortened to ~60 characters at a word boundary.
    - Hashtags: the most frequent "interesting" words (stop-words removed) + #shorts #reels.

HOW TO IMPROVE:
    - Use the LLM for titles in your channel's voice.
    - Add trending-hashtag lists per niche that you update by hand each month.
"""

import re
from collections import Counter

# Very common words that make useless hashtags.
STOP = set("""about above after again also always another because been before being between
both could does doing down during each even every from further have having here into just
like make many more most much must never only other over really same should since some such
than that their them then there these they this those through under until very want were what
when where which while will with would your you're it's don't can't i'm that's gonna""".split())


def make_title(first_sentence: str, limit: int = 60) -> str:
    """Shorten the first sentence to a title."""
    text = re.sub(r"\s+", " ", first_sentence).strip().rstrip(".,;:")
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0]   # cut at the last full word
    return cut.rstrip(".,;:") + "..."


def make_hashtags(text: str, count: int = 5) -> list:
    """Most common meaningful words -> hashtags."""
    words = re.findall(r"[a-z]{5,}", text.lower())
    common = Counter(w for w in words if w not in STOP).most_common(count)
    tags = [f"#{w}" for w, _ in common]
    return tags + ["#shorts", "#reels"]
