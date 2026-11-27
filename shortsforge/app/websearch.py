"""
websearch.py - lets the assistant look things up on the internet (OFF unless you switch it on).

WHY it exists:
    An offline model knows nothing recent and cannot check facts.

HOW it works:
    - With no key: searches Wikipedia (free, official; good for facts, NOT for news).
    - With a Tavily key (tavily.com, free plan with a monthly limit): searches the whole web.
    - Only your search words are sent out. We return titles, links and short extracts.
    - For a better answer the assistant may then OPEN one of those result pages (fetch_page).
      Only public web addresses are allowed, never your own PC or home network.
    - Web text is written by strangers, so assistant.py will not let the AI change anything
      (clips, memory) after it has read search results in the same message.

HOW TO IMPROVE:
    - Add other search services, or Wikipedia in your own language.
"""

import ipaddress
import json
import re
import socket
import urllib.error
import urllib.parse
import urllib.request
from html import unescape

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


# ---------------------------------------------------------------------------
# Opening one result page
# WHY: a 700-letter extract is often not enough to answer correctly.
# SAFETY: a web address could point at your own PC or router, so every address (also after a
# redirect) must resolve to public internet addresses only.
# HOW TO IMPROVE: read PDF pages too; keep only the paragraphs close to the question.
# ---------------------------------------------------------------------------
PAGE_LIMIT = 1_500_000
PAGE_TEXT = 5000


def check_public(url: str) -> None:
    """Raise ValueError unless the address is an ordinary public web page."""
    parts = urllib.parse.urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname or parts.username:
        raise ValueError("Only ordinary web addresses can be opened.")
    try:
        found = socket.getaddrinfo(parts.hostname, parts.port or 443, proto=socket.IPPROTO_TCP)
    except (OSError, ValueError) as err:
        raise ValueError("That website could not be found.") from err
    for item in found:
        if not ipaddress.ip_address(item[4][0].split("%")[0]).is_global:
            raise ValueError("Addresses on this PC or home network cannot be opened.")


class _CheckedRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        check_public(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def page_text(html: str) -> str:
    """The readable words of a web page."""
    html = re.sub(r"(?is)<(script|style|noscript|svg|nav|header|footer)\b.*?</\1>", " ", html)
    html = re.sub(r"(?i)</(p|div|li|h\d|tr)>|<br\s*/?>", "\n", html)
    text = unescape(re.sub(r"<[^>]+>", " ", html))
    lines = (" ".join(line.split()) for line in text.splitlines())
    return "\n".join(line for line in lines if len(line) > 2)[:PAGE_TEXT]


def fetch_page(url: str) -> dict:
    check_public(url)
    opener = urllib.request.build_opener(_CheckedRedirect)
    request = urllib.request.Request(url, headers={"User-Agent": AGENT, "Accept": "text/html,text/plain"})
    try:
        with opener.open(request, timeout=20) as response:
            kind = response.headers.get_content_type()
            if not kind.startswith("text/"):
                raise ValueError("That link is not a text page.")
            raw = response.read(PAGE_LIMIT)
            charset = response.headers.get_content_charset() or "utf-8"
    except (urllib.error.URLError, TimeoutError, OSError) as err:
        raise ValueError("The page could not be opened.") from err
    try:
        body = raw.decode(charset, "replace")
    except LookupError:
        body = raw.decode("utf-8", "replace")
    return {"url": url, "text": page_text(body) if kind == "text/html" else body[:PAGE_TEXT]}


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
