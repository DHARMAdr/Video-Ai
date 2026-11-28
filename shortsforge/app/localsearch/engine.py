"""
engine.py - runs a whole search.

WHY: one place that decides what to ask, keeps it fast and survives failures.
HOW:
    1. understand the question (query.py)
    2. ask the services at the same time (sources.py); a failing one is skipped
    3. if little came back, ask again with a shorter wording
    4. mix and order the links (rank.py)
    5. open the best few pages and keep the paragraphs that answer (like Tavily's "content")
    6. remember the answer for 10 minutes, so repeating a question asks nobody again
SAFETY: result pages are opened with websearch.fetch_page, which refuses addresses on this
    PC or home network, also after redirects.
HOW TO IMPROVE: let you choose which services are used; keep the memory between restarts.
"""

import time
from concurrent.futures import ThreadPoolExecutor, wait

from . import query, rank, sources

KEEP_SECONDS = 600
SEARCH_TIME = 12            # seconds to wait for the services
PAGE_TIME = 10              # seconds to wait for the pages
OPEN_PAGES = 6
RESULTS = 5
_memory = {}


def _in_parallel(jobs: dict, seconds: float) -> dict:
    """Run {name: function} together; return the ones that finished without an error."""
    if not jobs:
        return {}
    pool = ThreadPoolExecutor(max_workers=min(8, len(jobs)))
    futures = {pool.submit(function): name for name, function in jobs.items()}
    done, _ = wait(futures, timeout=seconds)
    pool.shutdown(wait=False, cancel_futures=True)
    return {futures[f]: f.result() for f in done if f.exception() is None}


def _ask(names: list, text: str, download, keywords: str = "") -> dict:
    def job(name):
        build, read = sources.SOURCES[name][:2]
        wording = keywords if keywords and name in sources.KEYWORD_SOURCES else text
        return lambda: read(download(build(wording)))

    return _in_parallel({name: job(name) for name in names}, SEARCH_TIME)


def gather(understood: dict, download) -> tuple:
    """Return ([(weight, items)], names of the services that answered with results)."""
    games = {f"{word}-wiki" for word in understood["keywords"] if word in sources.GAME_WIKIS}
    names = [n for n, s in sources.SOURCES.items()
             if s[3] == "web" or n in games or (s[3] != "wiki" and understood.get(s[3]))]
    lists, used = [], []

    def add(answers, factor=1.0):
        for name, items in answers.items():
            if items:
                weight = sources.SOURCES[name][2] if name in sources.SOURCES else 1.0
                lists.append((weight * factor, items))
                used.append(name)

    add(_ask(names, understood["text"], download, " ".join(understood["keywords"])))
    if "duckduckgo" not in used:
        name, build, read = sources.BACKUP
        add(_in_parallel({name: lambda: read(download(build(understood["text"])))}, SEARCH_TIME))
    # A second wording (just the key words) finds pages a whole sentence misses.
    for number, variant in enumerate(understood["variants"][1:]):
        if number and sum(len(items) for _, items in lists) >= 12:
            break
        add(_ask([n for n in names if sources.SOURCES[n][3] == "web"
                  and n not in sources.KEYWORD_SOURCES], variant, download), 0.8)
    return lists, sorted(set(used))


def _wiki_page(url: str, download):
    """Wikipedia text through its official interface (its web pages limit programs)."""
    title = sources.wiki_title(url)
    return sources.read_wiki_page(download(sources.wiki_address(title))) if title else None


def _page(url: str, fetch, download) -> dict:
    text = _wiki_page(url, download)
    if text:
        return {"text": text}
    answers = sources.stack_answers(url)
    if answers:
        return {"text": sources.read_stack_answers(download(answers))}
    return fetch(url)


def read_pages(results: list, keywords: list, fetch, download) -> None:
    """Replace short snippets with the best paragraphs of the top pages."""
    jobs = {r["url"]: (lambda url=r["url"]: _page(url, fetch, download))
            for r in results[:OPEN_PAGES]}
    pages = _in_parallel(jobs, PAGE_TIME)
    for result in results:
        page = pages.get(result["url"])
        found = rank.best_passages(keywords, page.get("text", ""),
                                   intro="wiki" in result["url"]) if page else []
        if found:
            result["text"] = " ... ".join(found)
            result["read"] = True
            words = rank.tokens(" ".join(found))
            result["score"] = round(result["score"] + 0.25 * rank.coverage(keywords, words), 4)


def search(question: str, download=None, fetch=None) -> dict:
    """Return {"source": ..., "results": [{title, url, extract}]}."""
    from .. import websearch

    understood = query.understand(question)
    if not understood["text"]:
        raise ValueError("Give something to search for.")
    live = download is None and fetch is None
    key = understood["text"].lower()
    if live and key in _memory and time.time() - _memory[key][0] < KEEP_SECONDS:
        return dict(_memory[key][1])
    download = download or sources.download
    lists, used = gather(understood, download)
    if not lists:
        raise ValueError("Cannot reach the internet for searching, or every search service "
                         "refused. Try again in a few minutes.")
    results = rank.fuse(lists, understood["keywords"])
    read_pages(results, understood["keywords"],
               fetch or (lambda url: websearch.fetch_page(url, limit=30000)), download)
    results.sort(key=lambda r: -r["score"])
    answer = {"source": "web (built-in search: " + ", ".join(used) + ")",
              "results": [{"title": r["title"], "url": r["url"],
                           "extract": r["text"][:1200 if r.get("read") else 700]}
                          for r in results[:RESULTS]]}
    if live:
        if len(_memory) > 50:
            _memory.clear()
        _memory[key] = (time.time(), answer)
    return dict(answer)
