import http.client
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile
import time
import unittest


ROOT = Path(__file__).resolve().parents[1]
PHP = shutil.which("php")


@unittest.skipUnless(PHP, "PHP is required for feed endpoint checks")
class FeedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workspace = tempfile.TemporaryDirectory(prefix="kk67-feed-")
        cls.addClassCleanup(cls.workspace.cleanup)
        package = Path(cls.workspace.name)
        for name in ("index.php", "loader.php"):
            shutil.copyfile(ROOT / "src" / name, package / name)
        cls.fixture_file = package / "graph.json"
        cls.request_log = package / "requests.jsonl"
        cls.server_log = tempfile.TemporaryFile()
        cls.addClassCleanup(cls.server_log.close)
        env = {
            **os.environ,
            "GRAPH_FIXTURE_FILE": str(cls.fixture_file),
            "GRAPH_REQUEST_LOG": str(cls.request_log),
            "FB_USER_ID": "fixture-user",
            "FB_PAGE_ID": "fixture-page",
            "FB_USER_KEY": "fixture-user-secret",
            "FB_PAGE_KEY": "fixture-page-secret",
        }
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            cls.port = listener.getsockname()[1]
        cls.server = subprocess.Popen(
            [
                PHP, "-n", "-d", "allow_url_fopen=0", "-d", "display_errors=1",
                "-d", "log_errors=1",
                "-d", f"auto_prepend_file={ROOT / 'tests' / 'fixtures' / 'graph_stream.php'}",
                "-S", f"127.0.0.1:{cls.port}", "-t", str(package),
            ],
            cwd=package, env=env, stdin=subprocess.DEVNULL,
            stdout=cls.server_log, stderr=subprocess.STDOUT,
        )
        cls.addClassCleanup(cls.stop_server)
        deadline = time.monotonic() + 10
        while cls.server.poll() is None and time.monotonic() < deadline:
            try:
                with socket.create_connection(("127.0.0.1", cls.port), timeout=1):
                    return
            except (ConnectionRefusedError, TimeoutError):
                time.sleep(0.05)
        raise RuntimeError("PHP feed fixture failed to start")

    @classmethod
    def stop_server(cls):
        if cls.server.poll() is None:
            cls.server.terminate()
            try:
                cls.server.wait(timeout=5)
            except subprocess.TimeoutExpired:
                cls.server.kill()
                cls.server.wait(timeout=5)

    def setUp(self):
        self.feed = {
            "data": [{
                "id": "fixture-post", "media_type": "CAROUSEL_ALBUM",
                "timestamp": "2026-10-20T10:00:00+0000",
                "permalink": "https://fixture.invalid/post",
                "children": {"data": [
                    {"media_type": "IMAGE", "media_url": "https://fixture.invalid/photo.jpg"},
                    {"media_type": "VIDEO", "media_url": "https://fixture.invalid/video.mp4"},
                ]},
            }],
            "paging": {
                "cursors": {"before": "first", "after": "last"},
                "next": "https://fixture.invalid/next?access_token=fixture-user-secret",
            },
        }
        self.profile = {
            "id": "fixture-profile", "name": "Fixture profile",
            "profile_picture_url": "https://fixture.invalid/profile.jpg",
            "picture": {"data": {"url": "https://fixture.invalid/profile.jpg"}},
        }

    def request(self, provider="ig", override=None):
        fixture = {
            "feed": {"available": True, "body": json.dumps(self.feed)},
            "profile": {"available": True, "body": json.dumps(self.profile)},
        }
        if override:
            fixture.update(override)
        self.fixture_file.write_text(json.dumps(fixture), encoding="utf-8")
        self.request_log.write_text("", encoding="utf-8")
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            connection.request("GET", f"/index.php/posts/{provider}/", headers={"Origin": "https://kk-67.com"})
            response = connection.getresponse()
            body = response.read().decode("utf-8")
            self.assertEqual(response.getheader("Access-Control-Allow-Origin"), "https://kk-67.com")
            self.assertIn("origin", response.getheader("Vary").lower())
            self.assertIn("application/json", response.getheader("Content-Type"))
            self.assertNotIn("fixture-user-secret", body)
            self.assertNotIn("fixture-page-secret", body)
            self.assertNotIn("access_token", body)
            return response.status, json.loads(body)
        finally:
            connection.close()

    def requests(self):
        return [json.loads(line) for line in self.request_log.read_text().splitlines()]

    def test_success_preserves_media_optional_captions_and_clean_paging(self):
        for provider, key in (("ig", "media"), ("fb", "posts")):
            with self.subTest(provider=provider):
                status, payload = self.request(provider)
                self.assertEqual(status, 200)
                self.assertEqual(payload[key]["data"], self.feed["data"])
                self.assertNotIn("caption", payload[key]["data"][0])
                self.assertEqual(payload[key]["paging"], {"cursors": {"after": "last"}})
                self.assertEqual([item["kind"] for item in self.requests()], ["feed", "profile"])
                self.assertTrue(all(item["timeout"] == 10 for item in self.requests()))

    def test_empty_or_nonempty_feeds_without_paging_are_valid(self):
        for data in ([], self.feed["data"]):
            self.feed = {"data": data}
            for provider, key in (("ig", "media"), ("fb", "posts")):
                with self.subTest(provider=provider, empty=not data):
                    status, payload = self.request(provider)
                    self.assertEqual(status, 200)
                    self.assertEqual(payload[key], self.feed)

    def test_paging_can_omit_cursors(self):
        self.feed["paging"] = {"next": "https://fixture.invalid/next"}
        status, payload = self.request()
        self.assertEqual(status, 200)
        self.assertEqual(payload["media"]["paging"], [])

    def test_upstream_failures_are_explicit_json_errors_without_secrets(self):
        failures = {
            "transport": {"available": False, "body": ""},
            "non-json": {"available": True, "body": "<h1>Upstream unavailable</h1>"},
            "graph-error": {"available": True, "body": json.dumps({
                "error": {"message": "Never echo fixture-user-secret or fixture-page-secret", "code": 190},
            })},
            "null": {"available": True, "body": "null"},
        }
        for provider in ("ig", "fb"):
            for part in ("feed", "profile"):
                for label, failure in failures.items():
                    with self.subTest(provider=provider, part=part, failure=label):
                        status, payload = self.request(provider, {part: failure})
                        self.assertEqual(status, 500)
                        self.assertEqual(list(payload), ["error"])
                        self.assertIsInstance(payload["error"], str)
                        if part == "feed":
                            self.assertEqual(len(self.requests()), 1)
        self.server_log.seek(0)
        logs = self.server_log.read().decode("utf-8", errors="replace")
        self.assertIn("feed request failed", logs.lower())
        self.assertNotIn("fixture-user-secret", logs)
        self.assertNotIn("fixture-page-secret", logs)

    def test_malformed_feed_or_profile_is_not_reported_as_success(self):
        for provider in ("ig", "fb"):
            for part, payload in (
                ("feed", {}), ("feed", {"data": None}), ("feed", {"data": {"wrong": "shape"}}),
                ("feed", {"data": [], "paging": None}),
                ("feed", {"data": [], "paging": {"cursors": "wrong"}}),
                ("profile", {}),
            ):
                with self.subTest(provider=provider, part=part, payload=payload):
                    status, result = self.request(provider, {
                        part: {"available": True, "body": json.dumps(payload)},
                    })
                    self.assertEqual(status, 500)
                    self.assertEqual(list(result), ["error"])


if __name__ == "__main__":
    unittest.main()
