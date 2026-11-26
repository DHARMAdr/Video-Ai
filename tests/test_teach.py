"""
test_teach.py - tests "learn from my video", the action-moment fallback and finding videos.

HOW: we DRAW a fake game video with a known kill feed (white text on dark rows, no red at all, so
the built-in colour rule cannot work), with our kills, a teammate's kill and our own death.
HOW TO IMPROVE: add a clip of real gameplay (with permission) and its true kill times.
"""

import json
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np

from shortsforge import killfeed, pipeline, teach
from shortsforge.app import library, router, server
from shortsforge.app.assistant import ToolBox
from shortsforge.config import load_game_profile

try:
    import cv2
except ImportError:
    cv2 = None

W, H, FPS = 1280, 720, 8
MY_KILLS = [5.0, 14.0, 23.0]
DEATH, TEAMMATE = 31.0, 36.0
LENGTH = 44


def draw_video(path: Path) -> dict:
    """Write the fake video. Returns where our name sits in the first kill (frame fractions)."""
    rows = [(t, "ShadowFox", "Brimstone") for t in MY_KILLS]
    rows += [(DEATH, "Viper", "ShadowFox"), (TEAMMATE, "SageMain", "Raze")]
    font = cv2.FONT_HERSHEY_SIMPLEX
    bursts = "+".join(f"between(mod(t,100),{t - 0.6},{t})*lt(mod(t,0.25),0.08)" for t in MY_KILLS)
    command = ["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24",
               "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-", "-f", "lavfi", "-i",
               # quiet noise with loud "shots" at each kill
               f"anoisesrc=d={LENGTH}:a=0.5,volume='if({bursts},1,0.02)':eval=frame", "-shortest", "-pix_fmt", "yuv420p",
               "-c:v", "libx264", "-preset", "ultrafast", "-crf", "18", "-c:a", "aac", str(path)]
    proc = subprocess.Popen(command, stdin=subprocess.PIPE)
    name_box = None
    for i in range(LENGTH * FPS):
        t = i / FPS
        frame = np.full((H, W, 3), 40, np.uint8)
        cv2.circle(frame, (200 + (i * 7) % 600, 400), 40, (90, 140, 90), -1)
        live = [r for r in rows if r[0] <= t < r[0] + 5]
        for n, (_, killer, victim) in enumerate(live):
            y = 60 + n * 34
            victim_w = cv2.getTextSize(victim, font, 0.6, 1)[0][0]
            victim_x = W - 50 - victim_w                  # right aligned, like a real feed
            killer_w, killer_h = cv2.getTextSize(killer, font, 0.6, 1)[0]
            killer_x = victim_x - 90 - killer_w
            cv2.rectangle(frame, (killer_x - 36, y - 20), (W - 16, y + 8), (15, 15, 15), -1)
            cv2.putText(frame, killer, (killer_x, y), font, 0.6, (235, 235, 235), 1, cv2.LINE_AA)
            cv2.putText(frame, "==>", (victim_x - 62, y), font, 0.5, (180, 180, 180), 1)
            cv2.putText(frame, victim, (victim_x, y), font, 0.6, (235, 235, 235), 1, cv2.LINE_AA)
            if killer == "ShadowFox" and name_box is None:
                name_box = [(killer_x - 2) / W, (y - killer_h - 3) / H,
                            (killer_x + killer_w + 2) / W, (y + 6) / H]
        proc.stdin.write(frame.tobytes())
    proc.stdin.close()
    assert proc.wait() == 0
    return name_box


@unittest.skipUnless(shutil.which("ffmpeg") and cv2 is not None, "needs ffmpeg and OpenCV")
class TeachTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        cls.video = cls.tmp / "my valorant stream.mp4"
        cls.name_box = draw_video(cls.video)
        cls.out = cls.tmp / "out"
        cls.out.mkdir()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_1_no_kill_gives_action_moments_not_an_error(self):
        result = pipeline.run_game(str(self.video), out_root=str(self.tmp / "plain"), count=2,
                                   log=lambda *_: None)
        self.assertEqual(result["kills"], [])
        self.assertTrue(result["shorts"])
        self.assertIn("ACTION MOMENTS", result["note"])
        self.assertEqual(result["shorts"][0]["label"], "ACTION MOMENT")
        self.assertTrue((Path(result["project"]) / "clips" / "short_01.mp4").exists())

    def test_2_teaching_the_name_finds_only_my_kills(self):
        teach.save_name(self.out, self.video, MY_KILLS[0] + 1.0, self.name_box)
        report = teach.learn(self.out, self.video, [t + 0.3 for t in MY_KILLS], log=lambda *_: None)
        self.assertTrue(report["ok"], report)
        self.assertEqual(report["hits"], 3, report)
        self.assertTrue(report["method"].startswith("name"), report)
        gp = teach.apply(self.out, load_game_profile("valorant"))
        info = pipeline.ingest.probe(self.video)
        kills = killfeed.detect(self.video, info, gp, self.tmp / "work", log=lambda *_: None)
        self.assertEqual(len(kills), 3, kills)               # the death and teammate are ignored
        for found, real in zip(kills, MY_KILLS):
            self.assertAlmostEqual(found, real, delta=0.6)

    def test_3_learning_without_a_clue_says_so(self):
        other = self.tmp / "empty"
        report = teach.learn(other, self.video, [10.0], log=lambda *_: None)
        self.assertFalse(report["ok"])
        self.assertIn("name", report["message"])
        self.assertNotIn("method", {k for k in teach.load(other) if k == "method"})

    def test_4_bad_boxes_are_refused(self):
        with self.assertRaises(ValueError):
            teach.save_area(self.out, [0.5, 0.5, 0.5, 0.5])
        with self.assertRaises(ValueError):                   # plain background, no text
            teach.save_name(self.out, self.video, 1.0, [0.1, 0.1, 0.2, 0.15])

    def test_5_a_failed_video_can_still_be_found_by_forge(self):
        state = server.AppState(self.tmp / "app")
        with mock.patch.object(library, "search_folders", lambda extra=(): []):
            server.make_start_job(state, {"source": str(self.video), "mode": "game"})
            box = ToolBox(state)
            names = [v["name"] for v in box.t_find_videos("find my valorant video")["videos"]]
            self.assertEqual(names, [self.video.name])
            self.assertTrue(box._known(str(self.video)))
            self.assertEqual(box.t_find_videos("birthday")["videos"], [])
            # a phone must not see PC files
            self.assertEqual(ToolBox(state, remote=True).t_find_videos("")["videos"], [])
            self.assertFalse(ToolBox(state, remote=True)._known(str(self.video)))

    def test_6_files_in_the_usual_folders_are_found(self):
        home = self.tmp / "home"
        (home / "Videos" / "Valorant").mkdir(parents=True)
        clip = home / "Videos" / "Valorant" / "ranked match.mp4"
        shutil.copy(self.video, clip)
        with mock.patch.object(library, "MIN_SIZE", 10), \
                mock.patch.object(library, "search_folders", lambda extra=(): [home / "Videos"]):
            found = library.find(self.out, "ranked")
        self.assertEqual([v["path"] for v in found], [str(clip)])

    def test_7_find_video_command_and_teach_routes(self):
        self.assertEqual(router.parse("find my valorant video")["intent"], "find_video")
        self.assertEqual(router.parse("where is the recording from monday")["intent"], "find_video")
        self.assertEqual(router.parse("find where I talk about pricing in the video")["intent"], "search")
        state = server.AppState(self.tmp / "routes")
        httpd = server.make_server(state)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{state.port}"

        def get(path):
            return urllib.request.urlopen(urllib.request.Request(
                base + path, headers={"X-Token": state.token}), timeout=30).read()

        def post(path, body):
            return urllib.request.urlopen(urllib.request.Request(
                base + path, data=json.dumps(body).encode(), headers={"X-Token": state.token}),
                timeout=60).read()
        try:
            page = get("/")
            self.assertIn(b"view-teach", page)
            self.assertIn(b"tLearn').addEventListener", page)     # teach.js is inside the page
            self.assertFalse(json.loads(get("/api/teach"))["taught"])
            post("/api/teach", {"action": "name", "source": str(self.video),
                                "time": MY_KILLS[0] + 1, "box": self.name_box})
            self.assertTrue(json.loads(get("/api/teach"))["name"])
            from urllib.parse import quote
            self.assertGreater(len(get("/api/video?path=" + quote(str(self.video)))), 1000)
            with self.assertRaises(urllib.error.HTTPError):       # only video files
                get("/api/video?path=" + quote(__file__))
            self.assertIn("ShortsForge", json.loads(get("/api/report"))["text"])
        finally:
            httpd.shutdown()
            httpd.server_close()


if __name__ == "__main__":
    unittest.main()
