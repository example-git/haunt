import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import ssl
import subprocess
import tarfile
import tempfile
import threading
import unittest
from unittest.mock import patch
import urllib.parse
import urllib.request

spec = importlib.util.spec_from_file_location("verify_deployment", Path(__file__).resolve().parents[1] / "verify-deployment.py")
verification = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verification)


class PublicVerificationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        certificate, key = root / "certificate.pem", root / "certificate-key.pem"
        subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1", "-subj", "/CN=updates.fixture.test",
            "-addext", "subjectAltName=DNS:updates.fixture.test,IP:127.0.0.1", "-addext", "basicConstraints=critical,CA:TRUE",
            "-keyout", str(key), "-out", str(certificate)], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.files = {}
        self.headers = {}
        self.requests = []
        files = self.files
        headers, requests = self.headers, self.requests
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                path = urllib.parse.urlsplit(self.path).path
                requests.append(path)
                data = files.get(path)
                self.send_response(200 if data is not None else 404)
                self.send_header("Content-Length", str(len(data) if data is not None else 0))
                for name, value in headers.get(path, {}).items():
                    self.send_header(name, value)
                self.end_headers()
                if data is not None:
                    self.wfile.write(data)

            def log_message(self, *args):
                pass
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(certificate, key)
        self.server.socket = context.wrap_socket(self.server.socket, server_side=True)
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.origin = "https://updates.fixture.test"
        client_context = ssl.create_default_context(cafile=str(certificate))
        def request(url, headers=None):
            parts = urllib.parse.urlsplit(url)
            local = "https://127.0.0.1:" + str(self.server.server_port) + parts.path + ("?" + parts.query if parts.query else "")
            return urllib.request.urlopen(urllib.request.Request(local, headers=headers or {}), context=client_context, timeout=30)
        self.enterContext(patch.object(verification, "request", side_effect=request))
        route = root / "route.cjs"
        route.write_text("""const https=require('node:https'),tls=require('node:tls');
const original=https.globalAgent.createConnection;
https.globalAgent.createConnection=function(options,...args){
 if(options.host==='updates.fixture.test'||options.hostname==='updates.fixture.test'||options.servername==='updates.fixture.test')
  return tls.connect({...options,host:'127.0.0.1',port:Number(process.env.HAUNT_FIXTURE_PORT),servername:'updates.fixture.test'});
 return original.call(this,options,...args);
};
""")
        self.enterContext(patch.dict(os.environ, {"NODE_OPTIONS": "--require " + json.dumps(str(route)), "NODE_EXTRA_CA_CERTS": str(certificate), "HAUNT_FIXTURE_PORT": str(self.server.server_port)}))

    def test_public_assets_must_equal_the_selected_build(self):
        archive = Path(self.temp.name) / "web.tar.gz"
        with tarfile.open(archive, "w:gz") as bundle:
            for name, data in [("index.html", b"selected build"), ("assets/client.js", b"selected code"), ("_headers", b"ordinary static file")]:
                info = tarfile.TarInfo("./" + name)
                info.size = len(data)
                bundle.addfile(info, io.BytesIO(data))
                self.files["/" + name] = data
        self.assertEqual(verification.verify_archive(self.origin, archive, "./"), 3)
        self.assertIn("/_headers", self.requests)
        self.files["/assets/client.js"] = b"wrong deployment"
        with self.assertRaisesRegex(ValueError, "asset mismatch"):
            verification.verify_archive(self.origin, archive, "./")

    def test_cloudflare_headers_are_verified_as_response_rules(self):
        archive = Path(self.temp.name) / "web.tar.gz"
        with tarfile.open(archive, "w:gz") as bundle:
            for name, data in [("index.html", b"selected build"), ("assets/client.js", b"selected code"),
                ("_headers", b"/*\n  X-Content-Type-Options: nosniff\n/assets/*\n  Cache-Control: public, immutable\n/\n  Cache-Control: no-cache\n")]:
                info = tarfile.TarInfo("./" + name)
                info.size = len(data)
                bundle.addfile(info, io.BytesIO(data))
                if name != "_headers":
                    self.files["/" + name] = data
        self.files["/"] = self.files["/index.html"]
        self.headers.update({path: {"X-Content-Type-Options": "nosniff"} for path in self.files})
        self.headers["/assets/client.js"]["Cache-Control"] = "public, immutable"
        self.headers["/"]["Cache-Control"] = "no-cache"
        self.assertEqual(verification.verify_archive(self.origin, archive, "./", cloudflare=True), 2)
        self.assertNotIn("/_headers", self.requests)
        self.headers["/assets/client.js"]["Cache-Control"] = "no-cache"
        with self.assertRaisesRegex(ValueError, "header mismatch"):
            verification.verify_archive(self.origin, archive, "./", cloudflare=True)
        self.headers["/assets/client.js"]["Cache-Control"] = "public, immutable"
        self.headers["/"].pop("X-Content-Type-Options")
        with self.assertRaisesRegex(ValueError, "header mismatch"):
            verification.verify_archive(self.origin, archive, "./", cloudflare=True)

    def test_cloudflare_header_rules_must_be_present(self):
        archive = Path(self.temp.name) / "web.tar.gz"
        with tarfile.open(archive, "w:gz") as bundle:
            info = tarfile.TarInfo("./index.html")
            info.size = 1
            bundle.addfile(info, io.BytesIO(b"x"))
        with self.assertRaisesRegex(ValueError, "header rules are missing"):
            verification.verify_archive(self.origin, archive, "./", cloudflare=True)

    def test_both_public_feed_paths_verify_all_signed_download_bytes(self):
        import base64
        targets = {}
        for target in ["win32-x64", "linux-x64", "linux-arm64", "darwin-arm64"]:
            entry = {"runtime": "f" * 64}
            for kind in ["asar", "installer"] + (["rpm"] if target.startswith("linux") else []):
                data = (target + kind).encode()
                suffix = ".asar" if kind == "asar" else ".rpm" if kind == "rpm" else ".exe" if target.startswith("win32") else ".dmg" if target.startswith("darwin") else ".AppImage"
                name = target + "-" + kind + suffix
                entry[kind] = {"file": name, "size": len(data), "sha256": hashlib.sha256(data).hexdigest()}
                for prefix in ["/api/v1/client-updates/0.17.9/", "/api/v1/client-updates/client-v0.17.9/", "/client-updates/client-v0.17.9/"]:
                    self.files[prefix + name] = data
            targets[target] = entry
        payload = {"schema": 1, "repository": "example-git/haunt-client", "version": "0.17.9", "notes": "fixture", "targets": targets}
        signed = json.loads(subprocess.check_output(["node", "-e", """const c=require('node:crypto');
const keys=c.generateKeyPairSync('ed25519'),payload=Buffer.from(process.argv[1]);
console.log(JSON.stringify({publicKey:keys.publicKey.export({type:'spki',format:'pem'}),envelope:{schema:1,payload:payload.toString('base64'),signature:c.sign(null,payload,keys.privateKey).toString('base64')}}));
""", json.dumps(payload)], text=True))
        envelope = signed["envelope"]
        fixture = Path(self.temp.name) / "project"
        for name in ["scripts/verify-client-downloads.mjs", "client/apps/desktop/updates.cjs"]:
            target = fixture / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(verification.ROOT / name, target)
        configuration = fixture / "client/static/updates.json"
        configuration.parent.mkdir(parents=True)
        configuration.write_text(json.dumps({"repository": payload["repository"], "publicKey": signed["publicKey"]}))
        self.enterContext(patch.object(verification, "ROOT", fixture))
        for prefix in ["/api/v1/client-updates", "/client-updates"]:
            self.files[prefix + "/haunt-updates.json"] = json.dumps(envelope).encode()
        self.files["/api/v1/client-updates/installers"] = json.dumps({"manifest": envelope, "available": list(targets)}).encode()
        for community in [True, False]:
            self.assertEqual(len(verification.verify_feed(self.origin, {"version": "0.17.9"}, envelope, community)), 10)
        damaged = "/client-updates/client-v0.17.9/linux-x64-rpm.rpm"
        original = self.files[damaged]
        self.files[damaged] = b"x" * len(original)
        with self.assertRaisesRegex(ValueError, "checksum does not match"):
            verification.verify_feed(self.origin, {"version": "0.17.9"}, envelope)
        self.files[damaged] = original
        envelope = {**envelope, "signature": base64.b64encode(b"x" * 64).decode()}
        self.files["/client-updates/haunt-updates.json"] = json.dumps(envelope).encode()
        with self.assertRaisesRegex(ValueError, "signature could not be verified"):
            verification.verify_feed(self.origin, {"version": "0.17.9"}, envelope)


if __name__ == "__main__":
    unittest.main()
