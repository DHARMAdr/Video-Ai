"""
test_editor.py - tests the video editor, Forge's new controls and voice typing.

HOW: small drawn test videos are really rendered with ffmpeg; the speech model is replaced by a
stand-in (the real one is tested in the Windows build).
HOW TO IMPROVE: compare pixels to prove each filter changes the picture the intended way.
"""

import json
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from shortsforge import editor, ingest
from shortsforge.app import edits, library, router, server, voice
from shortsforge.app.assistant import CHANGING_TOOLS, TOOLS, ToolBox
from shortsforge.app.memory import Memory


def make_video(path: Path, seconds: int, audio: bool = True) -> None:
    command = ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
               f"testsrc2=s=640x360:r=30:d={seconds}"]
    if audio:
        command += ["-f", "lavfi", "-i", f"sine=frequency=440:d={seconds}", "-shortest"]
    subprocess.run(command + ["-pix_fmt", "yuv420p", "-c:v", "libx264", "-preset", "ultrafast",
                              str(path)], check=True)


@unittest.skipUnless(shutil.which("ffmpeg"), "needs ffmpeg")
class EditorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        cls.a, cls.b = cls.tmp / "a.mp4", cls.tmp / "b silent.mp4"
        make_video(cls.a, 4)
        make_video(cls.b, 4, audio=False)
        cls.song = cls.tmp / "song.wav"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=f=200:d=2",
                        str(cls.song)], check=True)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def seg(self, path, **extra):
        return {"source": str(path), "start": 0, "end": 2, **extra}

    def test_every_filter_effect_and_transition_renders(self):
        """One small render per choice: a typo in any ffmpeg filter would fail here."""
        out = self.tmp / "x.mp4"
        short = {"source": str(self.a), "start": 0, "end": 0.6}
        for name in editor.FILTERS:
            editor.render({"segments": [{**short, "filter": name}]}, out, log=lambda *_: None,
                          preview=True)
        for name in editor.EFFECTS:
            editor.render({"segments": [{**short, "effect": name}]}, out, log=lambda *_: None,
                          preview=True)
        for name in editor.TRANSITIONS[1:]:
            editor.render({"segments": [short, short],
                           "transition": {"type": name, "seconds": 0.2}}, out,
                          log=lambda *_: None, preview=True)

    def test_a_full_edit_has_the_right_size_and_length(self):
        out = self.tmp / "full.mp4"
        timeline = {"aspect": "9:16", "fit": "blur",
                    "transition": {"type": "fade", "seconds": 0.5},
                    "segments": [self.seg(self.a, speed=2, mirror=True, zoom=1.5, rotate=90),
                                 self.seg(self.b, speed=0.5, reverse=True, fade_in=0.3,
                                          fade_out=0.3, saturation=1.4)],
                    "texts": [{"text": "GG {\\b1} WP", "start": 0, "end": 2, "style": "box"}],
                    "music": {"path": str(self.song), "volume": 0.5}}
        seconds = editor.render(timeline, out, log=lambda *_: None)
        info = ingest.probe(out)
        self.assertEqual((info["width"], info["height"]), (1080, 1920))
        self.assertAlmostEqual(seconds, 1 + 4 - 0.45, delta=0.3)
        self.assertTrue(info["has_audio"])

    def test_layers_keyframes_captions_and_range(self):
        """Picture, sticker, video-on-top, green screen, keyframes, freeze, sound and marks."""
        picture = self.tmp / "pic.png"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=green:s=200x200",
                        "-frames:v", "1", str(picture)], check=True)
        layer = {"start": 0.2, "end": 2.0, "fade_in": 0.2, "fade_out": 0.2}
        timeline = {
            "resolution": 720, "fps": 60,
            "segments": [self.seg(self.a, keyframes=[{"t": 0, "zoom": 1}, {"t": 1.5, "zoom": 2, "pan_x": 1}]),
                         self.seg(self.a, freeze=1.0),
                         self.seg(self.b, disabled=True)],
            "overlays": [
                {"kind": "image", "source": str(picture), "chroma": "008000", "rotate": 30, "opacity": 0.5, **layer},
                {"kind": "sticker", "source": "arrow", "keyframes": [{"t": 0, "x": 0.1, "y": 0.1, "scale": 0.1},
                                                                    {"t": 1, "x": 0.9, "y": 0.8, "scale": 0.5},
                                                                    {"t": 1.5, "x": 0.5, "y": 0.5, "scale": 0.2}], **layer},
                {"kind": "video", "source": str(self.a), "volume": 0.8, "mirror": True, **layer}],
            "audio": [{"path": str(self.song), "start": 0.5, "end": 2.5, "fade_in": 0.2, "fade_out": 0.2}],
            "texts": [{"text": "a", "start": 0, "end": 2, "anim": name} for name in editor.TEXT_ANIMATIONS],
            "music": {"path": str(self.song)}}
        out = self.tmp / "layers.mp4"
        seconds = editor.render(timeline, out, log=lambda *_: None)
        info = ingest.probe(out)
        self.assertEqual((info["width"], info["height"]), (720, 1280))
        self.assertAlmostEqual(seconds, 3.0, delta=0.25)
        for name in editor.layers.STICKERS:
            editor.render({"segments": [self.seg(self.a, end=0.6)], "overlays": [
                {"kind": "sticker", "source": name, "start": 0, "end": 0.5}]}, out,
                log=lambda *_: None, preview=True)
        timeline["range"] = {"in": 0.5, "out": 1.7}
        self.assertAlmostEqual(editor.render(timeline, out, log=lambda *_: None, preview=True),
                               1.2, delta=0.2)
        with self.assertRaises(ValueError):
            editor.clean({"segments": [self.seg(self.a)], "overlays": [{"kind": "image", "source": "/etc/passwd"}]})
        with self.assertRaises(ValueError):
            editor.clean({"segments": [self.seg(self.a)], "audio": [{"path": "/etc/passwd"}]})

    def test_auto_captions_follow_the_timeline(self):
        spoken = [{"word": w, "start": 1.0 + i * 0.4, "end": 1.3 + i * 0.4}
                  for i, w in enumerate(["one", "two", "three", "four"])]
        plan = editor.clean({"segments": [self.seg(self.a, start=1, end=3, speed=2),
                                          self.seg(self.b, start=1, end=3)]})
        result = edits.captions(self.tmp / "cap", plan, log=lambda *_: None,
                                transcriber=lambda v, w: {"segments": [{"words": spoken}]})
        self.assertEqual(result[0]["text"], "one two three")
        self.assertEqual(result[0]["start"], 0.0)
        self.assertTrue(any(c["start"] >= 1.0 for c in result))     # the second piece's words

    def test_bad_input_is_refused_or_made_safe(self):
        with self.assertRaises(ValueError):
            editor.clean({"segments": []})
        with self.assertRaises(ValueError):
            editor.clean({"segments": [{"source": "/nope.mp4", "start": 0, "end": 2}]})
        plan = editor.clean({"segments": [self.seg(self.a, speed=99, zoom="x",
                                                   filter="';rm -rf")]})
        self.assertEqual((plan["segments"][0]["speed"], plan["segments"][0]["zoom"],
                          plan["segments"][0]["filter"]), (4.0, 1.0, "none"))
        text = editor.build_text_file([{"text": "{\\an1}hi", "start": 0, "end": 1, "x": .5,
                                        "y": .5, "size": 40, "color": "ff0000",
                                        "style": "outline", "pop": False}], 100, 100)
        self.assertIn("(/an1)hi", text)

    def _state(self):
        state = server.AppState(self.tmp / f"app{time.time_ns()}")
        project = state.out_dir / "Match"
        (project / "clips").mkdir(parents=True)
        entries = []
        for n in (1, 2, 3):
            shutil.copy(self.a, project / "clips" / f"short_0{n}.mp4")
            entries.append({"file": f"short_0{n}.mp4", "start": 0, "end": 4, "title": f"T{n}"})
        (project / "shorts.json").write_text(json.dumps(entries))
        return state, project

    def _wait(self, state, job_id):
        for _ in range(600):
            snap = state.jobs.snapshot(job_id)
            if snap["status"] != "running":
                self.assertEqual(snap["status"], "done", snap["error"])
                return snap["result"]
            time.sleep(0.2)
        self.fail("job did not finish")

    def test_delete_restore_and_edit_by_words(self):
        state, project = self._state()
        memory = Memory(state.out_dir / "m.json")

        def say(text):
            box = ToolBox(state)
            reply, _ = router.execute(router.parse(text), box, memory)
            return reply, box

        titles = lambda: [e["title"] for e in json.loads((project / "shorts.json").read_text())]
        say("delete clip 2")
        self.assertEqual(titles(), ["T1", "T3"])
        say("restore the clip")
        self.assertEqual(titles(), ["T1", "T3", "T2"])
        self.assertTrue((project / "clips" / "short_02.mp4").exists())

        reply, box = say("join clips 1 and 3 and make them black and white")
        self.assertIn("Started", reply)
        result = self._wait(state, box.started_jobs[0])
        self.assertEqual(result["project_name"], "Edits")
        self.assertTrue((state.out_dir / result["file"]).exists())
        self.assertEqual(titles(), ["T1", "T3", "T2"])           # originals untouched

        reply, box = say("add text \"WOW\" to clip 1")
        self._wait(state, box.started_jobs[0])
        self.assertEqual(len(json.loads((state.out_dir / "Edits" / "shorts.json").read_text())), 2)

    def test_router_understands_app_control(self):
        self.assertEqual(router.parse("open the editor"), {"intent": "screen", "screen": "editor"})
        self.assertEqual(router.parse("dark mode"), {"intent": "theme", "theme": "dark"})
        edit = router.parse("make clip 2 slow motion with glitch")
        self.assertEqual(edit["changes"], {"speed": 0.5, "effect": "glitch"})
        self.assertEqual(router.parse("trim clip 2 to 0:40-1:10")["intent"], "trim")
        self.assertEqual(router.parse("list my videos")["intent"], "show")

    def test_forge_tools_control_the_window_safely(self):
        state, _ = self._state()
        box = ToolBox(state)
        names = {t["name"] for t in TOOLS}
        for name in names:
            self.assertTrue(hasattr(box, "t_" + name), name)
            self.assertIn(name, box.labels, name)
        for name in ("edit_clips", "delete_clip", "learn_kills", "set_options"):
            self.assertIn(name, CHANGING_TOOLS)
        box.run("open_screen", {"screen": "teach"})
        box.run("set_options", {"mode": "game", "count": 3})
        self.assertEqual([a["do"] for a in box.ui], ["open", "options"])
        phone = ToolBox(state, remote=True)
        for name, args in (("troubleshoot", {}), ("open_folder", {"project": "Match"}),
                           ("open_screen", {"screen": "settings"})):
            self.assertIn("error", json.loads(phone.run(name, args)[0]), name)
        after_search = ToolBox(state)
        after_search.searches = 1
        self.assertIn("error", json.loads(after_search.run("delete_clip", {
            "project": "Match", "clip_number": 1})[0]))

    def test_editor_and_voice_routes(self):
        state, _ = self._state()
        httpd = server.make_server(state)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{state.port}"

        def call(path, data=None):
            request = urllib.request.Request(base + path, data=data,
                                             headers={"X-Token": state.token})
            return json.loads(urllib.request.urlopen(request, timeout=60).read())
        try:
            self.assertIn("filters", call("/api/editor"))
            timeline = {"segments": [self.seg(self.a)]}
            call("/api/editor", json.dumps({"action": "save", "timeline": timeline}).encode())
            self.assertEqual(call("/api/editor")["draft"], timeline)
            job = call("/api/editor", json.dumps({"action": "preview",
                                                  "timeline": timeline}).encode())["job"]
            self.assertEqual(self._wait(state, job)["file"], "_editor/preview.mp4")

            class Words:
                text = "make five shorts"

            class Model:
                def transcribe(self, *a, **k):
                    return [Words()], None
            with mock.patch.object(voice, "_model", Model()):
                self.assertEqual(call("/api/voice", b"x" * 5000)["text"], "make five shorts")
            with self.assertRaises(urllib.error.HTTPError):
                call("/api/voice", b"x")
            # the settings file (API key) cannot be read, however the path is spelled
            (state.out_dir / "_settings.json").write_text("{}")
            for path in ("_settings.json", "./_settings.json", "Match/../_settings.json"):
                with self.assertRaises(urllib.error.HTTPError, msg=path):
                    call("/files/" + path.replace("..", "%2E%2E"))
        finally:
            httpd.shutdown()
            httpd.server_close()


if __name__ == "__main__":
    unittest.main()
