"""
test_search.py - measures the built-in search on the REAL internet.

WHY: tests/test_localsearch.py cannot tell whether the services still answer today.
HOW: asks questions with known answers and counts how often the answer appears in what the
    assistant would read. Prints which services replied. Run: python packaging/test_search.py
    (or the "Test web search" workflow on GitHub).
HONEST: this measures "is the answer in the results", on a small fixed list of fairly easy
    questions. It is not a comparison with Tavily. GitHub's computers may be refused more often
    than your home connection, or less often.
HOW TO IMPROVE: add your own kind of questions; with a Tavily key, ask both and compare.
"""

import re
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from shortsforge.app.localsearch import engine, query, sources  # noqa: E402

# (question, words of which at least one must appear)
QUESTIONS = [
    ("how tall is the Eiffel Tower", ["330", "324"]),
    ("who painted the Mona Lisa", ["leonardo"]),
    ("what is the capital of Australia", ["canberra"]),
    ("what year did the first iPhone come out", ["2007"]),
    ("who is the developer of Valorant", ["riot"]),
    ("Valorant agent Jett is from which country", ["korea"]),
    ("how many players are in a standard PUBG match", ["100"]),
    ("what is the maximum length of a YouTube Short", ["3 minutes", "three minutes", "180"]),
    ("ffmpeg filter to change playback speed of video", ["setpts"]),
    ("python how to reverse a list", ["reverse", "[::-1]"]),
    ("what does FPS stand for in video games", ["frames per second", "first-person", "first person"]),
    ("boiling point of water at sea level in celsius", ["100"]),
    ("who wrote the novel Pride and Prejudice", ["austen"]),
    ("what is the currency of Japan", ["yen"]),
    ("what aspect ratio are Instagram Reels", ["9:16"]),
    ("who founded Microsoft", ["gates"]),
    ("what is the largest planet in the solar system", ["jupiter"]),
    ("what GPU memory does the RTX 5060 Ti have", ["8gb", "8 gb", "16gb", "16 gb"]),
    ("which company makes CapCut", ["bytedance"]),
    ("what is whisper by OpenAI used for", ["speech", "transcri"]),
]


def main() -> int:
    replies, hits, times = Counter(), 0, []
    for question, expected in QUESTIONS:
        start = time.time()
        try:
            found = engine.search(question)
        except ValueError as err:
            found = {"source": str(err), "results": []}
        times.append(time.time() - start)
        text = " ".join(f"{r['title']} {r['extract']}" for r in found["results"]).lower()
        good = any(word in text for word in expected)
        hits += good
        for name in sources.SOURCES.keys() | {sources.BACKUP[0]}:
            replies[name] += name in found["source"].split(": ")[-1].rstrip(")").split(", ")
        print(f"{'OK  ' if good else 'MISS'} {times[-1]:5.1f}s {question}")
        for result in found["results"][:1 if good else 5]:
            print(f"       {result['url']}")
        time.sleep(2)                       # be polite to the free services
    print(f"\nAnswer found for {hits} of {len(QUESTIONS)} questions "
          f"({100 * hits // len(QUESTIONS)}%). Average {sum(times) / len(times):.1f}s.")
    print("Services that gave results (questions):", dict(replies.most_common()))

    print("\nOne request to each service:")
    for name, spec in list(sources.SOURCES.items()):
        try:
            body = sources.download(spec[0](query.clean("python ffmpeg latest release")))
            count = len(spec[1](body))
            print(f"  {name}: {count} results read from {len(body)} letters")
            if not count:           # show what came back, to fix the reader
                title = re.search(r"<title>(.*?)</title>", body, re.S)
                classes = Counter(re.findall(r'class="([^"]{3,40})"', body)).most_common(12)
                print(f"      title: {title.group(1)[:80] if title else '-'}; classes: "
                      f"{[c for c, _ in classes]}; start: {body[:200]!r}")
        except Exception as err:            # a report: show every kind of failure
            print(f"  {name}: FAILED {type(err).__name__}: {str(err)[:100]}")
    return 0 if hits >= len(QUESTIONS) // 2 else 1


if __name__ == "__main__":
    sys.exit(main())
