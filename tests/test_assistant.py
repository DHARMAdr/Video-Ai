"""
test_assistant.py - automatic checks for the AI assistant, settings, phone access and uploads.

WHY it exists:
    The assistant talks to an AI over the internet, which we cannot do in a test. So we start TWO
    tiny FAKE AI servers on this computer (one that speaks Anthropic's format, one that speaks the
    OpenAI format) and check that our code talks to them correctly: sends the key, runs the tools
    the "AI" asks for, and handles errors.
HOW it works:
    Run:  python -m unittest tests.test_assistant -v
HOW TO IMPROVE:
    Add a test for very long chats, and for an AI that keeps calling tools forever.
"""

import json
import shutil
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from shortsforge.app import assistant, lan, server
from shortsforge.app.settings import Settings


# ---------------------------------------------------------------------------
# Fake AI servers
# ---------------------------------------------------------------------------
SEEN = {"anthropic_headers": None, "openai_headers": None, "requests": []}
MODE = {"openai_no_tools": False}


class FakeAI(BaseHTTPRequestHandler):
    """Answers like Anthropic (/v1/messages) or OpenAI (/v1/chat/completions)."""

    def log_message(self, *a):
        pass

    def _reply(self, status, data):
        raw = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        SEEN["requests"].append((self.path, body))
        if self.path.endswith("/messages"):
            SEEN["anthropic_headers"] = dict(self.headers)
            if self.headers.get("x-api-key") != "sk-good":
                return self._reply(401, {"error": {"message": "bad key"}})
            last = body["messages"][-1]
            got_result = isinstance(last["content"], list) and last["content"][0].get("type") == "tool_result"
            if got_result:
                return self._reply(200, {"content": [{"type": "text", "text": "Tool said: " + last["content"][0]["content"][:60]}]})
            text = last["content"] if isinstance(last["content"], str) else ""
            if "projects" in text:
                return self._reply(200, {"content": [
                    {"type": "text", "text": "Let me look."},
                    {"type": "tool_use", "id": "tu_1", "name": "list_projects", "input": {}}]})
            return self._reply(200, {"content": [{"type": "text", "text": "Hello from fake Claude"}]})
        if self.path.endswith("/chat/completions"):
            SEEN["openai_headers"] = dict(self.headers)
            if MODE["openai_no_tools"] and "tools" in body:
                return self._reply(400, {"error": {"message": "registry.ollama.ai/x does not support tools"}})
            last = body["messages"][-1]
            if last["role"] == "tool":
                return self._reply(200, {"choices": [{"message": {"content": "Tool said: " + last["content"][:60]}}]})
            if "projects" in str(last["content"]):
                return self._reply(200, {"choices": [{"message": {"content": None, "tool_calls": [
                    {"id": "c1", "type": "function", "function": {"name": "list_projects", "arguments": "{}"}}]}}]})
            return self._reply(200, {"choices": [{"message": {"content": "Hello from fake OpenAI"}}]})
        self._reply(404, {})


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        cls.ai = ThreadingHTTPServer(("127.0.0.1", 0), FakeAI)
        threading.Thread(target=cls.ai.serve_forever, daemon=True).start()
        cls.ai_url = f"http://127.0.0.1:{cls.ai.server_address[1]}"
        cls.state = server.AppState(cls.tmp / "out")
        # A fake finished project with a transcript, so the tools have something to read.
        proj = cls.state.out_dir / "demo"
        proj.mkdir()
        (proj / "work").mkdir()
        words = [{"word": w, "start": 10 + i * 0.5, "end": 10.4 + i * 0.5}
                 for i, w in enumerate("Today we talk about cooking pasta. Boil water first.".split())]
        (proj / "work" / "transcript.json").write_text(json.dumps(
            {"segments": [{"start": 10, "end": 15, "text": "x", "words": words}]}))
        (proj / "shorts.json").write_text(json.dumps(
            [{"title": "Pasta tips", "start": 10, "end": 30, "score": {"total": 80}, "file": "short_01.mp4"}]))
        (proj / "project.json").write_text(json.dumps(
            {"mode": "talk", "video": "/videos/cook.mp4", "duration": 100,
             "words_file": str(proj / "work" / "transcript.json")}))
        cls.httpd = server.make_server(cls.state)
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.state.port}"

    @classmethod
    def tearDownClass(cls):
        server.stop_lan(cls.state)
        cls.httpd.shutdown()
        cls.ai.shutdown()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def call(self, path, body=None, base=None, headers=None, raw=None, token=True):
        request = urllib.request.Request(
            (base or self.base) + path,
            data=raw if raw is not None else (None if body is None else json.dumps(body).encode()),
            method="GET" if body is None and raw is None else "POST")
        if token:
            request.add_header("X-Token", self.state.token)
        for k, v in (headers or {}).items():
            request.add_header(k, v)
        try:
            with urllib.request.urlopen(request, timeout=20) as r:
                return r.status, json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as err:
            return err.code, json.loads(err.read() or b"{}")


class Settings_(Base):
    def test_keys_hidden_and_unchanged(self):
        st = Settings(self.tmp / "s.json")
        st.update({"anthropic": {"api_key": "sk-secret-1234"}})
        shown = st.public()["anthropic"]["api_key"]
        self.assertNotIn("secret", shown)
        self.assertTrue(shown.endswith("1234"))
        st.update({"anthropic": {"api_key": shown}})                # window sends dots back
        self.assertEqual(st.data["anthropic"]["api_key"], "sk-secret-1234")

    def test_settings_route_never_leaks_key(self):
        self.call("/api/settings", {"provider": "anthropic", "anthropic": {"api_key": "sk-abcdef9999"}})
        code, data = self.call("/api/settings")
        self.assertEqual(code, 200)
        self.assertNotIn("abcdef", json.dumps(data))
        code, _ = self.call("/files/_settings.json")                 # and the file is not downloadable
        self.assertEqual(code, 403)


class Chat(Base):
    def setUp(self):
        SEEN["requests"].clear()
        MODE["openai_no_tools"] = False

    def configure(self, provider):
        if provider == "anthropic":
            self.call("/api/settings", {"provider": "anthropic", "anthropic": {
                "api_key": "sk-good", "model": "claude-test", "base_url": self.ai_url + "/v1/messages"}})
        else:
            self.call("/api/settings", {"provider": "openai", "openai": {
                "base_url": self.ai_url + "/v1", "api_key": "k", "model": "m"}})
        self.call("/api/chat/clear", {})

    def test_anthropic_plain_and_tool_loop(self):
        self.configure("anthropic")
        code, data = self.call("/api/chat", {"text": "hi there"})
        self.assertEqual((code, data["reply"]), (200, "Hello from fake Claude"))
        self.assertEqual({k.lower(): v for k, v in SEEN["anthropic_headers"].items()}["x-api-key"], "sk-good")
        code, data = self.call("/api/chat", {"text": "tell me about my projects"})
        self.assertIn("demo", data["reply"])                         # the real tool result reached the AI
        self.assertEqual(data["actions"], ["Looked at your projects"])
        code, saved = self.call("/api/chat")
        self.assertEqual(len(saved["messages"]), 4)                  # history is stored

    def test_wrong_key_gives_friendly_error(self):
        self.call("/api/settings", {"provider": "anthropic", "anthropic": {
            "api_key": "sk-bad", "model": "m", "base_url": self.ai_url + "/v1/messages"}})
        code, data = self.call("/api/chat", {"text": "hi"})
        self.assertEqual(code, 400)
        self.assertIn("API key", data["error"])

    def test_openai_tool_loop(self):
        self.configure("openai")
        code, data = self.call("/api/chat", {"text": "tell me about my projects"})
        self.assertIn("demo", data["reply"])
        self.assertEqual(SEEN["openai_headers"]["Authorization"], "Bearer k")

    def test_openai_model_without_tools_falls_back(self):
        MODE["openai_no_tools"] = True
        self.configure("openai")
        code, data = self.call("/api/chat", {"text": "hi"})
        self.assertEqual(code, 200)
        self.assertIn("Hello from fake OpenAI", data["reply"])
        self.assertIn("cannot operate the app", data["reply"])

    def test_not_configured_commands_still_work(self):
        self.call("/api/settings", {"provider": "anthropic", "anthropic": {"api_key": ""}})
        code, data = self.call("/api/chat", {"text": "hi"})          # open question: needs an AI
        self.assertEqual(code, 200)
        self.assertIn("Settings", data["reply"])
        code, data = self.call("/api/chat", {"text": "show my projects"})  # command: no AI needed
        self.assertEqual(data["via"], "rules")
        self.assertIn("demo", data["reply"])

    def test_connection_test_route(self):
        self.configure("anthropic")
        code, data = self.call("/api/settings/test", {})
        self.assertTrue(data["ok"])


class Tools(Base):
    def setUp(self):
        self.tb = assistant.ToolBox(self.state)

    def run_tool(self, tool, **args):
        text, label = self.tb.run(tool, args)
        return json.loads(text), label

    def test_get_project(self):
        data, _ = self.run_tool("get_project", name="demo")
        self.assertEqual(data["clips"][0]["title"], "Pasta tips")
        self.assertEqual(data["clips"][0]["number"], 1)

    def test_search_and_read_transcript(self):
        data, _ = self.run_tool("search_transcript", project="demo", query="pasta")
        self.assertEqual(len(data["matches"]), 1)
        self.assertIn("pasta", data["matches"][0]["text"].lower())
        data, _ = self.run_tool("get_transcript", project="demo", start_seconds=10, end_seconds=20)
        self.assertIn("cooking", data["text"])

    def test_bad_inputs_are_errors_not_crashes(self):
        for name, args in [("get_project", {"name": "../../etc"}), ("get_project", {"name": "nope"}),
                           ("nonexistent_tool", {}), ("trim_clip", {"project": "demo"}),
                           ("search_transcript", {"project": "demo", "query": "?"})]:
            data, _ = self.run_tool(name, **args)
            self.assertIn("error", data, name)

    def test_make_shorts_refuses_unknown_paths(self):
        data, _ = self.run_tool("make_shorts", source="/etc/passwd", mode="talk")
        self.assertFalse(data["started"])

    def test_trim_validates_length(self):
        data, _ = self.run_tool("trim_clip", project="demo", clip_number=1, start_seconds=10, end_seconds=400)
        self.assertIn("error", data)


class PhoneAndUpload(Base):
    def test_upload_and_safe_names(self):
        code, data = self.call("/api/upload", raw=b"\x00" * 2048, headers={"X-Filename": "../../my clip!.mp4"})
        self.assertEqual(code, 200)
        saved = Path(data["path"])
        self.assertTrue(saved.is_file())
        self.assertEqual(saved.parent, (self.state.out_dir / "_uploads"))
        code, data = self.call("/api/upload", raw=b"abc", headers={"X-Filename": "virus.exe"})
        self.assertEqual(code, 400)

    def test_phone_door(self):
        self.assertEqual(self.call("/api/lan")[1]["enabled"], False)
        code, status = self.call("/api/lan", {"enabled": True})
        self.assertTrue(status["enabled"])
        port = self.state.lan_port
        base = f"http://127.0.0.1:{port}"
        # a public-looking Host name is refused by the phone door
        self.assertEqual(self.call("/api/info", base=base, headers={"Host": "8.8.8.8"})[0], 403)
        self.assertEqual(self.call("/api/info", base=base, headers={"Host": "evil.example.com"})[0], 403)
        # but a private Host header is accepted when the token is right
        code, info = self.call("/api/info", base=base, headers={"Host": f"192.168.1.5:{port}"})
        self.assertEqual(code, 200)
        self.assertTrue(info["remote"])
        # wrong token -> refused
        code, _ = self.call("/api/info", base=base, headers={"Host": "192.168.1.5", "X-Token": "x"}, token=False)
        self.assertEqual(code, 403)
        # PC-only actions are refused from the phone
        for path, body in [("/api/settings", {"name": "x"}), ("/api/open_folder", {"project": "demo"}),
                           ("/api/pick", {})]:
            code, _ = self.call(path, body, base=base, headers={"Host": f"192.168.1.5:{port}"})
            self.assertEqual(code, 403, path)
        self.assertEqual(self.call("/api/settings", base=base, headers={"Host": "192.168.1.5"})[0], 403)
        # a phone may not point at any file on the PC
        code, data = self.call("/api/start", {"source": __file__, "mode": "talk"}, base=base,
                               headers={"Host": f"192.168.1.5:{port}"})
        self.assertEqual(code, 400)
        self.assertIn("uploaded", data["error"])
        code, status = self.call("/api/lan", {"enabled": False})
        self.assertFalse(status["enabled"])
        self.assertIsNone(self.state.lan_server)

    def test_lan_helpers(self):
        self.assertTrue(lan.is_private_host("192.168.0.4"))
        self.assertTrue(lan.is_private_host("10.1.2.3"))
        self.assertFalse(lan.is_private_host("8.8.8.8"))
        self.assertFalse(lan.is_private_host("evil.com"))
        self.assertIn("<svg", lan.qr_svg("http://192.168.0.4:1234/?t=abc"))


if __name__ == "__main__":
    unittest.main()
