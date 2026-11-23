"""
test_game.py - automatic checks for the Valorant kill-detection mode.

WHY it exists:
    Proves the detector counts kill-feed rows correctly, ignores look-alike things, groups
    kills into plays, and that rendering produces a proper vertical video.
HOW it works:
    We build a FAKE 1920x1080 "game" video with ffmpeg: a noisy dark background and coloured
    boxes that appear in the top-right like kill-feed rows. Known kill times:
        5s, 8s, 10s  (a triple)   and   25s  (a single)
    Distractors that must NOT count: a dark teal teammate row, a red box on the LEFT of the scan
    area (not right-aligned), and a full-screen red flash.
    IMPORTANT: this proves the LOGIC. Real Valorant colours are checked with the calibrate tool.
    Run:  python -m unittest discover tests -v
HOW TO IMPROVE:
    Add a test using a short real clip of your own footage (a few seconds) with known kill times.
"""

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from shortsforge import highlights, killfeed
from shortsforge.config import load_game_profile

EXPECTED_KILLS = [5.0, 8.0, 10.0, 25.0]


def make_fake_game(path: Path, seconds: int = 40) -> None:
    """Create the fake gameplay video described in the module notes."""
    red = "0xFF4655"
    boxes = [
        f"drawbox=x=1520:y=60:w=380:h=40:color={red}:t=fill:enable='between(t,5,12)'",
        f"drawbox=x=1520:y=106:w=380:h=40:color={red}:t=fill:enable='between(t,8,15)'",
        f"drawbox=x=1520:y=152:w=380:h=40:color={red}:t=fill:enable='between(t,10,17)'",
        f"drawbox=x=1520:y=60:w=380:h=40:color={red}:t=fill:enable='between(t,25,32)'",
        # distractors:
        "drawbox=x=1500:y=250:w=400:h=40:color=0x1f6b5c:t=fill:enable='between(t,14,21)'",
        f"drawbox=x=1160:y=300:w=340:h=40:color={red}:t=fill:enable='between(t,18,20)'",
        "drawbox=x=0:y=0:w=1920:h=1080:color=0xFF2030:t=fill:enable='between(t,35,35.5)'",
    ]
    graph = f"color=c=0x1c2a38:s=1920x1080:r=25:d={seconds},noise=alls=25:allf=t+u," + ",".join(boxes)
    subprocess.run([
        "ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", graph,
        "-f", "lavfi", "-i", f"sine=frequency=300:duration={seconds}",
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-shortest", str(path)], check=True)


class PlayLogic(unittest.TestCase):
    def setUp(self):
        self.gp = load_game_profile()

    def test_grouping_and_labels(self):
        plays = highlights.group_plays([5, 8, 10, 25], self.gp, 40.0)
        self.assertEqual([p["count"] for p in plays], [3, 1])
        self.assertEqual(plays[0]["label"], "TRIPLE KILL")
        self.assertGreaterEqual(plays[1]["end"] - plays[1]["start"], self.gp["min_clip_seconds"])

    def test_more_kills_score_higher_and_selection_does_not_overlap(self):
        plays = highlights.group_plays([5, 8, 10, 25], self.gp, 40.0)
        for p in plays:
            highlights.score_play(p, None, self.gp)
        self.assertGreater(plays[0]["score"]["total"], plays[1]["score"]["total"])
        picked = highlights.select_plays(plays, 5, min_kills=2)
        self.assertEqual(len(picked), 1)

    def test_long_chain_is_split(self):
        kills = [i * 6.0 for i in range(1, 20)]          # a kill every 6 s for ~2 minutes
        plays = highlights.group_plays(kills, self.gp, 200.0)
        for p in plays:
            self.assertLessEqual(p["end"] - p["start"], self.gp["max_clip_seconds"] + 0.01)

    def test_counts_to_kills(self):
        self.assertEqual(killfeed.counts_to_kill_times([0, 1, 1, 2, 1, 0, 1], 1.0), [1.0, 3.0, 6.0])


@unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg not installed")
class DetectionAndRender(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        cls.video = cls.tmp / "fake_valorant.mp4"
        make_fake_game(cls.video)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_detects_exactly_the_real_kills(self):
        from shortsforge.pipeline import detect_only
        kills = detect_only(str(self.video), out_root=str(self.tmp / "o1"), log=lambda *_: None)
        self.assertEqual(len(kills), len(EXPECTED_KILLS), f"got {kills}")
        for found, wanted in zip(kills, EXPECTED_KILLS):
            self.assertAlmostEqual(found, wanted, delta=0.6)

    def test_full_run_all_layouts_make_vertical_video(self):
        from shortsforge.pipeline import run_game
        for layout, facecam in (("center", None), ("blur", None), ("stack", [0.0, 0.7, 0.25, 0.3])):
            res = run_game(str(self.video), out_root=str(self.tmp / f"o_{layout}"), count=2,
                           layout=layout, facecam=facecam, log=lambda *_: None)
            self.assertEqual(len(res["shorts"]), 2)
            self.assertEqual(res["shorts"][0]["label"], "TRIPLE KILL")
            for s in res["shorts"]:
                out = Path(res["project"]) / "clips" / s["file"]
                info = json.loads(subprocess.run(
                    ["ffprobe", "-v", "error", "-print_format", "json", "-show_streams", str(out)],
                    capture_output=True, text=True).stdout)
                v = next(x for x in info["streams"] if x["codec_type"] == "video")
                self.assertEqual((v["width"], v["height"]), (1080, 1920), layout)
            ass = (Path(res["project"]) / "clips" / "short_01.ass").read_text()
            self.assertIn("TRIPLE KILL", ass)


if __name__ == "__main__":
    unittest.main()
