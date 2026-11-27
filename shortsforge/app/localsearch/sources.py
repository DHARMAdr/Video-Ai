"""
sources.py - the free search services we ask, and how to read their answers.

WHY several: no single free service is reliable. One may be down, may block programs, or may
    simply miss the page. Asking several and comparing is what makes the answer dependable.
HOW: each source is two small things: the web address to ask, and a "reader" that turns the
    answer into [{title, url, text}]. A source that fails gives an error that engine.py skips.
SAFETY: these are fixed, well-known addresses. Only your search words are sent to them.
HOW TO IMPROVE: add a source = add one URL builder, one reader and one line in SOURCES.
    If a service changes its page layout, only its reader needs fixing.
"""

import base64
import json
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from html import unescape

# Search pages refuse unknown programs, so we ask like an ordinary browser would.
BROWSER = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
           "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
LIMIT = 2_000_000


def download(url: str, timeout: float = 10) -> str:
    request = urllib.request.Request(url, headers={
        "User-Agent": BROWSER, "Accept": "text/html,application/json,application/xml",
        "Accept-Language": "en-US,en;q=0.8"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read(LIMIT).decode("utf-8", "replace")


def plain(html: str) -> str:
    """Remove tags and extra spaces."""
    return " ".join(unescape(re.sub(r"<[^>]+>", "", str(html or ""))).split())


def _web_link(url: str) -> str:
    url = unescape(str(url or "").strip())
    if url.startswith("//"):
        url = "https:" + url
    return url if url.startswith(("http://", "https://")) else ""


def _item(title, url, text) -> dict:
    return {"title": plain(title)[:200], "url": _web_link(url)[:500], "text": plain(text)[:700]}


def _keep(items) -> list:
    return [i for i in items if i["url"] and i["title"]][:10]


# -- DuckDuckGo (two page layouts) ---------------------------------------------
def _unwrap_ddg(link: str) -> str:
    """DuckDuckGo wraps links as /l/?uddg=<real address>. Adverts use y.js and are dropped."""
    link = _web_link(unescape(link))
    parts = urllib.parse.urlsplit(link)
    if parts.hostname and parts.hostname.endswith("duckduckgo.com"):
        real = urllib.parse.parse_qs(parts.query).get("uddg")
        return _web_link(real[0]) if real else ""
    return link


def read_ddg(html: str) -> list:
    out = []
    # Cut the page at every result title; the snippet belongs to the title before it.
    for block in re.split(r'(?=<a[^>]+class="[^"]*result__a)', html)[1:]:
        head = re.match(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', block, re.S)
        if not head:
            continue
        snippet = re.search(r'class="[^"]*result__snippet[^"]*"[^>]*>(.*?)</(a|div)>', block, re.S)
        out.append(_item(head.group(2), _unwrap_ddg(head.group(1)),
                         snippet.group(1) if snippet else ""))
    return _keep(out)


def read_ddg_lite(html: str) -> list:
    out = []
    for block in re.split(r"(?=<a[^>]+class=['\"]result-link)", html)[1:]:
        head = re.match(r"<a[^>]*>(.*?)</a>", block, re.S)
        href = re.search(r'href="([^"]+)"', block.split(">", 1)[0])
        if not head or not href:
            continue
        snippet = re.search(r"class=['\"]result-snippet['\"][^>]*>(.*?)</td>", block, re.S)
        out.append(_item(head.group(1), _unwrap_ddg(href.group(1)),
                         snippet.group(1) if snippet else ""))
    return _keep(out)


# -- Bing ----------------------------------------------------------------------
def _unwrap_bing(link: str) -> str:
    """Bing may wrap links as /ck/a?...&u=a1<base64 of the real address>."""
    link = _web_link(link)
    parts = urllib.parse.urlsplit(link)
    if parts.hostname and parts.hostname.endswith("bing.com") and parts.path.startswith("/ck/"):
        packed = urllib.parse.parse_qs(parts.query).get("u", [""])[0][2:]
        try:
            raw = base64.urlsafe_b64decode(packed + "=" * (-len(packed) % 4))
            return _web_link(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return ""
    return link


def read_bing(html: str) -> list:
    out = []
    for block in re.split(r'(?=<li class="b_algo)', html)[1:]:
        head = re.search(r'<h2[^>]*>\s*<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', block, re.S)
        if not head:
            continue
        snippet = re.search(r"<p[^>]*>(.*?)</p>", block, re.S)
        out.append(_item(head.group(2), _unwrap_bing(unescape(head.group(1))),
                         snippet.group(1) if snippet else ""))
    return _keep(out)


def read_bing_news(xml: str) -> list:
    out = []
    for item in ET.fromstring(xml).iter("item"):
        link = item.findtext("link") or ""
        parts = urllib.parse.urlsplit(link)
        real = urllib.parse.parse_qs(parts.query).get("url")        # unwrap the click counter
        date = (item.findtext("pubDate") or "")[:16]
        out.append(_item(item.findtext("title"), real[0] if real else link,
                         f"{date} {item.findtext('description') or ''}"))
    return _keep(out)


# -- Mojeek (an independent index) ---------------------------------------------
def read_mojeek(html: str) -> list:
    out = []
    for block in re.split(r"(?=<li[^>]*>\s*(?:<!--[^>]*-->)?\s*<a[^>]+class=\"ob\")", html)[1:]:
        head = re.search(r'<h2>\s*<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', block, re.S)
        if not head:
            continue
        snippet = re.search(r'<p class="s">(.*?)</p>', block, re.S)
        out.append(_item(head.group(2), head.group(1), snippet.group(1) if snippet else ""))
    return _keep(out)


# -- Official, free programming interfaces --------------------------------------
def read_wikipedia(body: str) -> list:
    pages = (json.loads(body).get("query") or {}).get("pages", {}).values()
    return _keep([_item(p.get("title"), "https://en.wikipedia.org/wiki/" +
                        urllib.parse.quote(str(p.get("title", "")).replace(" ", "_")),
                        p.get("extract", ""))
                  for p in sorted(pages, key=lambda p: p.get("index", 99))])


def read_stack(body: str) -> list:
    return _keep([_item(r.get("title"), r.get("link"),
                        f"Stack Overflow, {r.get('answer_count', 0)} answers. "
                        f"{r.get('excerpt', '')}") for r in json.loads(body).get("items", [])])


def read_github(body: str) -> list:
    return _keep([_item(r.get("full_name"), r.get("html_url"),
                        f"{r.get('description') or ''} ({r.get('stargazers_count', 0)} stars)")
                  for r in json.loads(body).get("items", [])])


def _url(base: str, **params) -> str:
    return base + "?" + urllib.parse.urlencode(params)


# name: (address builder, reader, trust weight, when to ask: "web", "news", "code")
SOURCES = {
    "duckduckgo": (lambda q: _url("https://html.duckduckgo.com/html/", q=q),
                   read_ddg, 1.0, "web"),
    "bing": (lambda q: _url("https://www.bing.com/search", q=q, setlang="en"),
             read_bing, 0.9, "web"),
    "mojeek": (lambda q: _url("https://www.mojeek.com/search", q=q), read_mojeek, 0.7, "web"),
    "wikipedia": (lambda q: _url(
        "https://en.wikipedia.org/w/api.php", action="query", format="json", generator="search",
        gsrsearch=q, gsrlimit=4, prop="extracts", exintro=1, explaintext=1, exlimit=4),
        read_wikipedia, 0.8, "web"),
    "news": (lambda q: _url("https://www.bing.com/news/search", q=q, format="rss"),
             read_bing_news, 0.9, "news"),
    "stackoverflow": (lambda q: _url(
        "https://api.stackexchange.com/2.3/search/excerpts", order="desc", sort="relevance",
        q=q, site="stackoverflow", pagesize=6), read_stack, 0.8, "code"),
    "github": (lambda q: _url("https://api.github.com/search/repositories", q=q, per_page=6),
               read_github, 0.6, "code"),
}
# Used only when "duckduckgo" gives nothing (it is the same service in a simpler page).
BACKUP = ("duckduckgo-lite",
          lambda q: _url("https://lite.duckduckgo.com/lite/", q=q), read_ddg_lite)
