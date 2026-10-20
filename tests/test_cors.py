import http.client
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile
import time
import unittest


ROOT = Path(__file__).resolve().parents[1]
PHP = shutil.which("php")


@unittest.skipUnless(PHP, "PHP is required for real HTTP CORS checks")
class CorsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workspace = tempfile.TemporaryDirectory(prefix="kk67-cors-")
        cls.addClassCleanup(cls.workspace.cleanup)
        package = Path(cls.workspace.name)
        for name in ("index.php", "loader.php"):
            shutil.copyfile(ROOT.joinpath("src", name), package / name)

        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            cls.port = listener.getsockname()[1]
        cls.server_log = tempfile.TemporaryFile()
        cls.addClassCleanup(cls.server_log.close)
        cls.server = subprocess.Popen(
            [
                PHP, "-n", "-d", "allow_url_fopen=0",
                "-S", f"127.0.0.1:{cls.port}", "-t", str(package),
            ],
            cwd=package,
            stdin=subprocess.DEVNULL,
            stdout=cls.server_log,
            stderr=subprocess.STDOUT,
        )
        cls.addClassCleanup(cls.stop_server)
        deadline = time.monotonic() + 10
        while cls.server.poll() is None and time.monotonic() < deadline:
            try:
                with socket.create_connection(("127.0.0.1", cls.port), timeout=1):
                    return
            except (ConnectionRefusedError, TimeoutError):
                time.sleep(0.05)
        cls.server_log.seek(0)
        raise RuntimeError(
            "PHP HTTP fixture failed to start: "
            + cls.server_log.read().decode("utf-8", errors="replace")
        )

    @classmethod
    def stop_server(cls):
        if cls.server.poll() is None:
            cls.server.terminate()
            try:
                cls.server.wait(timeout=5)
            except subprocess.TimeoutExpired:
                cls.server.kill()
                cls.server.wait(timeout=5)

    def request(self, method, origin):
        headers = {}
        if origin is not None:
            headers["Origin"] = origin
        if method == "OPTIONS":
            headers.update({
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "content-type",
            })
        path = "/index.php/posts/ig/" if method == "OPTIONS" else "/index.php/"
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            connection.request(method, path, headers=headers)
            response = connection.getresponse()
            return response.status, response.headers, response.read()
        finally:
            connection.close()

    def assert_varies_by_origin(self, headers):
        vary = ",".join(headers.get_all("Vary", []))
        self.assertIn("origin", {value.strip().lower() for value in vary.split(",")})

    def test_preflight_accepts_both_production_origins_and_local_development(self):
        for origin in (
            "https://kk-67.com",
            "https://www.kk-67.com",
            "http://localhost:3000",
        ):
            with self.subTest(origin=origin):
                status, headers, body = self.request("OPTIONS", origin)
                self.assertEqual(status, 200)
                self.assertEqual(headers.get("Access-Control-Allow-Origin"), origin)
                self.assertIn("GET", headers["Access-Control-Allow-Methods"].split(","))
                self.assertIn(
                    "content-type",
                    headers["Access-Control-Allow-Headers"].lower(),
                )
                self.assert_varies_by_origin(headers)
                self.assertEqual(body, b"")

    def test_get_accepts_both_production_origins(self):
        for origin in ("https://kk-67.com", "https://www.kk-67.com"):
            with self.subTest(origin=origin):
                status, headers, body = self.request("GET", origin)
                self.assertEqual(status, 200)
                self.assertEqual(headers.get("Access-Control-Allow-Origin"), origin)
                self.assert_varies_by_origin(headers)
                self.assertEqual(body, b"")

    def test_untrusted_and_absent_origins_are_not_allowed_and_vary_for_caches(self):
        for origin in (
            "https://untrusted.invalid",
            "https://kk-67.com.untrusted.invalid",
            "null",
            None,
        ):
            with self.subTest(origin=origin):
                status, headers, body = self.request("OPTIONS", origin)
                self.assertEqual(status, 200)
                self.assertIsNone(headers.get("Access-Control-Allow-Origin"))
                self.assert_varies_by_origin(headers)
                self.assertEqual(body, b"")


if __name__ == "__main__":
    unittest.main()
