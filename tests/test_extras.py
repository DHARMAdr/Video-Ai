"""
Tests for the newest editor tools: curve speed, masks, blend modes, effects, match cut,
motion tracking, background removal and text to speech. Videos are made by ffmpeg here.

HOW TO IMPROVE: check more pixels of more mask shapes.
"""

import subprocess
import tempfile
import unittest
from pathlib import Path

import numpy as np

from shortsforge import editor, editor_extras, ingest, matting, tracking, tts
from shortsforge.app import editortools

try:
    import cv2
except ImportError:                                       # pragma: no cover
    cv2 = None


def make(path: Path, source: str, seconds: float = 3, audio: bool = True) -> str:
    cmd = ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"{source}:d={seconds}:r=30"]
    if audio:
        cmd += ["-f", "lavfi", "-i", f"sine=d={seconds}"]
    cmd += ["-pix_fmt", "yuv420p", "-shortest", str(path)]
    subprocess.run(cmd, check=True)
    return str(path)


def pixel(video, x, y, at=0.5):
    """(r, g, b) at a place given as shares of the frame."""
    info = ingest.probe(Path(video))
    raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", str(at), "-i", str(video),
                          "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                         capture_output=True, check=True).stdout
    frame = np.frombuffer(raw, np.uint8).reshape(info["height"], info["width"], 3)
    return tuple(int(v) for v in frame[int(y * (info["height"] - 1)), int(x * (info["width"] - 1))])


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        cls.dir = Path(cls.tmp.name)
        cls.grey = make(cls.dir / "grey.mp4", "color=c=0x606060:s=640x360")
        cls.red = make(cls.dir / "red.mp4", "color=c=0xc00000:s=320x180", audio=False)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def render(self, segment=None, **timeline):
        out = self.dir / "out.mp4"
        seg = {"source": self.grey, "start": 0, "end": 2, **(segment or {})}
        length = editor.render({"aspect": "16:9", "segments": [seg], **timeline}, out,
                               log=lambda m: None, preview=True)
        return out, length


@unittest.skipIf(cv2 is None, "OpenCV is not installed")
class EditorExtras(Base):
    def test_curve_speed_changes_the_length_as_promised(self):
        for name in ("montage", "bullet"):
            _, length = self.render({"curve": name, "speed": 3})
            self.assertAlmostEqual(length, 2 * editor_extras.curve_factor(name), delta=0.25)

    def test_mask_on_the_piece_hides_the_outside(self):
        out, _ = self.render({"mask": {"shape": "circle", "size": 0.5, "feather": 0}})
        self.assertLess(max(pixel(out, 0.05, 0.5)), 30)
        self.assertGreater(min(pixel(out, 0.5, 0.5)), 70)

    def test_masked_layer_and_blend_modes(self):
        layer = {"kind": "video", "source": self.red, "start": 0, "end": 2, "scale": 0.5}
        out, _ = self.render(overlays=[{**layer, "mask": {"shape": "circle", "size": 0.5,
                                                          "feather": 0}}])
        self.assertGreater(pixel(out, 0.5, 0.5)[0], 150)          # inside the circle: red
        self.assertLess(pixel(out, 0.28, 0.28)[0], 130)           # layer corner: see-through
        for mode, check in (("screen", lambda p: p[0] > 180 and 70 < p[1] < 120),
                            ("multiply", lambda p: 50 < p[0] < 95 and p[1] < 25),
                            ("add", lambda p: p[0] > 220 and 70 < p[1] < 120),
                            ("overlay", lambda p: p[0] > 120 and p[1] < 40),
                            ("soft light", lambda p: p[0] > 96 and p[1] < 90)):
            out, _ = self.render(overlays=[{**layer, "blend": mode}])
            self.assertTrue(check(pixel(out, 0.5, 0.5)), (mode, pixel(out, 0.5, 0.5)))
            outside = pixel(out, 0.05, 0.05)                      # untouched elsewhere
            self.assertTrue(all(abs(v - 96) < 8 for v in outside), (mode, outside))

    def test_every_effect_renders(self):
        for effect in editor.EFFECTS:
            _, length = self.render({"effect": effect, "end": 0.6})
            self.assertGreater(length, 0.4, effect)

    def test_match_cut_finds_the_same_picture(self):
        moving = make(self.dir / "move.mp4", "testsrc2=s=320x180", 6, audio=False)
        found = editor_extras.match_cut({"source": moving, "start": 0, "end": 3},
                                        {"source": moving, "start": 2, "end": 6})
        self.assertGreater(found["likeness"], 0.9)
        self.assertLess(abs((found["end"] - 0.1) - found["start"]), 0.25)


@unittest.skipIf(cv2 is None, "OpenCV is not installed")
class Tracking(unittest.TestCase):
    def scene(self, frames=45, jump_out=False):
        """A textured square sliding right and down over a plain background."""
        patch = np.random.default_rng(1).integers(0, 255, (60, 60)).astype(np.uint8)
        patch = cv2.GaussianBlur(patch, (3, 3), 0)
        for i in range(frames):
            image = np.full((360, 640), 90, np.uint8)
            if not (jump_out and i > 20):
                image[80 + 2 * i:140 + 2 * i, 100 + 6 * i:160 + 6 * i] = patch
            yield image

    def test_follows_a_moving_thing(self):
        path = tracking.follow_frames(self.scene(), (100, 80, 60, 60))
        x, y, _, _, found = path[-1]
        self.assertTrue(found)
        self.assertAlmostEqual(x, 100 + 6 * 44, delta=8)
        self.assertAlmostEqual(y, 80 + 2 * 44, delta=8)

    def test_says_when_the_thing_is_gone_and_refuses_a_blank_box(self):
        path = tracking.follow_frames(self.scene(jump_out=True), (100, 80, 60, 60))
        self.assertFalse(path[-1][4])
        with self.assertRaisesRegex(ValueError, "nothing clear"):
            tracking.follow_frames(self.scene(), (400, 20, 60, 60))

    def test_straight_movement_needs_only_its_ends(self):
        points = [{"t": i / 10, "x": i / 100, "y": 0.5, "scale": 1.0} for i in range(50)]
        self.assertEqual(len(tracking.simplify(points, 60)), 2)


@unittest.skipUnless(cv2 is not None and matting.available(), "model not downloaded")
class Matting(Base):
    def test_a_plain_picture_has_no_person_and_layers_become_see_through(self):
        self.assertLess(matting.matte(np.full((180, 320, 3), 90, np.uint8)).mean(), 0.2)
        out = matting.process(self.red, 0, 1, self.dir / "cut.mkv", "transparent",
                              log=lambda m: None)
        self.assertIn("yuva", subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "stream=pix_fmt", "-of", "csv=p=0",
             str(out)], capture_output=True, text=True).stdout)

    def test_removed_background_renders_for_pieces_and_layers(self):
        out, length = self.render({"bg": "green", "end": 1})
        self.assertGreater(pixel(out, 0.5, 0.5)[1], 200)
        self.assertAlmostEqual(length, 1, delta=0.2)
        out, _ = self.render(overlays=[{"kind": "video", "source": self.red, "start": 0,
                                        "end": 1, "scale": 0.5, "remove_bg": True}])
        self.assertLess(pixel(out, 0.5, 0.5)[0], 130)             # no person: layer vanishes


@unittest.skipUnless(tts.voices(), "no speech voice on this computer")
class Speech(unittest.TestCase):
    def test_words_become_sound(self):
        with tempfile.TemporaryDirectory() as folder:
            out = tts.speak('Hello there. "$(Remove-Item x)"', Path(folder) / "a.wav", rate=99)
            self.assertGreater(ingest.length_of(out), 0.5)
            spoken = editortools.speak(folder, "Winning round")        # what the button does
            self.assertGreater(spoken["duration"], 0.3)


@unittest.skipIf(cv2 is None, "OpenCV is not installed")
class Buttons(Base):
    """What the editor's helper buttons do (app/editortools.py)."""

    def test_tracking_returns_keyframes_where_the_target_goes(self):
        # A detailed square moves right across a plain background.
        moving = self.dir / "target.mp4"
        subprocess.run(
            ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "color=c=gray:s=640x360:d=2:r=30",
             "-f", "lavfi", "-i", "testsrc2=s=80x80:d=2:r=30", "-filter_complex",
             "[0:v][1:v]overlay=x='100+150*t':y=140", "-pix_fmt", "yuv420p", str(moving)],
            check=True)
        # 640x360 on a 16:9 canvas: shares are the same in the source and the canvas.
        box = {"kind": "sticker", "source": "box", "start": 0, "end": 1.8,
               "x": 140 / 640, "y": 0.5, "scale": 60 / 640}
        timeline = {"aspect": "16:9", "overlays": [box],
                    "segments": [{"source": str(moving), "start": 0, "end": 2}]}
        found = editortools.track(timeline, 0, log=lambda m: None)
        self.assertGreater(found["found"], 0.9)
        self.assertAlmostEqual(found["keyframes"][-1]["x"], (140 + 150 * 1.8) / 640, delta=0.04)
        with self.assertRaisesRegex(ValueError, "plain piece"):
            editortools.track({**timeline, "segments": [{**timeline["segments"][0],
                                                         "reverse": True}]}, 0)

    def test_canvas_and_source_positions_convert_both_ways(self):
        seg = {"zoom": 1.5, "pan_x": 0.5, "pan_y": -0.2}
        to_source, to_canvas, _ = editortools.mapping(1080, 1920, 1920, 1080, seg, "crop")
        back = to_canvas(*to_source(0.3, 0.7))
        self.assertAlmostEqual(back[0], 0.3)
        self.assertAlmostEqual(back[1], 0.7)

    def test_compound_clip_joins_neighbours_only(self):
        timeline = {"aspect": "16:9", "segments": [
            {"source": self.grey, "start": 0, "end": 1}, {"source": self.grey, "start": 1, "end": 2},
            {"source": self.grey, "start": 2, "end": 3}]}
        made = editortools.compound(self.dir, timeline, [0, 1], log=lambda m: None)
        self.assertAlmostEqual(made["duration"], 2, delta=0.3)
        self.assertTrue(Path(made["path"]).is_file())
        with self.assertRaises(ValueError):
            editortools.compound(self.dir, timeline, [0, 2])

    def test_caption_times_follow_a_speed_curve(self):
        self.assertAlmostEqual(editor_extras.curve_time("hero", 4, 4),
                               4 * editor_extras.curve_factor("hero"))
        self.assertLess(editor_extras.curve_time("flash in", 1, 4), 0.5)


class SpeechChecks(unittest.TestCase):
    def test_empty_text_is_refused(self):
        with self.assertRaises(ValueError):
            tts.speak("   ", Path("never.wav"))


if __name__ == "__main__":
    unittest.main()
