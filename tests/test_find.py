"""
test_find.py - tests "describe it, find it, cut it" (shortsforge/find).

HOW: we DRAW a fake game video whose kill feed has a small made-up icon per character, then teach
the app those icons and search with sentences. The speech and the picture AI are replaced by
fakes, so no model is needed.
HOW TO IMPROVE: add a short piece of real gameplay (with permission) and its true answers.
"""

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np

from shortsforge import teach
from shortsforge.find import engine, moments, pictures, query, speech, vision

try:
    import cv2
except ImportError:
    cv2 = None

W, H, FPS, LENGTH = 1280, 720, 8, 60
ME = "ShadowFox"
# (time, killer, killer agent, victim, victim agent)
ROWS = [(5, ME, "Reyna", "enemy1", "Jett"), (18, ME, "Reyna", "enemy2", "Sage"),
        (30, "mate", "Omen", "enemy1", "Jett"), (41, "enemy3", "Raze", ME, "Reyna"),
        (50, ME, "Reyna", "enemy1", "Jett")]
BANNER = (22.0, 25.0)


def icon(seed: int):
    """A 30x30 pattern that stands for one character's face."""
    blocks = np.random.default_rng(seed).integers(20, 235, (5, 5, 3), dtype=np.uint8)
    return cv2.resize(blocks, (30, 30), interpolation=cv2.INTER_NEAREST)


AGENTS = {"Jett": 1, "Sage": 2, "Reyna": 3, "Omen": 4, "Raze": 5}


def banner():
    picture = np.full((80, 300, 3), 30, np.uint8)
    cv2.putText(picture, "VICTORY", (20, 58), cv2.FONT_HERSHEY_DUPLEX, 1.8, (60, 220, 240), 3)
    cv2.circle(picture, (270, 40), 22, (200, 90, 60), -1)
    return picture


def draw_video(path: Path) -> dict:
    """Write the fake video and return the boxes (frame fractions) of each icon and the banner."""
    font = cv2.FONT_HERSHEY_SIMPLEX
    bursts = "+".join(f"between(t,{r[0] - 0.6},{r[0]})*lt(mod(t,0.25),0.08)" for r in ROWS)
    command = ["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "bgr24",
               "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-", "-f", "lavfi", "-i",
               f"anoisesrc=d={LENGTH}:a=0.5,volume='if({bursts},1,0.02)':eval=frame", "-shortest",
               "-pix_fmt", "yuv420p", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "17",
               "-c:a", "aac", str(path)]
    proc = subprocess.Popen(command, stdin=subprocess.PIPE)
    boxes = {}
    for i in range(LENGTH * FPS):
        t = i / FPS
        frame = np.full((H, W, 3), 45, np.uint8)
        cv2.circle(frame, (200 + (i * 7) % 600, 500), 40, (90, 140, 90), -1)
        live = [r for r in ROWS if r[0] <= t < r[0] + 5]
        for n, (_, killer, k_agent, victim, v_agent) in enumerate(live):
            top = 40 + n * 40
            victim_icon_x = W - 50
            victim_x = victim_icon_x - 8 - cv2.getTextSize(victim, font, 0.6, 1)[0][0]
            killer_x = victim_x - 90 - cv2.getTextSize(killer, font, 0.6, 1)[0][0]
            cv2.rectangle(frame, (killer_x - 46, top - 2), (W - 16, top + 32), (15, 15, 15), -1)
            for x, agent in ((killer_x - 40, k_agent), (victim_icon_x, v_agent)):
                frame[top:top + 30, x:x + 30] = icon(AGENTS[agent])
                boxes.setdefault(agent, (t, [x / W, top / H, (x + 30) / W, (top + 30) / H]))
            cv2.putText(frame, killer, (killer_x, top + 21), font, 0.6, (235, 235, 235), 1, cv2.LINE_AA)
            cv2.putText(frame, victim, (victim_x, top + 21), font, 0.6, (235, 235, 235), 1, cv2.LINE_AA)
            if killer == ME and "name" not in boxes:
                width = cv2.getTextSize(ME, font, 0.6, 1)[0][0]
                boxes["name"] = (t, [(killer_x - 2) / W, (top + 6) / H,
                                     (killer_x + width + 2) / W, (top + 26) / H])
        if BANNER[0] <= t < BANNER[1]:
            frame[300:380, 490:790] = banner()
            boxes.setdefault("banner", (t, [490 / W, 300 / H, 790 / W, 380 / H]))
        proc.stdin.write(frame.tobytes())
    proc.stdin.close()
    assert proc.wait() == 0
    return boxes


class QueryTests(unittest.TestCase):
    """Sentences must become the right search."""

    def test_kill_relations(self):
        for text, killer, victim in [
            ("find where I kill Jett", "me", "Jett"),
            ("my kills on a jett", "me", "Jett"),
            ("kill of Jett", "me", "Jett"),
            ("clips of Jett getting a kill", "Jett", None),
            ("when I am killed by Raze", "Raze", "me"),
            ("Raze kills me", "Raze", "me"),
            ("my kills with Reyna", "Reyna", None),
            ("Omen killing Jett", "Omen", "Jett"),
        ]:
            plan = query.parse(text)
            self.assertEqual((plan["killer"], plan["victim"]), (killer, victim), text)

    def test_numbers_time_and_speech(self):
        plan = query.parse("top 3 triple kills in the last 10 minutes, 20 second clips")
        self.assertEqual((plan["limit"], plan["multi"], plan["range"]["last"], plan["length"]),
                         (3, 3, 600, 20))
        self.assertEqual(query.parse('find where I say "nice shot"')["said"], "nice shot")
        plan = query.parse("kills between 1:00 and 3:30")
        self.assertEqual((plan["range"]["from"], plan["range"]["to"]), (60, 210))
        self.assertEqual(query.parse("my first kill")["which"], "first")

    def test_descriptions_and_pictures(self):
        plan = query.parse("the spike being planted")
        self.assertTrue(plan["description"])
        self.assertFalse(plan["kill"])
        self.assertEqual(query.parse("show the victory screen", ["victory screen"])["pictures"],
                         ["victory screen"])
        self.assertIn("kills", query.explain(query.parse("kill Jett")))
        self.assertEqual(query.parse("where I kill Jett", ["Jett"])["pictures"], [])
        with self.assertRaises(ValueError):
            query.parse("   ")


class PieceTests(unittest.TestCase):
    def test_merge_and_require(self):
        groups = moments.merge([moments.hit(10, 0.5, "feed", "a"), moments.hit(12, 0.5, "speech", "b"),
                                moments.hit(80, 0.9, "feed", "c")])
        self.assertEqual([g["confidence"] for g in groups], [0.75, 0.9])
        self.assertEqual(len(moments.require(groups, ["feed", "speech"])), 1)
        start, end = moments.bounds(groups[0], 100)
        self.assertTrue(start < 10 < 12 < end <= 100)
        self.assertEqual(moments.bounds(groups[1], 82, length=20)[1], 82)

    def test_speech_allows_small_mistakes(self):
        words = [{"word": w, "start": i, "end": i + 0.5}
                 for i, w in enumerate("that was a cluch moment my friend".split())]
        found = speech.search({"segments": [{"words": words}]}, "clutch moment")
        self.assertEqual([h["t"] for h in found], [3])
        self.assertEqual(speech.search({"segments": [{"words": words}]}, "banana"), [])

    def test_vision_answers(self):
        self.assertTrue(vision.read_answer('Sure: {"match": true, "confidence": 90}')["match"])
        self.assertFalse(vision.read_answer('{"match": "false"}')["match"])
        self.assertFalse(vision.read_answer("I cannot tell")["match"])
        self.assertLessEqual(len(vision.coarse_times(0, 100000)), vision.MAX_COARSE)


@unittest.skipUnless(shutil.which("ffmpeg") and cv2 is not None, "needs ffmpeg and OpenCV")
class SearchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        cls.video = cls.tmp / "match.mp4"
        cls.boxes = draw_video(cls.video)
        cls.out = cls.tmp / "out"
        cls.out.mkdir()
        t, box = cls.boxes["name"]
        teach.save_name(cls.out, cls.video, t + 1, box)
        for agent in ("Jett", "Raze", "Omen"):
            t, box = cls.boxes[agent]
            pictures.add(cls.out, cls.video, t + 1, box, agent, "feed")
        t, box = cls.boxes["banner"]
        pictures.add(cls.out, cls.video, t + 1, box, "victory", "scene")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def find(self, text, **extra):
        return engine.search(self.out, self.video, text, log=lambda *_: None, **extra)

    def times(self, answer):
        return [round(m["at"]) for m in answer["moments"]]

    def test_my_kills_on_a_character(self):
        answer = self.find("find where I kill Jett")
        self.assertEqual(self.times(answer), [5, 50], answer)       # not the teammate's at 30
        first = answer["moments"][0]
        self.assertTrue(first["start"] < 5 < first["end"])
        self.assertTrue((self.out / first["thumb"]).is_file())

    def test_other_players(self):
        self.assertEqual(self.times(self.find("Omen killing Jett")), [30])
        self.assertEqual(self.times(self.find("when Raze kills me")), [41])

    def test_untaught_character_is_said_not_guessed(self):
        answer = self.find("kill Viper")
        self.assertEqual(answer["moments"], [])
        self.assertIn("Viper", answer["problems"][0])

    def test_scene_picture_and_time_range(self):
        self.assertEqual(self.times(self.find("show me the victory")), [22])
        self.assertEqual(self.times(self.find("kill Jett after 0:30")), [50])

    def test_speech_and_kill_together(self):
        words = [{"word": "clutch", "start": 51.0, "end": 51.4}]
        answer = self.find("kill Jett where I say clutch",
                           transcriber=lambda v, w: {"segments": [{"words": words}]})
        self.assertEqual(self.times(answer), [50], answer)

    def test_picture_ai(self):
        def look(system, question, image):
            self.assertTrue(image.startswith("data:image/jpeg;base64,"))
            return json.dumps({"match": False})
        answer = self.find("the spike being planted", look=look)
        self.assertEqual(answer["moments"], [])
        self.assertIn("picture AI", self.find("the spike being planted")["problems"][0])
        seen = []
        def yes_once(*_):
            seen.append(1)
            return json.dumps({"match": len(seen) == 3, "confidence": 90, "seen": "a spike"})
        self.assertEqual(len(self.find("the spike being planted", look=yes_once)["moments"]), 1)

    def test_make_clips(self):
        answer = self.find("find where I kill Jett")
        result = engine.make_clips(self.out, self.video, answer["moments"][:1], "Jett",
                                   log=lambda *_: None)
        self.assertEqual(result["count"], 1)
        clips = list((self.out / result["project_name"] / "clips").glob("*.mp4"))
        self.assertEqual(len(clips), 1)


class AssistantTests(unittest.TestCase):
    def test_router_sends_scene_requests_to_find(self):
        from shortsforge.app import router
        for text in ("find where I kill Jett", "show my triple kills", "find the scene with the spike",
                     "find where I kill Sage in my last video"):
            self.assertEqual(router.parse(text)["intent"], "scene", text)
        for text in ("find my valorant video", "find where I talk about pricing", "show my projects",
                     "make valorant shorts with at least 2 kills", "find my kill video"):
            self.assertNotEqual((router.parse(text) or {}).get("intent"), "scene", text)

    def test_only_public_web_pages_are_opened(self):
        from shortsforge.app import websearch
        for url in ("file:///C:/secret.txt", "http://127.0.0.1:8000/", "http://localhost/",
                    "http://192.168.1.1/", "http://169.254.169.254/", "ftp://example.com/",
                    "http://user:pw@example.com/", "http://[::1]/"):
            with self.assertRaises(ValueError, msg=url):
                websearch.check_public(url)
        text = websearch.page_text("<script>bad()</script><p>Hello &amp; welcome</p><p>Second</p>")
        self.assertEqual(text, "Hello & welcome\nSecond")

    def test_invented_links_are_removed(self):
        from shortsforge.app.assistant import ToolBox, check_links

        class State:
            settings = None
        box = ToolBox(State())
        self.assertIn("http://x.invalid", check_links("see http://x.invalid", box, [], ""))
        box.searches, box.sources = 1, ["https://playvalorant.com/news"]
        reply = check_links("Read https://playvalorant.com/news. Not https://roitgames.com/x.", box, [], "")
        self.assertIn("https://playvalorant.com/news.", reply)
        self.assertNotIn("roitgames", reply)
        self.assertIn("error", box.t_read_page("https://example.com/?secret=1"))

    def test_picture_ai_needs_a_local_ai(self):
        from shortsforge.app.assistant import looker

        class Settings:
            def __init__(self, provider, cfg):
                self.value = (provider, cfg)

            def provider_config(self):
                return self.value
        self.assertIsNone(looker(Settings("anthropic", {"model": "x", "api_key": "k"}), None))
        self.assertIsNone(looker(Settings("openai", {"model": "x", "base_url": "https://openrouter.ai/api/v1"}), None))
        self.assertIsNotNone(looker(Settings("openai", {"model": "x", "base_url": "http://localhost:11434/v1"}), None))


if __name__ == "__main__":
    unittest.main()
