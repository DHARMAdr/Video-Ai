"""
test_router.py - the "exam" for the built-in command understanding (no AI involved).

WHY it exists:
    Each row below is a sentence a person might type and the answer we expect. When I (or you)
    improve router.py, run this: if a previously-working sentence breaks, a test fails.
    To teach the router a new phrasing, add a row here FIRST, then fix router.py until it passes.
HOW it works:
    Run:  python -m unittest tests.test_router -v
HOW TO IMPROVE:
    Keep adding real sentences from the thumbs-down feedback file (_feedback.jsonl).
"""

import json
import shutil
import sys
import tempfile
import threading
import unittest
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from shortsforge.app import retrieval, router, server

# (sentence, expected intent, extra fields that must match)
CASES = [
    ("help", "help", {}),
    ("What can you do?", "help", {}),
    ("how do I use this", "help", {}),
    ("make 5 shorts from my last video", "make", {"count": 5, "mode": "talk"}),
    ("Make three reels from my latest podcast", "make", {"count": 3}),
    ("create shorts from https://youtu.be/abc123", "make", {"source": "https://youtu.be/abc123"}),
    ("make valorant shorts with at least 2 kills", "make", {"mode": "game", "min_kills": 2}),
    ("cut my best kills from the gameplay", "make", {"mode": "game"}),
    ("make 4 highlights, blur background", "make", {"count": 4, "layout": "blur"}),
    ("make shorts without captions", "make", {"captions": False}),
    ("trim clip 2 to 0:40-1:10", "trim", {"clip": 2, "start": 40, "end": 70}),
    ("change short 3 to start at 1:05 and end at 1:40", "trim", {"clip": 3, "start": 65, "end": 100}),
    ("set the second clip from 30s to 55s", "trim", {"clip": 2, "start": 30, "end": 55}),
    ("shorten clip 1 to 12-30", "trim", {"clip": 1, "start": 12, "end": 30}),
    ("trim the last clip to 2:00-2:30", "trim", {"clip": -1, "start": 120, "end": 150}),
    ("add a clip from 1:05 to 1:40 called Big moment", "add", {"start": 65, "end": 100, "title": "Big moment"}),
    ("make a new clip from 2m to 2m30s", "add", {"start": 120, "end": 150}),
    ("find where I talk about pricing", "search", {"query": "pricing", "scope": "one"}),
    ("search all my videos for budget", "search", {"query": "budget", "scope": "all"}),
    ('where did I say "free trial"', "search", {"query": "free trial"}),
    ("when do I mention the launch date", "search", {"query": "the launch date"}),
    ("show my projects", "show", {"all": True}),
    ("show clips", "show", {}),
    ("list my videos", "show", {}),
    ("projects", "show", {}),
    ("status", "status", {}),
    ("is it done?", "status", {}),
    ("remember that I prefer the blur layout", "remember", {"text": "I prefer the blur layout"}),
    ("what do you remember", "recall", {}),
    ("forget everything", "forget", {}),
]

NOT_COMMANDS = [                       # these must go to the AI, not be hijacked by a rule
    "hi", "write me a funny title for a cooking short", "give me 10 hashtag ideas for gaming shorts",
    "explain how viral videos work", "what is a good length for a short?", "thanks!",
    "write a script about pasta", "how do I get more subscribers",
]


class Parse(unittest.TestCase):
    def test_commands(self):
        for text, intent, extra in CASES:
            got = router.parse(text)
            self.assertIsNotNone(got, text)
            self.assertEqual(got["intent"], intent, text)
            for key, value in extra.items():
                self.assertEqual(got.get(key), value, f"{text!r} field {key}")

    def test_open_questions_go_to_the_ai(self):
        for text in NOT_COMMANDS:
            self.assertIsNone(router.parse(text), text)

    def test_parse_time(self):
        for text, seconds in [("1:05", 65), ("90", 90), ("90s", 90), ("1m30", 90), ("2 minutes", 120),
                              ("0:40", 40), ("1:02:03", 3723)]:
            self.assertEqual(router.parse_time(text), seconds, text)
        self.assertIsNone(router.parse_time("soon"))


class Retrieval(unittest.TestCase):
    def test_rare_words_beat_common_ones(self):
        docs = ["the price of the product is the main thing", "we talk about cooking pasta and the sauce",
                "pricing for the plan and the price list", "the the the the"]
        best = retrieval.rank("what about the pricing", docs)
        self.assertEqual(best[0][1], 2)                          # 'pricing/price' sentence wins
        self.assertEqual(retrieval.rank("zzz", docs), [])

    def test_stemming(self):
        self.assertEqual(retrieval.tokens("talking prices"), ["talk", "pric"])
        self.assertEqual(retrieval.tokens("pricing"), retrieval.tokens("price"))


class Chat(unittest.TestCase):
    """End to end: commands through the real server, with NO AI configured."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        cls.state = server.AppState(cls.tmp / "out")
        for name, text in [("cooking_show", "Today we talk about cooking pasta. The price of pasta is low."),
                           ("money_talk", "Our pricing plan has a free trial. Budget matters a lot.")]:
            proj = cls.state.out_dir / name
            (proj / "work").mkdir(parents=True)
            words = [{"word": w, "start": 10 + i * 0.5, "end": 10.4 + i * 0.5} for i, w in enumerate(text.split())]
            (proj / "work" / "transcript.json").write_text(json.dumps({"segments": [{"start": 10, "end": 40, "text": text, "words": words}]}))
            (proj / "shorts.json").write_text(json.dumps([{"title": "T " + name, "start": 10, "end": 30, "score": {"total": 70}, "file": "short_01.mp4"}]))
            (proj / "project.json").write_text(json.dumps({"mode": "talk", "video": "/v/%s.mp4" % name, "duration": 100,
                                                            "words_file": str(proj / "work" / "transcript.json")}))
        cls.httpd = server.make_server(cls.state)
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.state.port}"

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def post(self, path, body):
        req = urllib.request.Request(self.base + path, data=json.dumps(body).encode(), method="POST",
                                     headers={"X-Token": self.state.token})
        return json.loads(urllib.request.urlopen(req, timeout=20).read())

    def get(self, path):
        req = urllib.request.Request(self.base + path, headers={"X-Token": self.state.token})
        return json.loads(urllib.request.urlopen(req, timeout=20).read())

    def say(self, text):
        return self.post("/api/chat", {"text": text})

    def test_show_and_search(self):
        self.assertIn("cooking_show", self.say("show my projects")["reply"])
        r = self.say("search all my videos for pricing")
        self.assertIn("money_talk", r["reply"])
        self.assertEqual(r["via"], "rules")
        r = self.say("find where I talk about pasta in cooking_show")
        self.assertIn("pasta", r["reply"].lower())

    def test_help_and_open_question_without_ai(self):
        self.assertIn("Make shorts", self.say("help")["reply"])
        self.assertIn("Settings", self.say("write me a poem")["reply"])

    def test_make_without_video_is_friendly(self):
        r = self.say("make 5 shorts from my last video")
        self.assertFalse(r["jobs"])
        self.assertIn("upload", r["reply"].lower())

    def test_bad_trim_is_explained(self):
        r = self.say("trim clip 1 to 1:00-0:30")
        self.assertIn("after", r["reply"])
        r = self.say("trim clip 1 to 0:00-9:59")
        self.assertIn("1", r["reply"])                             # a clear error, not a crash

    def test_memory_and_feedback(self):
        self.say("remember that my channel is about cooking")
        self.assertIn("my channel is about cooking", self.get("/api/memory")["notes"])
        self.assertIn("cooking", self.say("what do you remember")["reply"])
        self.post("/api/feedback", {"rating": "down", "user": "x", "reply": "y", "via": "ai"})
        self.assertTrue(self.state.feedback_file.read_text().strip())
        self.post("/api/memory/clear", {})
        self.assertEqual(self.get("/api/memory")["notes"], [])

    def test_private_files_not_downloadable(self):
        self.say("remember that secret thing")
        for name in ("_memory.json", "_feedback.jsonl", "_settings.json"):
            req = urllib.request.Request(f"{self.base}/files/{name}", headers={"X-Token": self.state.token})
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(req)
            self.assertEqual(ctx.exception.code, 403)


if __name__ == "__main__":
    unittest.main()
