import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def module(name, filename):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).resolve().parents[1] / filename)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


remote = module("deploy_remote", "deploy-remote.py")
transport = module("deploy_transport", "deploy-release.py")


class DeploymentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_atomic_replacement_keeps_previous_binary_on_failure(self):
        source, target = self.root / "next", self.root / "current"
        source.write_bytes(b"new binary")
        target.write_bytes(b"previous binary")
        with patch.object(remote.os, "replace", side_effect=OSError("disk failure")):
            with self.assertRaises(OSError):
                remote.atomic_file(source, target)
        self.assertEqual(target.read_bytes(), b"previous binary")
        self.assertFalse((self.root / "current.haunt-release").exists())
        remote.atomic_file(source, target)
        self.assertEqual(target.read_bytes(), b"new binary")
        self.assertTrue(target.stat().st_mode & 0o111)
        (self.root / "current.haunt-release").write_bytes(b"another writer")
        with self.assertRaises(FileExistsError):
            remote.atomic_file(source, target)
        self.assertEqual((self.root / "current.haunt-release").read_bytes(), b"another writer")

    def test_feed_setting_preserves_unrelated_environment_bytes(self):
        manifest = "https://github.com/example-git/haunt/releases/download/v0.17.14/haunt-updates.json"
        original = b'PRIVATE_SETTING="keep # this"\r\n HAUNT_CLIENT_UPDATE_MANIFEST_URL ="https://old.example.test/updates.json"\r\nOTHER=unchanged'
        expected = original.replace(b'"https://old.example.test/updates.json"', manifest.encode())
        self.assertEqual(remote.server_environment(original, manifest), expected)
        self.assertEqual(remote.server_environment(expected, manifest), expected)
        original = b"PRIVATE_SETTING=unchanged\r\nOTHER=also-unchanged"
        self.assertEqual(remote.server_environment(original, manifest), original + b"\r\nHAUNT_CLIENT_UPDATE_MANIFEST_URL=" + manifest.encode() + b"\r\n")

    def test_server_feed_selection_and_startup_failure_preserve_configuration(self):
        for outcome in ["success", "startup-failure", "schema-advanced"]:
            with self.subTest(outcome=outcome), tempfile.TemporaryDirectory(dir=self.root) as temporary:
                root = Path(temporary)
                data = root / "data"
                data.mkdir()
                (data / "settings.json").write_bytes(b'{"private":"preserved"}')
                environment, binary = root / "service.env", root / "haunt"
                old_environment = b"PRIVATE_SETTING=preserved\nHAUNT_CLIENT_UPDATE_MANIFEST_URL=https://old.example.test/updates.json\n"
                environment.write_bytes(old_environment)
                environment.chmod(0o640)
                binary.write_bytes(b"previous binary")
                stage = root / "stage"
                publish = stage / "publish"
                publish.mkdir(parents=True)
                source = publish / "haunt-server-linux-amd64"
                source.write_bytes(b"next binary")
                marker = {"version": "0.17.14"}
                with tarfile.open(publish / "haunt-app-linux-amd64.tar.gz", "w:gz") as archive:
                    payload = json.dumps(marker).encode()
                    item = tarfile.TarInfo("web/haunt-build.json")
                    item.size = len(payload)
                    archive.addfile(item, io.BytesIO(payload))
                plan = {"version": "0.17.14", "repository": "example-git/haunt", "tag": "v0.17.14"}
                config = {"binary": str(binary), "data": str(data), "environment_file": str(environment), "service": "fixture", "database_container": "fixture-db", "database_port": 32768, "arch": "amd64", "local_origin": "http://127.0.0.1:8080", "web_origin": "https://web.example.test", "preserved_files": [str(environment)]}
                manifest = "https://github.com/example-git/haunt/releases/download/v0.17.14/haunt-updates.json"
                expected_environment = old_environment.replace(b"https://old.example.test/updates.json", manifest.encode())
                read_bytes = Path.read_bytes
                digest = remote.digest
                running = [True]
                def environment_bytes(path):
                    if str(path) == "/proc/123/environ":
                        value = next(line.split(b"=", 1)[1] for line in read_bytes(environment).splitlines() if line.startswith(b"HAUNT_CLIENT_UPDATE_MANIFEST_URL="))
                        return b"HAUNT_DATABASE_URL=postgres://fixture@127.0.0.1:32768/fixture\0HAUNT_INSTANCE_ID=fixture\0HAUNT_CLIENT_UPDATE_MANIFEST_URL=" + value + b"\0"
                    return read_bytes(path)
                def command(*args, **kwargs):
                    if args[:2] == ("systemctl", "show"):
                        key = next(a.removeprefix("--property=") for a in args if a.startswith("--property="))
                        return {"MainPID": "123", "ActiveState": "active", "NRestarts": "0"}[key]
                    if args[:2] == ("systemctl", "stop"):
                        running[0] = False
                        return ""
                    if args[:2] == ("systemctl", "start"):
                        running[0] = True
                        return ""
                    if args[:2] == ("docker", "port"):
                        return "127.0.0.1:32768"
                    if "psql" in args:
                        query = args[-1]
                        if "max(version)" in query:
                            return "2" if outcome == "schema-advanced" and read_bytes(binary) == b"next binary" else "1"
                        return json.dumps({"role": 7} if "roles" in query else {"singleton": True})
                    if "pg_restore" in args:
                        return "schema_migrations"
                    if args[0] == "tar":
                        Path(args[args.index("-cpf") + 1]).write_bytes(b"data backup")
                        return ""
                    if args == (str(source), "-version"):
                        return plan["version"]
                    raise AssertionError(args)
                def dump(*args, **kwargs):
                    kwargs["stdout"].write(b"database backup")
                    return subprocess.CompletedProcess(args, 0)
                def read(origin, route, headers=None):
                    value = {"status": "ok"} if route == "/readyz" else marker if route == "/haunt-build.json" else {"instance_id": "fixture"}
                    return value, {"Access-Control-Allow-Origin": config["web_origin"]}
                def ready(check):
                    result = check()
                    self.assertEqual(environment.read_bytes(), expected_environment)
                    if outcome != "success":
                        raise RuntimeError("new service failed")
                    return result
                with patch.object(Path, "read_bytes", new=environment_bytes), patch.object(remote, "digest", side_effect=lambda path: digest(binary if str(path) == "/proc/123/exe" else path)), patch.object(remote, "run", side_effect=command), patch.object(remote.subprocess, "run", side_effect=dump), patch.object(remote, "read", side_effect=read), patch.object(remote, "ready", side_effect=ready):
                    if outcome == "success":
                        result = remote.server(stage, config, plan)
                        self.assertEqual(result["manifest_url"], manifest)
                    else:
                        with self.assertRaisesRegex(RuntimeError, "new service failed"):
                            remote.server(stage, config, plan)
                self.assertTrue(running[0])
                self.assertEqual(environment.read_bytes(), expected_environment if outcome == "success" else old_environment)
                self.assertEqual(environment.stat().st_mode & 0o777, 0o640)
                self.assertEqual(binary.read_bytes(), b"previous binary" if outcome == "startup-failure" else b"next binary")
                self.assertEqual((stage / "rollback/config-0").read_bytes(), old_environment)
                self.assertEqual((data / "settings.json").read_bytes(), b'{"private":"preserved"}')

    def test_sync_failure_restores_original_image_pin_and_configuration(self):
        compose = self.root / "compose"
        compose.mkdir()
        previous = b"HAUNT_SYNC_IMAGE=ghcr.io/example-git/haunt-sync:0.17.8\nPRIVATE_SETTING=preserved\n"
        (compose / ".env").write_bytes(previous)
        (compose / "compose.yml").write_text("services: {}\n")
        stage = self.root / "stage"
        stage.mkdir()
        config = {"compose_directory": str(compose), "container": "fixture-nexus", "project": "fixture", "updates_directory": str(self.root / "updates")}
        plan = {"version": "0.17.9", "revision": "a" * 40, "components": {"sync": "b" * 40}}
        before = {key: {"rows": 1, "sha256": "preserved"} for key in ["configuration", "accounts", "vaults"]}
        before["saved_password_sha256"] = "preserved"
        old = {"Image": "old-image", "Mounts": [{"Destination": "/data", "Type": "volume", "Name": "fixture-data", "Source": "/data/fixture"}], "Config": {"Env": ["HAUNT_SYNC_HOST=example.test"]}}
        new = {"Config": {"Labels": {"org.opencontainers.image.version": "0.17.9", "org.opencontainers.image.revision": "b" * 40, "vg.xo.haunt.hub-revision": "a" * 40}}}
        def run(*args, **kwargs):
            if args[:2] == ("docker", "inspect"):
                return json.dumps([old])
            if args[:3] == ("docker", "image", "inspect"):
                return json.dumps([new])
            if "pg_restore" in args:
                return "vaults"
            if args[:2] == ("docker", "run"):
                (stage / "rollback/data.tar.gz").write_bytes(b"volume backup")
            return ""
        def dump(*args, **kwargs):
            kwargs["stdout"].write(b"database backup")
            return subprocess.CompletedProcess(args, 0)
        with patch.object(remote, "run", side_effect=run), patch.object(remote, "sync_snapshot", return_value=before), patch.object(remote, "ready", side_effect=RuntimeError("new service failed")), patch.object(remote.subprocess, "run", side_effect=dump):
            with self.assertRaisesRegex(RuntimeError, "new service failed"):
                remote.sync(stage, config, plan)
        self.assertEqual((compose / ".env").read_bytes(), previous)
        self.assertEqual((stage / "rollback/database.dump").read_bytes(), b"database backup")
        self.assertEqual((stage / "rollback/data.tar.gz").read_bytes(), b"volume backup")
        self.assertFalse((self.root / "updates").exists())

    def test_development_plan_is_rejected_before_deployment_commands(self):
        (self.root / "plan.json").write_text(json.dumps({"channel": "dev", "version": "0.17.9-dev.1"}))
        with patch.object(remote.sys, "argv", ["deploy.py", str(self.root)]), patch.object(remote, "run") as run:
            with self.assertRaisesRegex(ValueError, "cannot deploy"):
                remote.main()
        run.assert_not_called()

    def test_invalid_deployment_targets_fail_before_ssh(self):
        config = {"kind": "sync", "ssh_target": "deploy@example.test", "compose_directory": "/srv/haunt/sync", "container": "nexus", "project": "haunt", "updates_directory": "/srv/haunt/updates", "public_origins": ["https://nexus.example.test"]}
        self.assertEqual(transport.validate_config(config), config)
        for update in [{"ssh_target": "deploy@host;echo unsafe"}, {"jump_host": "deploy@host;echo unsafe"}, {"ssh_port": 0}, {"ssh_port": True}, {"ssh_port": "22"}, {"compose_directory": "relative"}, {"public_origins": ["http://example.test"]}, {"updates_directory": ""}]:
            with self.assertRaises(ValueError):
                transport.validate_config({**config, **update})

    def test_private_deployment_routes_keep_authentication_and_host_pinning(self):
        import shlex
        config = {"kind": "sync", "ssh_target": "root@127.0.0.1", "compose_directory": "/srv/haunt/sync", "container": "nexus", "project": "haunt", "updates_directory": "/srv/haunt/updates", "public_origins": ["https://nexus.example.test"]}
        direct = transport.ssh_command(config, "/private/release key", "/private/pinned hosts")
        self.assertEqual(direct[-3:], ["-p", "22", "root@127.0.0.1"])
        self.assertFalse(any(arg.startswith("ProxyCommand=") for arg in direct))
        routed = transport.ssh_command({**config, "jump_host": "deploy@gateway.example.test", "ssh_port": 22222}, "/private/release key", "/private/pinned hosts")
        proxy = shlex.split(next(arg.removeprefix("ProxyCommand=") for arg in routed if arg.startswith("ProxyCommand=")))
        self.assertEqual(proxy[-3:], ["-W", "%h:%p", "deploy@gateway.example.test"])
        self.assertEqual(routed[-3:], ["-p", "22222", "root@127.0.0.1"])
        for command in [direct, routed, proxy]:
            self.assertIn("StrictHostKeyChecking=yes", command)
            self.assertIn("UserKnownHostsFile=/private/pinned hosts", command)
            self.assertEqual(command[command.index("-i") + 1], "/private/release key")


if __name__ == "__main__":
    unittest.main()
