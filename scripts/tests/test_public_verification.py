import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import io
import json
from pathlib import Path
import tarfile
import tempfile
import threading
import unittest

spec = importlib.util.spec_from_file_location("verify_deployment", Path(__file__).resolve().parents[1] / "verify-deployment.py")
verification = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verification)


class PublicVerificationTests(unittest.TestCase):
    def setUp(self):
        self.files = {}
        files = self.files
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                data = files.get(self.path)
                self.send_response(200 if data is not None else 404)
                self.end_headers()
                if data is not None:
                    self.wfile.write(data)

            def log_message(self, *args):
                pass
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.origin = "http://127.0.0.1:" + str(self.server.server_port)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)

    def test_public_assets_must_equal_the_selected_build(self):
        archive = Path(self.temp.name) / "web.tar.gz"
        with tarfile.open(archive, "w:gz") as bundle:
            for name, data in [("index.html", b"selected build"), ("assets/client.js", b"selected code")]:
                info = tarfile.TarInfo("./" + name)
                info.size = len(data)
                bundle.addfile(info, io.BytesIO(data))
                self.files["/" + name] = data
        self.assertEqual(verification.verify_archive(self.origin, archive, "./"), 2)
        self.files["/assets/client.js"] = b"wrong deployment"
        with self.assertRaisesRegex(ValueError, "asset mismatch"):
            verification.verify_archive(self.origin, archive, "./")

    def test_both_public_feed_paths_verify_all_signed_download_bytes(self):
        import base64
        targets = {}
        for target in ["win32-x64", "linux-x64", "linux-arm64", "darwin-arm64"]:
            entry = {}
            for kind in ["asar", "installer"] + (["rpm"] if target.startswith("linux") else []):
                data = (target + kind).encode()
                name = target + "-" + kind
                entry[kind] = {"file": name, "size": len(data), "sha256": hashlib.sha256(data).hexdigest()}
                for prefix in ["/api/v1/client-updates/0.17.9/", "/client-updates/client-v0.17.9/"]:
                    self.files[prefix + name] = data
            targets[target] = entry
        envelope = {"schema": 1, "payload": base64.b64encode(json.dumps({"version": "0.17.9", "targets": targets}).encode()).decode(), "signature": "fixture"}
        for prefix in ["/api/v1/client-updates", "/client-updates"]:
            self.files[prefix + "/haunt-updates.json"] = json.dumps(envelope).encode()
        self.files["/api/v1/client-updates/installers"] = json.dumps({"manifest": envelope, "available": list(targets)}).encode()
        for community in [True, False]:
            self.assertEqual(len(verification.verify_feed(self.origin, {"version": "0.17.9"}, envelope, community)), 10)
        self.files["/client-updates/client-v0.17.9/linux-x64-rpm"] = b"corrupt download"
        with self.assertRaisesRegex(ValueError, "download hash mismatch"):
            verification.verify_feed(self.origin, {"version": "0.17.9"}, envelope)


if __name__ == "__main__":
    unittest.main()
