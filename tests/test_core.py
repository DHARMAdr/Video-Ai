"""
test_core.py - automatic checks that the brain of ShortsForge behaves correctly.

WHY it exists:
    When you (or Claude) change the code later, run these tests to make sure nothing broke.
HOW it works:
    Run from the project folder:   python -m unittest discover tests -v
    The end-to-end test creates a tiny fake video with ffmpeg, so it needs no downloads
    and no speech model. It is skipped automatically if ffmpeg is missing.
HOW TO IMPROVE:
    Add one test for every bug you fix, so the bug can never come back.
"""

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from shortsforge import captions, scoring, segments
from shortsforge.config import load_profile


def fake_transcript(total_seconds=120):
    """A made-up transcript: one 4-second sentence at a time. Sentence 0 is a strong hook."""
    segs, t, i = [], 0.0, 0
    while t + 4 <= total_seconds:
        text = ("Here's why you should never do this mistake?" if i == 10
                else f"This is plain sentence number {i} about nothing special.")
        words = text.split()
        step = 4.0 / len(words)
        segs.append({"start": t, "end": t + 4.0, "text": text, "words": [
            {"word": w, "start": t + k * step, "end": t + (k + 1) * step}
            for k, w in enumerate(words)]})
        t += 4.0
        i += 1
    return {"language": "en", "segments": segs}


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.profile = load_profile()

    def test_hook_beats_plain(self):
        strong, _ = scoring.score_hook("Here's why you should never do this mistake?", self.profile)
        plain, _ = scoring.score_hook("This is plain sentence number three.", self.profile)
        self.assertGreater(strong, plain)

    def test_candidates_respect_length_and_do_not_overlap_when_picked(self):
        sentences = segments.to_sentences(fake_transcript())
        cands = segments.build_candidates(sentences, self.profile)
        self.assertTrue(cands)
        for c in cands:
            self.assertGreaterEqual(c["duration"], self.profile["min_seconds"])
            self.assertLessEqual(c["duration"], self.profile["max_seconds"])
            c["score"] = scoring.score_candidate(c, None, self.profile)
        top = segments.pick_top(cands, 3)
        for a in top:
            for b in top:
                if a is not b:
                    self.assertFalse(a["start"] < b["end"] and a["end"] > b["start"])

    def test_best_clip_starts_with_the_hook(self):
        sentences = segments.to_sentences(fake_transcript())
        cands = segments.build_candidates(sentences, self.profile)
        for c in cands:
            c["score"] = scoring.score_candidate(c, None, self.profile)
        best = segments.pick_top(cands, 1)[0]
        self.assertIn("never do this mistake", best["first_sentence"])

    def test_captions_have_events_and_start_at_zero(self):
        words = [{"word": "Hello", "start": 10.0, "end": 10.4},
                 {"word": "world", "start": 10.5, "end": 10.9}]
        ass = captions.build_ass(words, 10.0, 12.0, "Title", self.profile["caption"])
        self.assertIn("Dialogue", ass)
        self.assertIn("0:00:00.00", ass)


@unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg not installed")
class EndToEnd(unittest.TestCase):
    def test_full_pipeline_with_fake_video(self):
        from shortsforge.pipeline import run
        tmp = Path(tempfile.mkdtemp())
        video = tmp / "demo.mp4"
        # 120 s test pattern with a tone, 1280x720 (landscape like a normal video)
        subprocess.run([
            "ffmpeg", "-y", "-v", "error",
            "-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=25:duration=120",
            "-f", "lavfi", "-i", "sine=frequency=300:duration=120",
            "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", "-shortest", str(video),
        ], check=True)
        tr = tmp / "tr.json"
        tr.write_text(json.dumps(fake_transcript()))
        result = run(str(video), out_root=str(tmp / "out"), count=2, reframe_mode="blur",
                     transcript_file=str(tr), log=lambda *_: None)
        for s in result["shorts"]:
            out = Path(result["project"]) / "clips" / s["file"]
            self.assertTrue(out.exists() and out.stat().st_size > 10_000)
            info = json.loads(subprocess.run(
                ["ffprobe", "-v", "error", "-print_format", "json", "-show_streams", str(out)],
                capture_output=True, text=True).stdout)
            v = next(x for x in info["streams"] if x["codec_type"] == "video")
            self.assertEqual((v["width"], v["height"]), (1080, 1920))
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
