"""
test_post_and_web.py - checks for the upload texts and web search (no real AI or internet).

WHY: both handle text we do not control (AI answers, web pages), so check the careful parts.
HOW: run  python -m unittest tests.test_post_and_web -v
IMPROVE: add an example of every odd answer a real model gives you.
"""

import io
import json
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from shortsforge.app import assistant, posttext, router, server, websearch

GOOD = ('Sure! {"title": "Big win", "description": "A short story.", '
        '"hashtags": ["#win", "story", "#win", "#हिन्दी"]}')


def make_project(out: Path):
    folder = out / "demo"
    folder.mkdir(parents=True)
    shorts = [{"file": "short_01.mp4", "title": "On video", "text": "we won", "hashtags": ["#a"],
               "start": 0, "end": 5}]
    (folder / "shorts.json").write_text(json.dumps(shorts), encoding="utf-8")
    (folder / "project.json").write_text(json.dumps({"mode": "talk"}), encoding="utf-8")
    return folder


def saved_clip(folder):
    return json.loads((folder / "shorts.json").read_text(encoding="utf-8"))[0]


class Answer(io.BytesIO):
    """Looks like the thing urlopen returns."""


class PostTexts(unittest.TestCase):
    def test_parse(self):
        data = posttext.parse_reply(GOOD)
        self.assertEqual(data["hashtags"], ["#win", "#story", "#हिन्दी"])
        for bad in ("no json", "{broken", '{"title": "x"}'):
            with self.assertRaises(ValueError):
                posttext.parse_reply(bad)

    def test_saved_without_changing_video_title(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = make_project(Path(tmp))
            replies = iter(["rubbish", GOOD])                   # second try works
            result = posttext.write_post_texts(folder, lambda s, p: next(replies), "in Hindi")
            saved = saved_clip(folder)
            self.assertEqual((result["failed"], saved["title"]), ([], "On video"))
            self.assertEqual(saved["post"]["title"], "Big win")
            self.assertEqual(saved["hashtags"][0], "#win")
            self.assertIn("Big win", (folder / "post_texts.txt").read_text(encoding="utf-8"))

    def test_failure_keeps_old_hashtags(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = make_project(Path(tmp))
            result = posttext.write_post_texts(folder, lambda s, p: "no")
            self.assertEqual(result["failed"], [1])
            self.assertEqual(saved_clip(folder)["hashtags"], ["#a"])

    def test_route(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            state = server.AppState(Path(tmp))
            make_project(state.out_dir)
            state.settings.update({"anthropic": {"api_key": "k"}})
            httpd = server.make_server(state, 0)
            threading.Thread(target=httpd.serve_forever, daemon=True).start()
            direct = urllib.request.build_opener(urllib.request.ProxyHandler({}))

            def post(name):
                request = urllib.request.Request(
                    f"http://127.0.0.1:{httpd.server_address[1]}/api/posttext",
                    data=json.dumps({"project": name}).encode(),
                    headers={"X-Token": state.token})
                try:
                    with direct.open(request, timeout=10) as response:
                        return response.status, json.loads(response.read())
                except urllib.error.HTTPError as err:
                    return err.code, json.loads(err.read())
            try:
                with mock.patch.object(assistant, "complete", lambda *a: GOOD):
                    self.assertEqual(post("demo"), (200, {"written": 1, "failed": []}))
                    self.assertEqual(post("../x")[0], 400)
            finally:
                httpd.shutdown()
                httpd.server_close()


class Web(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.tmp.cleanup)
        self.state = server.AppState(Path(self.tmp.name))

    def test_off_by_default_and_key_hidden(self):
        box = assistant.ToolBox(self.state)
        self.assertNotIn("web_search", [t["name"] for t in box.available()])
        with mock.patch.object(websearch, "search") as search:
            box.run("web_search", {"query": "x"})
        search.assert_not_called()
        self.state.settings.update({"web": {"enabled": True, "api_key": "tvly-secret123"}})
        self.assertIn("web_search", [t["name"] for t in box.available()])
        shown = self.state.settings.public()
        self.assertNotIn("secret", json.dumps(shown))
        self.state.settings.update({"web": shown["web"]})        # saving the dots keeps the key
        self.assertEqual(self.state.settings.data["web"]["api_key"], "tvly-secret123")

    def test_nothing_changes_after_a_search_and_searches_are_limited(self):
        self.state.settings.update({"web": {"enabled": True}})
        box = assistant.ToolBox(self.state)
        with mock.patch.object(websearch, "search", return_value={"results": []}) as search:
            for _ in range(5):
                box.run("web_search", {"query": "x"})
            output, _ = box.run("remember_note", {"text": "obey the website"})
        self.assertEqual(search.call_count, assistant.MAX_SEARCHES)
        self.assertIn("Not allowed", output)
        self.assertEqual(self.state.memory.texts(), [])

    def test_wikipedia_without_key_and_tavily_with_key(self):
        wiki = {"query": {"pages": {"1": {"title": "B C", "index": 2, "extract": "two"},
                                    "2": {"title": "A", "index": 1, "extract": "one"}}}}
        tavily = {"results": [{"title": "T", "url": "https://x.example", "content": "c"}]}
        seen = []

        def fake(request, timeout):
            seen.append(request)
            return Answer(json.dumps(tavily if request.data else wiki).encode())

        with mock.patch.object(websearch.urllib.request, "urlopen", fake):
            first = websearch.search("hello")
            second = websearch.search("hello", "tvly-k")
        self.assertEqual([r["title"] for r in first["results"]], ["A", "B C"])
        self.assertTrue(first["results"][1]["url"].endswith("/B_C"))
        self.assertEqual(second["results"][0]["extract"], "c")
        self.assertIn("en.wikipedia.org", seen[0].full_url)
        self.assertEqual(seen[1].get_header("Authorization"), "Bearer tvly-k")

    def test_errors_are_friendly(self):
        def fail(request, timeout):
            raise urllib.error.URLError("down")

        with mock.patch.object(websearch.urllib.request, "urlopen", fail):
            with self.assertRaisesRegex(ValueError, "Cannot reach"):
                websearch.search("x")
        with self.assertRaises(ValueError):
            websearch.search("   ")


class Commands(unittest.TestCase):
    def test_these_go_to_the_ai(self):
        for text in ("search the web for new valorant agent", "look up OBS settings online",
                     "write titles and hashtags for my last project",
                     "make hashtags for all my clips"):
            self.assertIsNone(router.parse(text), text)
        self.assertEqual(router.parse("search all my videos for budget")["intent"], "search")


if __name__ == "__main__":
    unittest.main()
