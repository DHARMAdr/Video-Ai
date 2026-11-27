"""
query.py - understands what is being asked.

WHY: "can you tell me what the latest patch of Valorant is?" searches badly. Search services
    like a few important words, and different questions need different services.
HOW: remove polite filler, spot whether the question is about NEWS or about PROGRAMMING, and
    make a second, shorter way to ask.
HOW TO IMPROVE: add more languages; fix spelling mistakes.
"""

import datetime
import re

STOP = set("""a an and are as at be been being but by can could did do does for from had has
have how i if in into is it its me my of on or our please tell than that the their them then
there these they this to was we were what when where which who whom why will with would you
your about give show find search look up know want need let some any more most
many much made make makes used use does standard called
बताओ क्या है""".split())

FILLER = re.compile(r"(?i)^\s*(hey|hi|ok|okay|please|can you|could you|will you|i want to know|"
                    r"tell me|search for|search|google|look up|find out|find me)\b[\s,:]*")
NEWS = re.compile(r"(?i)\b(latest|newest|recent|today|yesterday|tonight|this (week|month|year)|"
                  r"news|update|patch|released?|launch(ed)?|current(ly)?|now|score|winner|won|"
                  r"price|announce[ds]?)\b")
CODE = re.compile(r"(?i)\b(error|exception|traceback|python|javascript|typescript|java|c\+\+|"
                  r"c#|rust|golang|ffmpeg|code|function|library|api|npm|pip|compile|debug|"
                  r"github|repository|repo)\b")


def words(text: str) -> list:
    """Lower-case words of any language (letters and digits; keeps 9.04, c++ and c#)."""
    found = re.findall(r"[^\W_]+(?:[.'][^\W_]+)*[+#]*", str(text or "").lower(), re.UNICODE)
    return [w[:-2] if w.endswith("'s") else w for w in found]


def stem(word: str) -> str:
    """A very small English stemmer, so 'kills' also matches 'kill'."""
    for ending in ("ing", "ies", "ed", "es", "s"):
        if word.endswith(ending) and len(word) - len(ending) >= 3:
            return word[:-len(ending)] + ("y" if ending == "ies" else "")
    return word


def clean(question: str) -> str:
    text = " ".join(str(question or "").split())[:200]
    while True:
        shorter = FILLER.sub("", text, count=1)
        if shorter == text:
            return text.strip(" ?!.")
        text = shorter


def understand(question: str, today=None) -> dict:
    """Return {"text", "keywords", "variants", "news", "code"}."""
    today = today or datetime.date.today()
    text = clean(question)
    keywords = [w for w in words(text) if w not in STOP] or words(text)
    news = bool(NEWS.search(text))
    variants = [text]
    short = " ".join(keywords)
    if short and short != text.lower():
        variants.append(short)
    if news and not re.search(r"\b20\d\d\b", text):
        variants.append(f"{short} {today.year}")
    return {"text": text, "keywords": keywords, "variants": variants[:3],
            "news": news, "code": bool(CODE.search(text))}
