"""
websearch.py - lets the assistant look things up on the internet (OFF unless you switch it on).

WHY it exists:
    An offline model knows nothing recent and cannot check facts.

HOW it works:
    - With no key: the built-in search (localsearch folder) asks several free services,
      opens the best pages and keeps the paragraphs that answer.
    - With a Tavily key (tavily.com, free plan with a monthly limit): asks Tavily, and
      falls back to the built-in search if Tavily fails.
    - Search services get your search words; websites whose pages are opened see your
      internet address, like when you visit them yourself.
    - For a better answer the assistant may then OPEN one of those result pages (fetch_page).
      Only public web addresses are allowed, never your own PC or home network.
    - Web text is written by strangers, so assistant.py will not let the AI change anything
      (clips, memory) after it has read search results in the same message.

HOW TO IMPROVE:
    - See localsearch/ to add search services.
"""

import ipaddress
import json
import re
import socket
import urllib.error
import urllib.parse
import urllib.request
from html import unescape

from . import localsearch

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


def page_text(html: str, limit: int = PAGE_TEXT) -> str:
    """The readable words of a web page."""
    html = re.sub(r"(?is)<(script|style|noscript|svg|nav|header|footer)\b.*?</\1>", " ", html)
    html = re.sub(r"(?i)</(p|div|li|h\d|tr)>|<br\s*/?>", "\n", html)
    text = unescape(re.sub(r"<[^>]+>", " ", html))
    lines = (" ".join(line.split()) for line in text.splitlines())
    return "\n".join(line for line in lines if len(line) > 2)[:limit]


def fetch_page(url: str, limit: int = PAGE_TEXT) -> dict:
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
    return {"url": url, "text": page_text(body, limit) if kind == "text/html" else body[:limit]}


def _item(title, url, text) -> dict:
    return {"title": str(title)[:200], "url": str(url)[:500],
            "extract": " ".join(str(text).split())[:700]}


def search(query: str, api_key: str = "") -> dict:
    """Return {"source": ..., "results": [{title, url, extract}]}.

    With a Tavily key, Tavily is asked; if it fails, the built-in search takes over.
    """
    query = " ".join(str(query or "").split())[:200]
    if not query:
        raise ValueError("Give something to search for.")
    if not api_key:
        return localsearch.search(query)
    body = {"query": query, "max_results": 5, "search_depth": "basic"}
    try:
        data = _get_json(urllib.request.Request(
            TAVILY_URL, data=json.dumps(body).encode(), method="POST",
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}",
                     "User-Agent": AGENT}))
    except ValueError as err:
        result = localsearch.search(query)
        result["note"] = f"Tavily was not used: {err}"
        return result
    found = [_item(r.get("title"), r.get("url"), r.get("content"))
             for r in data.get("results") or []]
    return {"source": "web (Tavily)", "results": found[:5]}
