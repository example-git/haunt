import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
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
