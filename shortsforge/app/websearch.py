"""
websearch.py - lets the assistant look things up on the internet (OFF unless you switch it on).

WHY it exists:
    An offline model knows nothing recent and cannot check facts.

HOW it works:
    - With no key: searches Wikipedia (free, official; good for facts, NOT for news).
    - With a Tavily key (tavily.com, free plan with a monthly limit): searches the whole web.
    - Only your search words are sent out. We return titles, links and short extracts; we never
      open the pages themselves.
    - Web text is written by strangers, so assistant.py will not let the AI change anything
      (clips, memory) after it has read search results in the same message.

HOW TO IMPROVE:
    - Add other search services, or Wikipedia in your own language.
"""

import json
import urllib.error
import urllib.parse
import urllib.request

WIKI_URL = "https://en.wikipedia.org/w/api.php"
TAVILY_URL = "https://api.tavily.com/search"
AGENT = "ShortsForge (https://github.com/DHARMAdr/Video-Ai)"


def _get_json(request) -> dict:
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.loads(response.read(2_000_000).decode("utf-8"))
    except urllib.error.HTTPError as err:
        if err.code in (401, 403):
            raise ValueError("The search service rejected the key. Check it in Settings.") from err
        if err.code in (429, 432, 433):
            raise ValueError("The search limit is used up for now. Try again later.") from err
        raise ValueError(f"The search service returned an error ({err.code}).") from err
    except (urllib.error.URLError, TimeoutError, OSError) as err:
        raise ValueError("Cannot reach the internet for searching.") from err
    except ValueError as err:
        raise ValueError("The search answer could not be read.") from err


def _item(title, url, text) -> dict:
    return {"title": str(title)[:200], "url": str(url)[:500],
            "extract": " ".join(str(text).split())[:700]}


def search(query: str, api_key: str = "") -> dict:
    """Return {"source": ..., "results": [{title, url, extract}]}."""
    query = " ".join(str(query or "").split())[:200]
    if not query:
        raise ValueError("Give something to search for.")
    if api_key:
        body = {"query": query, "max_results": 5, "search_depth": "basic"}
        data = _get_json(urllib.request.Request(
            TAVILY_URL, data=json.dumps(body).encode(), method="POST",
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}",
                     "User-Agent": AGENT}))
        found = [_item(r.get("title"), r.get("url"), r.get("content"))
                 for r in data.get("results") or []]
        return {"source": "web (Tavily)", "results": found[:5]}
    params = {"action": "query", "format": "json", "generator": "search", "gsrsearch": query,
              "gsrlimit": 4, "prop": "extracts", "exintro": 1, "explaintext": 1, "exlimit": 4}
    data = _get_json(urllib.request.Request(WIKI_URL + "?" + urllib.parse.urlencode(params),
                                            headers={"User-Agent": AGENT}))
    pages = sorted((data.get("query") or {}).get("pages", {}).values(),
                   key=lambda p: p.get("index", 99))
    found = [_item(p.get("title"), "https://en.wikipedia.org/wiki/" +
                   urllib.parse.quote(str(p.get("title", "")).replace(" ", "_")),
                   p.get("extract", "")) for p in pages]
    return {"source": "Wikipedia only (not the whole web, may not have recent news)",
            "results": found}
