"""
Tests for the built-in search. No internet is used: small made-up result pages stand in for
the services, so these tests check OUR reading and ordering, not the services themselves
(packaging/test_search.py does that, with the real internet).
"""

import base64
import datetime
import json
import unittest

from shortsforge.app.localsearch import engine, query, rank, sources

DDG = '''<div><a rel="nofollow" class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.org%2Fjett&amp;rut=x">Jett <b>guide</b></a>
<a class="result__snippet" href="x">Jett is a Korean agent.</a></div>
<div><a class="result__a" href="https://duckduckgo.com/y.js?ad=1">Advert</a></div>'''
LITE = '''<table><tr><td><a rel="nofollow" href="https://example.org/a" class='result-link'>A page</a></td></tr>
<tr><td class='result-snippet'>About A.</td></tr></table>'''
BING_TARGET = base64.urlsafe_b64encode(b"https://example.org/jett?utm_source=b").decode().rstrip("=")
BING = f'''<ol><li class="b_algo"><h2><a href="https://www.bing.com/ck/a?x=1&amp;u=a1{BING_TARGET}">Jett page</a></h2>
<div><p>Jett uses wind.</p></div></li></ol>'''
NEWS = '''<rss><channel><item><title>Patch out</title>
<link>https://news.example/patch</link>
<pubDate>Fri, 27 Nov 2026 10:00:00 GMT</pubDate><source>Example News</source></item></channel></rss>'''
MOJEEK = '''<ul class="results-standard"><li class="r1"><a title="x" class="ob" href="https://m.example/p">m</a>
<h2><a class="title" href="https://m.example/p">Mojeek hit</a></h2><p class="s">Text.</p></li></ul>'''


class Readers(unittest.TestCase):
    def test_each_page_layout_is_read(self):
        self.assertEqual(sources.read_ddg(DDG), [{"title": "Jett guide",
                         "url": "https://example.org/jett", "text": "Jett is a Korean agent."}])
        self.assertEqual(sources.read_ddg_lite(LITE)[0]["url"], "https://example.org/a")
        self.assertEqual(sources.read_bing(BING)[0]["url"],
                         "https://example.org/jett?utm_source=b")
        self.assertEqual(sources.read_news(NEWS)[0]["text"], "Fri, 27 Nov 2026 Example News")
        self.assertIn("/questions/5/answers",
                      sources.stack_answers("https://stackoverflow.com/q/5"))
        self.assertIsNone(sources.stack_answers("https://example.org/q/5"))
        self.assertEqual(sources.read_stack_answers('{"items": [{"body": "<p>use setpts</p>"}]}'),
                         "use setpts")
        self.assertEqual(sources.read_mojeek(MOJEEK)[0]["title"], "Mojeek hit")
        stack = {"items": [{"title": "t", "link": "https://s.example/q", "excerpt": "e"}]}
        self.assertEqual(len(sources.read_stack(json.dumps(stack))), 1)
        self.assertEqual(sources.read_github('{"items": []}'), [])

    def test_yahoo_stack_and_game_wiki(self):
        yahoo = ('<div class="dd algo algo-sr"><div class="compTitle"><a href="https://r.search.'
                 'yahoo.com/x/RU=https%3a%2f%2fexample.org%2fy/RK=2/RS=z"><h3>Yahoo hit</h3></a>'
                 '</div><div class="compText"><p>Words.</p></div></div>')
        self.assertEqual(sources.read_yahoo(yahoo), [{"title": "Yahoo hit",
                         "url": "https://example.org/y", "text": "Words."}])
        stack = {"items": [{"title": "t", "question_id": 5, "excerpt": "e"}]}
        self.assertEqual(sources.read_stack(json.dumps(stack))[0]["url"],
                         "https://stackoverflow.com/q/5")
        wiki = {"query": {"search": [{"title": "Jett (agent)", "snippet": "<span>x</span>"}]}}
        self.assertEqual(sources.SOURCES["valorant-wiki"][1](json.dumps(wiki))[0]["url"],
                         "https://valorant.fandom.com/wiki/Jett_%28agent%29")

    def test_unsafe_links_are_dropped(self):
        page = '<a class="result__a" href="javascript:alert(1)">bad</a>'
        self.assertEqual(sources.read_ddg(page), [])


class Understanding(unittest.TestCase):
    def test_filler_news_and_code(self):
        found = query.understand("Can you tell me what is the latest Valorant patch?",
                                 datetime.date(2026, 11, 27))
        self.assertEqual(found["text"], "what is the latest Valorant patch")
        self.assertTrue(found["news"])
        self.assertIn("latest valorant patch 2026", found["variants"])
        self.assertTrue(query.understand("ffmpeg error invalid argument")["code"])
        self.assertFalse(query.understand("who painted the ceiling")["news"])


class Ranking(unittest.TestCase):
    def test_agreement_wins_and_one_site_cannot_fill_the_list(self):
        item = lambda url, title: {"url": url, "title": title, "text": "jett agent"}
        one = [item(f"https://big.example/{i}", "jett") for i in range(5)]
        one.append(item("https://www.shared.example/jett/", "jett"))
        two = [item("https://shared.example/jett?utm_source=x", "jett")]
        found = rank.fuse([(1.0, one), (1.0, two)], ["jett"])
        self.assertIn("shared.example", found[0]["url"])
        self.assertEqual(sum("big.example" in r["url"] for r in found), 2)

    def test_the_answering_paragraph_is_chosen(self):
        page = "\n".join(["Home About Contact Login"] +
                         ["We like many things on this website and write about them often."] * 8 +
                         ["The Eiffel Tower is 330 metres tall after the 2022 antenna change."])
        best = rank.best_passages(["eiffel", "tower", "tall"], page, 1)
        self.assertIn("330 metres", best[0])


class WholeSearch(unittest.TestCase):
    def download(self, url):
        if "html.duckduckgo" in url:
            return DDG
        if "bing.com/search" in url:
            return BING
        raise OSError("this service is down")

    def test_failing_services_are_skipped_and_pages_are_read(self):
        fetch = lambda url: {"text": "Jett is a duelist agent released in Valorant in 2020. " * 2}
        found = engine.search("who is jett in valorant", self.download, fetch)
        self.assertIn("duckduckgo", found["source"])
        self.assertIn("bing", found["source"])
        self.assertIn("duelist", found["results"][0]["extract"])

    def test_pages_that_cannot_be_opened_keep_their_snippet(self):
        def fetch(url):
            raise ValueError("no")

        found = engine.search("jett", self.download, fetch)
        self.assertIn("Jett", found["results"][0]["extract"])

    def test_everything_down(self):
        def down(url):
            raise OSError("offline")

        with self.assertRaisesRegex(ValueError, "Cannot reach"):
            engine.search("jett", down, down)


if __name__ == "__main__":
    unittest.main()
