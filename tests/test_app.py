"""
test_app.py - automatic checks for the app window's server (the part behind the buttons).

WHY it exists:
    Proves that the window can start a job, follow its progress, play a clip (HTTP Range),
    export a clip again with a new length, and that the safety rules work (secret token,
    no reading files outside the output folder).
HOW it works:
    Starts the real server on a free port, creates the same FAKE kill-feed video as
    test_game.py, then talks to the server with plain HTTP like the window does.
    Run:  python -m unittest tests.test_app -v
HOW TO IMPROVE:
    Add a test for the 'talk' mode job (needs a transcript) and for error messages.
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

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from shortsforge.app import server
from test_game import make_fake_game


class AppServer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        cls.video = cls.tmp / "fake_valorant.mp4"
        make_fake_game(cls.video)
        cls.state = server.AppState(cls.tmp / "out")
        cls.httpd = server.make_server(cls.state)
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.state.port}"

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    # --- tiny HTTP helpers ---------------------------------------------------
    def call(self, path, body=None, token=True, headers=None):
        url = self.base + path
        data = None if body is None else json.dumps(body).encode()
        request = urllib.request.Request(url, data=data, method="GET" if body is None else "POST")
        if token:
            request.add_header("X-Token", self.state.token)
        for k, v in (headers or {}).items():
            request.add_header(k, v)
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                raw = response.read()
                return response.status, response.headers, raw
        except urllib.error.HTTPError as err:
            return err.code, err.headers, err.read()

    def wait_job(self, job_id, timeout=240):
        end = time.time() + timeout
        while time.time() < end:
            _, _, raw = self.call(f"/api/job?id={job_id}&since=0")
            job = json.loads(raw)
            if job["status"] != "running":
                return job
            time.sleep(0.5)
        self.fail("job did not finish")

    # --- tests ---------------------------------------------------------------
    def test_1_security(self):
        self.assertEqual(self.call("/api/info", token=False)[0], 403)            # no token
        self.assertEqual(self.call("/api/info", headers={"X-Token": "wrong"})[0], 403)
        status, _, raw = self.call("/api/info")
        self.assertEqual(status, 200)
        self.assertIn("version", json.loads(raw))
        # path traversal must be refused
        self.assertIn(self.call("/files/..%2F..%2Fetc%2Fpasswd")[0], (403, 404))
        self.assertIn(self.call("/files/%2Fetc%2Fpasswd")[0], (403, 404))
        # a wrong Host header (DNS-rebinding style) is refused
        self.assertEqual(self.call("/api/info", headers={"Host": "evil.example"})[0], 403)

    def test_2_page_is_served(self):
        status, headers, raw = self.call(f"/?t={self.state.token}", token=False)
        self.assertEqual(status, 200)
        self.assertIn(b"ShortsForge", raw)

    def test_3_game_job_then_edit_then_range(self):
        # missing file -> friendly 400
        status, _, raw = self.call("/api/start", {"mode": "game", "source": str(self.tmp / "nope.mp4")})
        self.assertEqual(status, 400)
        self.assertIn("File not found", json.loads(raw)["error"])

        # real job
        status, _, raw = self.call("/api/start", {
            "mode": "game", "source": f'"{self.video}"',            # quotes are cleaned up
            "options": {"count": 2, "layout": "stack", "facecam": [0, 0.7, 0.25, 0.3]}})
        self.assertEqual(status, 200, raw)
        job = self.wait_job(json.loads(raw)["job"])
        self.assertEqual(job["status"], "done", job.get("error"))
        name = job["result"]["project_name"]
        self.assertEqual(job["result"]["count"], 2)

        # a second job while idle is fine, and project data is readable
        _, _, raw = self.call("/api/project?name=" + name)
        project = json.loads(raw)
        self.assertEqual(len(project["shorts"]), 2)
        self.assertEqual(project["meta"]["mode"], "game")
        listed = json.loads(self.call("/api/projects")[2])
        self.assertEqual(listed[0]["name"], name)

        # video streaming with a Range header (needed for seeking in the preview)
        clip = f"/files/{name}/clips/short_01.mp4"
        status, headers, raw = self.call(clip, headers={"Range": "bytes=0-99"})
        self.assertEqual(status, 206)
        self.assertEqual(len(raw), 100)
        self.assertTrue(headers["Content-Range"].startswith("bytes 0-99/"))
        status, _, raw = self.call(clip)
        self.assertEqual(status, 200)
        self.assertGreater(len(raw), 10_000)

        # export clip 1 again with a shorter length and a new title
        first = project["shorts"][0]
        new_start, new_end = first["start"] + 1.0, first["end"] - 1.0
        status, _, raw = self.call("/api/rerender", {
            "project": name, "index": 0, "start": new_start, "end": new_end, "title": "My new title"})
        self.assertEqual(status, 200, raw)
        job = self.wait_job(json.loads(raw)["job"])
        self.assertEqual(job["status"], "done", job.get("error"))
        after = json.loads(self.call("/api/project?name=" + name)[2])["shorts"][0]
        self.assertEqual(after["title"], "My new title")
        self.assertAlmostEqual(after["end"] - after["start"], new_end - new_start, places=1)
        out = Path(self.state.out_dir) / name / "clips" / "short_01.mp4"
        info = json.loads(subprocess.run(
            ["ffprobe", "-v", "error", "-print_format", "json", "-show_format", str(out)],
            capture_output=True, text=True).stdout)
        self.assertAlmostEqual(float(info["format"]["duration"]), new_end - new_start, delta=0.3)

        # bad edit values give a clear message
        status, _, raw = self.call("/api/rerender", {"project": name, "index": 0, "start": 5, "end": 5.2})
        job = self.wait_job(json.loads(raw)["job"])
        self.assertEqual(job["status"], "error")
        self.assertIn("at least 1 second", job["error"])

    def test_4_calibrate_job(self):
        status, _, raw = self.call("/api/calibrate", {"source": str(self.video), "time": 11})
        self.assertEqual(status, 200, raw)
        job = self.wait_job(json.loads(raw)["job"])
        self.assertEqual(job["status"], "done", job.get("error"))
        self.assertEqual(job["result"]["rows"], 3)
        for rel in job["result"]["images"]:
            self.assertEqual(self.call(f"/files/{rel}")[0], 200)


if __name__ == "__main__":
    unittest.main()
