"""
test_localai.py - automatic checks for the built-in offline AI and the speech fallback.

WHY it exists:
    The real engine and models are too big for a quick test. So we use a tiny fake "model file"
    served by a local web server, and a pretend llama-server (a small Python script) that
    answers like the real one. The REAL engine is tried by packaging/test_engine.py.
HOW it works:
    Run:  python -m unittest tests.test_localai -v
    (The tests that start the pretend engine are skipped on Windows, because Windows cannot
    start a .py file as a program.)
HOW TO IMPROVE:
    Add a test where the disk is full.
"""

import hashlib
import json
import os
import stat
import sys
import tempfile
import threading
import time
import types
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from shortsforge import transcribe
from shortsforge.app import assistant, localai, server
from shortsforge.app.settings import Settings

CONTENT = os.urandom(300_000)                      # our pretend model file

FAKE_ENGINE = '''#!{python}
import json, os, sys, time
from http.server import BaseHTTPRequestHandler, HTTPServer
args = sys.argv[1:]
if os.environ.get("FAKE_ENGINE_CRASH"):
    sys.exit(3)
port = int(args[args.index("--port") + 1])
class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def send(self, data, code=200):
        raw = json.dumps(data).encode()
        self.send_response(code); self.send_header("Content-Length", str(len(raw)))
        self.end_headers(); self.wfile.write(raw)
    def do_GET(self):
        self.send({{"status": "ok"}})
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if self.headers["Authorization"] != "Bearer " + os.environ["LLAMA_API_KEY"]:
            return self.send({{"error": "no"}}, 401)
        if body.get("tools") and body["messages"][-1]["role"] != "tool":
            msg = {{"content": None, "tool_calls": [{{"id": "1", "type": "function",
                   "function": {{"name": "list_projects", "arguments": "{{}}"}}}}]}}
        else:
            msg = {{"content": "<think>secret</think>You have no projects."}}
        self.send({{"choices": [{{"message": msg}}]}})
HTTPServer(("127.0.0.1", port), H).serve_forever()
'''


class Files(BaseHTTPRequestHandler):
    """Serves CONTENT and understands "Range" (resume), like the real download site."""
    ranges = []

    def log_message(self, *a):
        pass

    def do_GET(self):
        start = 0
        header = self.headers.get("Range")
        Files.ranges.append(header)
        if header:
            start = int(header[6:].rstrip("-"))
        data = CONTENT[start:]
        self.send_response(206 if header else 200)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.web = ThreadingHTTPServer(("127.0.0.1", 0), Files)
        threading.Thread(target=cls.web.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.web.shutdown()
        cls.web.server_close()

    def setUp(self):
        Files.ranges = []
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.entry = {"label": "Test", "note": "n", "file": "test.gguf", "size": len(CONTENT),
                      "sha256": hashlib.sha256(CONTENT).hexdigest(),
                      "url": f"http://127.0.0.1:{self.web.server_address[1]}/m"}
        self.ai = localai.LocalAI(self.root / "ai", {"test": self.entry})
        self.addCleanup(self.ai.stop)

    def download(self):
        self.ai.start_download("test")
        for _ in range(200):
            state = self.ai.status()["download"]
            if state["state"] not in ("downloading", "checking"):
                return state
            time.sleep(0.05)
        self.fail("download did not finish")


class Download(Base):
    def test_download_is_verified(self):
        self.assertFalse(self.ai.installed("test"))
        self.assertEqual(self.download()["state"], "done")
        self.assertTrue(self.ai.installed("test"))
        self.assertEqual(self.ai.model_path("test").read_bytes(), CONTENT)
        with self.assertRaises(localai.LocalAIError):
            self.ai.start_download("test")                     # already there

    def test_resumes_a_partial_file(self):
        self.ai.dir.mkdir(parents=True)
        (self.ai.dir / "test.gguf.part").write_bytes(CONTENT[:1000])
        self.assertEqual(self.download()["state"], "done")
        self.assertEqual(Files.ranges, ["bytes=1000-"])
        self.assertEqual(self.ai.model_path("test").read_bytes(), CONTENT)

    def test_wrong_checksum_is_thrown_away(self):
        self.entry["sha256"] = "0" * 64
        state = self.download()
        self.assertEqual(state["state"], "error")
        self.assertIn("safety check", state["error"])
        self.assertEqual(list(self.ai.dir.iterdir()), [])

    def test_remove_and_unknown_model(self):
        self.download()
        self.ai.remove("test")
        self.assertFalse(self.ai.installed("test"))
        for bad in ("nope", "../x"):
            with self.assertRaises(localai.LocalAIError):
                self.ai.start_download(bad)


class Catalogue(unittest.TestCase):
    def test_entries_are_complete(self):
        self.assertIn(localai.DEFAULT_MODEL, localai.MODELS)
        for entry in localai.MODELS.values():
            self.assertRegex(entry["sha256"], r"^[0-9a-f]{64}$")
            self.assertRegex(entry["url"], r"^https://huggingface\.co/.+/resolve/[0-9a-f]{40}/")
            self.assertGreater(entry["size"], 10 ** 9)

    def test_engine_command_is_private(self):
        command = localai.LocalAI("x").command("llama-server", "qwen3.5-4b", 1234)
        self.assertEqual(command[command.index("--host") + 1], "127.0.0.1")
        self.assertIn("--jinja", command)
        self.assertNotIn("--api-key", command)                 # the password is not on show

    def test_settings(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = Settings(Path(tmp) / "s.json")
            ready = set()
            settings.local_ready = ready.__contains__
            settings.update({"provider": "builtin"})
            self.assertFalse(settings.configured())
            ready.add("qwen3.5-9b")
            self.assertTrue(settings.configured())
            self.assertEqual(Settings(Path(tmp) / "s.json").data["provider"], "builtin")


class Routes(Base):
    def setUp(self):
        super().setUp()
        self.state = server.AppState(self.root / "out")
        self.state.local_ai = self.ai
        self.state.settings.local_ready = self.ai.installed
        self.doors = []
        for lan in (False, True):
            httpd = server.make_server(self.state, 0, lan=lan)
            threading.Thread(target=httpd.serve_forever, daemon=True).start()
            self.addCleanup(httpd.server_close)
            self.addCleanup(httpd.shutdown)
            self.doors.append(f"http://127.0.0.1:{httpd.server_address[1]}")

    def call(self, door, body=None):
        request = urllib.request.Request(
            self.doors[door] + "/api/localai", data=json.dumps(body).encode() if body else None,
            headers={"X-Token": self.state.token})
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as err:
            return err.code, json.loads(err.read())

    def test_status_download_and_errors(self):
        code, data = self.call(0)
        self.assertEqual((code, data["models"][0]["installed"]), (200, False))
        self.assertEqual(self.call(0, {"action": "download", "model": "test"})[0], 200)
        for _ in range(100):
            if self.call(0)[1]["models"][0]["installed"]:
                break
            time.sleep(0.05)
        self.assertTrue(self.call(0)[1]["models"][0]["installed"])
        self.assertEqual(self.call(0, {"action": "download", "model": "zzz"})[0], 400)
        self.assertEqual(self.call(0, {"action": "boom", "model": "test"})[0], 400)

    def test_phone_cannot_manage_models(self):
        self.assertEqual(self.call(1)[0], 403)
        self.assertEqual(self.call(1, {"action": "download", "model": "test"})[0], 403)


@unittest.skipIf(os.name == "nt", "the pretend engine is a script; Windows needs a real .exe")
class Engine(Base):
    def setUp(self):
        super().setUp()
        script = self.root / "llama-server"
        script.write_text(FAKE_ENGINE.format(python=sys.executable))
        script.chmod(script.stat().st_mode | stat.S_IEXEC)
        patch = mock.patch.dict(os.environ, {"SHORTSFORGE_LLAMA_SERVER": str(script)})
        patch.start()
        self.addCleanup(patch.stop)
        self.download()
        self.state = server.AppState(self.root / "out")
        self.state.local_ai = self.ai
        self.state.settings.local_ready = self.ai.installed
        self.state.settings.update({"provider": "builtin", "builtin": {"model": "test"}})

    def test_chat_uses_tools_and_hides_thinking(self):
        reply, actions = assistant.ask(self.state.settings, [], "what do I have?",
                                       assistant.ToolBox(self.state))
        self.assertEqual(reply, "You have no projects.")
        self.assertEqual(actions, ["Looked at your projects"])
        first = self.ai.process
        assistant.ping(self.state.settings, self.ai)
        self.assertIs(self.ai.process, first)                  # engine is reused, not restarted
        self.ai.stop()
        self.assertIsNotNone(first.poll())

    def test_idle_engine_is_stopped_but_not_during_a_chat(self):
        self.ai.idle_seconds = 0.4
        self.ai.busy(True)
        self.ai.ensure_running("test")
        process = self.ai.process
        time.sleep(1.2)
        self.assertIsNone(process.poll())                      # busy: still running
        self.ai.busy(False)
        for _ in range(100):
            if process.poll() is not None:
                break
            time.sleep(0.05)
        self.assertIsNotNone(process.poll())

    def test_crash_gives_a_friendly_error(self):
        with mock.patch.dict(os.environ, {"FAKE_ENGINE_CRASH": "1"}):
            with self.assertRaises(assistant.AssistantError) as caught:
                assistant.ping(self.state.settings, self.ai)
        self.assertIn("stopped while loading", str(caught.exception))


class SpeechFallback(unittest.TestCase):
    def test_graphics_card_failure_uses_processor(self):
        devices = []

        class Model:
            def __init__(self, name, device, compute_type):
                self.device = device

            def transcribe(self, *args, **kwargs):
                devices.append(self.device)

                def segments():
                    if self.device != "cpu":
                        raise RuntimeError("Library cublas64_12.dll is not found")
                    yield types.SimpleNamespace(start=0, end=1, text=" Hi ", words=[])
                return segments(), types.SimpleNamespace(language="en")

        fake = types.ModuleType("faster_whisper")
        fake.WhisperModel = Model
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(sys.modules,
                                                                   {"faster_whisper": fake}):
            result = transcribe.transcribe(Path("v.mp4"), Path(tmp))
        self.assertEqual(devices, ["auto", "cpu"])
        self.assertEqual(result["segments"][0]["text"], "Hi")


if __name__ == "__main__":
    unittest.main()
