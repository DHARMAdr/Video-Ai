"""test_clipping.py - topic changes (topics.py) and the crop that follows the speaker (follow.py)."""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from shortsforge import follow, reframe, topics


def sentence(i, text):
    return {"start": i * 3.0, "end": i * 3.0 + 2.5, "text": text, "words": []}


class TopicTests(unittest.TestCase):
    def setUp(self):
        cooking = ["The pasta needs salted water.", "Tomato sauce goes with pasta.",
                   "Garlic makes the sauce better.", "Boil the pasta then add sauce.",
                   "Fresh tomato and garlic taste great.", "Serve the pasta with cheese."]
        cars = ["The engine needs new oil.", "Car tyres wear out fast.",
                "Brakes keep the car safe.", "Check engine oil every month.",
                "New tyres help the brakes.", "A clean engine runs the car well."]
        self.sentences = [sentence(i, t) for i, t in enumerate(cooking + cars)]

    def test_finds_the_change_between_two_subjects(self):
        found = topics.boundaries(self.sentences)
        self.assertIn(5, found)                       # between "cheese" and "engine"
        self.assertEqual(max(found, key=found.get), 5)

    def test_clip_that_fits_the_topic_scores_higher(self):
        def clip(a, b):
            return {"start": self.sentences[a]["start"], "end": self.sentences[b]["end"],
                    "score": {"total": 50.0}}
        fits, crosses = clip(6, 11), clip(3, 8)
        topics.apply([fits, crosses], self.sentences)
        self.assertGreater(fits["score"]["total"], 50)
        self.assertLess(crosses["score"]["total"], 50)

    def test_short_or_empty_speech_changes_nothing(self):
        self.assertEqual(topics.boundaries(self.sentences[:4]), {})
        self.assertEqual(topics.boundaries([sentence(i, "um okay") for i in range(12)]), {})


class FollowTests(unittest.TestCase):
    def test_goes_to_the_talker_and_does_not_flicker(self):
        samples = []
        for i in range(40):                           # 10 seconds, two people
            t = i * 0.25
            left_talks = t < 5
            samples.append((t, False, [(0.25, 0.1, 9 if left_talks else 1),
                                       (0.75, 0.1, 1 if left_talks else 9)]))
        steps = follow.plan(samples)
        self.assertEqual([round(c, 2) for _, c in steps], [0.25, 0.75])
        self.assertTrue(4.0 <= steps[1][0] <= 5.5, steps)

    def test_camera_cut_moves_at_once_and_no_faces_means_none(self):
        samples = [(i * 0.25, i == 3, [(0.2 if i < 3 else 0.8, 0.1, 0)]) for i in range(12)]
        self.assertEqual(follow.plan(samples)[1][0], 0.75)
        self.assertEqual(follow.plan([(i * 0.25, False, []) for i in range(12)]), [])

    @unittest.skipUnless(shutil.which("ffmpeg"), "needs ffmpeg")
    def test_moving_crop_really_renders(self):
        """Left half red, right half blue: the crop must show red first, blue later."""
        import cv2
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        source, out = tmp / "in.mp4", tmp / "out.mp4"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
                        "color=red:s=640x360:d=3:r=30", "-f", "lavfi", "-i",
                        "color=blue:s=640x360:d=3:r=30", "-filter_complex", "hstack", str(source)],
                       check=True)
        steps = [(0.0, 100.0)] + [(1.5, 1180.0)] + [(2.0 + i * 0.01, 1180.0) for i in range(58)]
        vf = reframe.build_filter("face", 1280, 360, steps)
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(source), "-vf", vf, str(out)],
                       check=True)
        capture = cv2.VideoCapture(str(out))
        for second, channel in ((0.5, 2), (2.5, 0)):  # OpenCV order: blue, green, red
            capture.set(cv2.CAP_PROP_POS_MSEC, second * 1000)
            ok, frame = capture.read()
            self.assertTrue(ok and frame[960, 540][channel] > 180, (second, frame[960, 540]))
        capture.release()
        self.assertEqual(len(follow.sample(source, 0.5, 2.0, detect=lambda gray: [])), 6)


class FaceDetectorTests(unittest.TestCase):
    """Uses the REAL face detector. OpenCV 5 removed it and the app broke without a test noticing."""

    @unittest.skipUnless(shutil.which("ffmpeg"), "needs ffmpeg")
    def test_the_installed_opencv_can_still_find_faces(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        video = tmp / "v.mp4"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
                        "testsrc2=s=640x360:d=2:r=30", str(video)], check=True)
        self.assertGreater(len(follow.sample(video, 0, 2)), 4)     # raises if no detector
        self.assertIsNone(reframe.detect_face_x(video, 0, 2, 640))


if __name__ == "__main__":
    unittest.main()
