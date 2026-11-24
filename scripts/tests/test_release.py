import argparse
import copy
import importlib.util
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import release


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.plan = {"schema": 1, "repository": release.REPO, "channel": "stable", "version": "0.17.9",
            "tag": "v0.17.9", "revision": "a" * 40, "components": {key: char * 40 for key, char in zip(["client", "server", "sync", "rnnoise"], "bcde")},
            "targets": release.TARGETS.copy(), "run_id": "123"}

    def test_only_selected_dev_targets_and_all_stable_targets(self):
        self.assertEqual(release.selected_targets("dev", "linux-arm64,web"), ["linux-arm64", "web"])
        self.assertEqual(release.selected_targets("stable", ""), release.TARGETS)
        for raw in ["", "all", "linux-x64,", "linux-x64,linux-x64", "linux-arm64;echo unsafe"]:
            with self.assertRaises(ValueError):
                release.selected_targets("dev", raw)
        with self.assertRaises(ValueError):
            release.selected_targets("stable", "linux-x64")

    def test_explicit_version_increments_and_validation(self):
        for bump, result in [("patch", "0.17.9"), ("minor", "0.18.0"), ("major", "1.0.0")]:
            self.assertEqual(release.increment("0.17.8", bump), result)
        for value in ["1.2.3-dev.1", "01.2.3", "1.2", "1.2.3\n", "1000000.0.0"]:
            with self.assertRaises(ValueError):
                release.stable_tuple(value)

    def test_service_builder_reads_version_from_both_streams_and_rejects_mismatch(self):
        spec = importlib.util.spec_from_file_location("build_service", release.ROOT / "scripts/build-service.py")
        builder = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(builder)
        release.write(self.root / "release/plan.json", self.plan)
        release.write(self.root / "client/web-deployment.json", {"origin": "https://web.example.test"})
        (self.root / "sync").mkdir()
        execute = subprocess.run
        for stream, version in [("stdout", self.plan["version"]), ("stderr", self.plan["version"]), ("stderr", "0.0.0")]:
            with self.subTest(stream=stream, version=version):
                def compile_or_execute(command, *args, **kwargs):
                    if command[0] != "go":
                        return execute(command, *args, **kwargs)
                    executable = Path(command[command.index("-o") + 1])
                    output = "2026/10/27 12:00:00 Haunt Sync " + version + "\n"
                    executable.write_text("#!" + sys.executable + "\nimport sys\nsys." + stream + ".write(" + repr(output) + ")\n")
                    executable.chmod(0o700)
                    return subprocess.CompletedProcess(command, 0)
                with patch.object(builder, "ROOT", self.root), patch.dict(os.environ, COMPONENT="sync", ARCH="amd64"), patch.object(builder.subprocess, "run", side_effect=compile_or_execute):
                    if version == self.plan["version"]:
                        builder.main()
                    else:
                        with self.assertRaisesRegex(ValueError, "version does not match"):
                            builder.main()

    @patch.dict(os.environ, GITHUB_REF="refs/heads/main")
    def test_saved_plan_retry_never_reselects_moving_sources_or_version(self):
        file = self.root / "plan.json"
        release.write(file, self.plan)
        args = argparse.Namespace(channel="stable", plan=str(file), version="", targets="", bump="major")
        with patch.object(release, "run", return_value=self.plan["revision"]) as run, patch.object(release, "github_output"):
            release.plan_release(args)
        self.assertEqual(run.call_count, 1)
        self.assertEqual(json.loads(file.read_text()), self.plan)
        with patch.object(release, "run", return_value="f" * 40):
            with self.assertRaisesRegex(ValueError, "different source"):
                release.plan_release(args)

    def test_stable_plans_require_main_before_accessing_sources_or_releases(self):
        args = argparse.Namespace(channel="stable", plan=str(self.root / "plan.json"), version="", targets="", bump="patch")
        for ref in ["refs/heads/dev", "refs/heads/feature", "refs/tags/v0.17.9", ""]:
            with patch.dict(os.environ, GITHUB_REF=ref), patch.object(release, "run") as run:
                with self.assertRaisesRegex(ValueError, "must run from main"):
                    release.plan_release(args)
                run.assert_not_called()
            self.assertFalse(Path(args.plan).exists())

    def test_retry_reuses_only_the_original_target_artifact(self):
        plan = {**self.plan, "targets": ["web"]}
        folder = self.root / "artifacts/web"
        folder.mkdir(parents=True)
        (folder / "web.tar.gz").write_bytes(b"original build")
        release.describe(plan, "web", folder)
        artifact = {"name": "build-web", "expired": False, "id": 42}
        with patch.object(release, "api", return_value=[{"artifacts": [artifact]}]), patch.object(release, "run") as run, patch.object(release, "github_output"), patch.dict(os.environ, GITHUB_RUN_ID="123"):
            self.assertTrue(release.restore_artifact("build-web", folder, plan, "web"))
            self.assertEqual(run.call_args.args[:4], ("gh", "run", "download", "123"))
            (folder / "web.tar.gz").write_bytes(b"changed build")
            with self.assertRaisesRegex(ValueError, "checksum"):
                release.restore_artifact("build-web", folder, plan, "web")

    def test_saved_plan_cannot_cross_channels_or_change_tags(self):
        for changes in [{"channel": "dev"}, {"tag": "v9.0.0"}, {"repository": "foreign/project"}]:
            file = self.root / "bad-plan.json"
            release.write(file, {**self.plan, **changes})
            with self.assertRaises(ValueError):
                release.load_plan(file)

    def test_expired_plan_never_silently_changes_the_release_version(self):
        with patch.object(release, "api", return_value=[{"artifacts": [{"name": "release-plan", "expired": True, "id": 42}]}]), patch.dict(os.environ, GITHUB_RUN_ID="123"):
            with self.assertRaisesRegex(ValueError, "expired"):
                release.restore_artifact("release-plan", self.root)

    def test_orphan_tag_cannot_publish_a_different_source_revision(self):
        reference = {"object": {"type": "commit", "sha": "f" * 40}}
        with patch.object(release, "find_release", return_value=None), patch.object(release, "optional_api", return_value=reference), patch.object(release, "run") as run:
            with self.assertRaisesRegex(ValueError, "different source"):
                release.ensure_release(self.plan, draft=True)
            run.assert_not_called()
        with patch.object(release, "api", return_value=[{"artifacts": []}]), patch.dict(os.environ, GITHUB_RUN_ID="123", GITHUB_RUN_ATTEMPT="2"):
            with self.assertRaisesRegex(ValueError, "No saved release plan"):
                release.restore_artifact("release-plan", self.root)

    def test_creation_uses_response_and_channel_flags_without_published_tag_lookup(self):
        for channel, draft in [("stable", True), ("dev", False)]:
            with self.subTest(channel=channel):
                plan = {**self.plan, "channel": channel}
                if channel == "dev":
                    plan.update(version="0.17.9-dev.42", tag="dev-v0.17.9-dev.42", targets=["linux-x64"])
                response = {"id": 123, "tag_name": plan["tag"], "draft": draft, "prerelease": channel == "dev", "target_commitish": plan["revision"], "assets": []}
                with patch.object(release, "optional_api", return_value=None) as lookup, patch.object(release, "api", side_effect=[[], response]) as api:
                    self.assertEqual(release.ensure_release(plan, draft=draft), response)
                self.assertEqual(lookup.call_count, 2)
                self.assertEqual(api.call_args.args[:3], (f"repos/{release.REPO}/releases", "--method", "POST"))
                self.assertIn("target_commitish=" + plan["revision"], api.call_args.args)
                self.assertIn("draft=" + str(draft).lower(), api.call_args.args)
                self.assertIn("prerelease=" + str(channel == "dev").lower(), api.call_args.args)
                self.assertIn("make_latest=false", api.call_args.args)

    def test_existing_unpublished_draft_is_found_and_reused_without_creating_another(self):
        draft = {"id": 123, "tag_name": self.plan["tag"], "draft": True, "prerelease": False, "target_commitish": self.plan["revision"], "assets": []}
        earlier = [{"tag_name": f"v0.16.{index}"} for index in range(100)]
        with patch.object(release, "optional_api", return_value=None), patch.object(release, "api", side_effect=[earlier, [draft]]) as api:
            self.assertEqual(release.ensure_release(self.plan, draft=True), draft)
        self.assertEqual(api.call_count, 2)
        self.assertEqual(api.call_args.args, (f"repos/{release.REPO}/releases?per_page=100&page=2",))

    def test_unpublished_draft_cannot_change_the_recorded_source(self):
        draft = {"id": 123, "tag_name": self.plan["tag"], "draft": True, "prerelease": False, "target_commitish": "f" * 40}
        with patch.object(release, "find_release", return_value=draft), patch.object(release, "optional_api", return_value=None):
            with self.assertRaisesRegex(ValueError, "source tag"):
                release.ensure_release(self.plan, draft=True)

    def test_new_plan_uses_hub_version_and_frozen_gitlinks(self):
        args = argparse.Namespace(channel="dev", plan=str(self.root / "plan.json"), version="", targets="linux-x64", bump="patch")
        def run(*command, **kwargs):
            if command[:3] == ("gh", "release", "list"):
                return json.dumps([{"tagName": "v0.17.8", "isPrerelease": False, "isDraft": False}, {"tagName": "dev-v9.0.0-dev.1", "isPrerelease": True, "isDraft": False}])
            if command[:3] == ("git", "rev-parse", "HEAD"):
                return "a" * 40
            return "160000 commit " + "b" * 40 + "\t" + command[-1]
        with patch.object(release, "run", side_effect=run), patch.object(release, "github_output"), patch.dict(os.environ, GITHUB_RUN_NUMBER="42", GITHUB_RUN_ID="123"):
            release.plan_release(args)
        plan = release.load_plan(args.plan)
        self.assertEqual(plan["version"], "0.17.9-dev.42")
        self.assertEqual(plan["targets"], ["linux-x64"])
        self.assertEqual(plan["components"]["client"], "b" * 40)

    def test_dev_is_rejected_before_stable_publication_or_network(self):
        self.plan.update(channel="dev", version="0.17.9-dev.42", targets=["linux-x64"])
        with patch.object(release, "run") as command:
            for function, args in [(release.assemble, (self.plan, self.root, self.root / "out")),
                (release.publish_images, (self.plan, self.root))]:
                with self.assertRaises(ValueError):
                    function(*args)
            command.assert_not_called()

    def test_provenance_rejects_wrong_sources_corruption_and_missing_targets(self):
        self.plan["targets"] = ["web"]
        folder = self.root / "artifacts/web"
        folder.mkdir(parents=True)
        (folder / "web.tar.gz").write_bytes(b"web")
        release.describe(self.plan, "web", folder)
        self.assertEqual(release.verify_artifacts(self.plan, folder.parent), {"web": folder})
        (folder / "web.tar.gz").write_bytes(b"bad")
        with self.assertRaisesRegex(ValueError, "checksum"):
            release.verify_artifacts(self.plan, folder.parent)
        (folder / "web.tar.gz").write_bytes(b"web")
        other = copy.deepcopy(self.plan)
        other["components"]["client"] = "f" * 40
        with self.assertRaisesRegex(ValueError, "source"):
            release.verify_artifacts(other, folder.parent)
        self.plan["targets"].append("linux-x64")
        with self.assertRaisesRegex(ValueError, "Missing targets"):
            release.verify_artifacts(self.plan, folder.parent)

    def test_stamping_dev_changes_install_identity_without_mutating_dependencies(self):
        self.copy_client()
        plan = {**self.plan, "channel": "dev", "version": "0.17.9-dev.42"}
        release.stamp(plan, self.root / "client")
        builder = json.loads((self.root / "client/electron-builder.config.json").read_text())
        self.assertEqual(builder["appId"], "com.exampleuser.haunt.dev")
        self.assertEqual(builder["linux"]["target"], [{"target": "AppImage"}])
        self.assertFalse(any(x.get("path", "").endswith("Install Haunt.command") for x in builder["dmg"]["contents"]))
        manifest = json.loads((self.root / "client/package.json").read_text())
        self.assertEqual(manifest["version"], plan["version"])
        self.assertEqual(manifest["desktopName"], "com.exampleuser.haunt.dev.desktop")

    def copy_client(self):
        client = self.root / "client"
        for name in ["package.json", "package-lock.json", "electron-app/package.json", "packages/core/package.json", "electron-builder.config.json",
            "scripts/version-main.mjs", "scripts/release-client.mjs", "scripts/update-runtime.mjs", "apps/desktop/updates.cjs", "static/updates.json"]:
            destination = client / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(release.ROOT / "client" / name, destination)
        return client

    def test_assembly_uses_shipped_signer_and_rejects_tampered_target(self):
        client = self.copy_client()
        key = subprocess.check_output(["openssl", "genpkey", "-algorithm", "ED25519"], stderr=subprocess.DEVNULL)
        public = subprocess.check_output(["openssl", "pkey", "-pubout"], input=key, stderr=subprocess.DEVNULL).decode()
        config = {"repository": "example-git/haunt-client", "feedURL": None, "publicKey": public}
        release.write(client / "static/updates.json", config)
        release.stamp(self.plan, client)
        plugin = self.root / "audio-plugins/rnnoise/dist/haunt-plugin.zip"
        plugin.parent.mkdir(parents=True)
        plugin.write_bytes(b"plugin")
        artifacts = self.root / "artifacts"
        for target in release.TARGETS:
            folder = artifacts / target
            folder.mkdir(parents=True)
            if target in release.DESKTOP:
                entry = {"version": self.plan["version"], "repository": config["repository"], "target": target, "runtime": "1" * 64}
                kinds = {"asar": ".asar", "installer": ".exe" if target.startswith("win") else ".dmg" if target.startswith("darwin") else ".AppImage"}
                if target.startswith("linux"):
                    kinds["rpm"] = ".rpm"
                for kind, extension in kinds.items():
                    file = folder / ("Haunt-" + target + extension)
                    file.write_bytes((target + kind).encode())
                    entry[kind] = {"file": file.name, "size": file.stat().st_size, "sha256": release.digest(file)}
                release.write(folder / (target + ".json"), entry)
            elif target.startswith("server"):
                arch = release.SERVICES[target]["arch"]
                platform = "linux/" + arch
                binary = bytearray(64)
                binary[:6] = b"\x7fELF\x02\x01"
                struct.pack_into("<H", binary, 18, 62 if arch == "amd64" else 183)
                (folder / ("haunt-server-linux-" + arch)).write_bytes(binary)
                staging = self.root / ("server-" + arch)
                staging.mkdir()
                (staging / "haunt").write_bytes(binary)
                release.write(staging / "release.json", {"schema": 1, "version": self.plan["version"], "runtime": "runtime", "platform": platform})
                archive = folder / ("haunt-app-linux-" + arch + ".tar.gz")
                with tarfile.open(archive, "w:gz") as bundle:
                    bundle.add(staging / "haunt", arcname="haunt")
                    bundle.add(staging / "release.json", arcname="release.json")
                release.write(folder / "haunt-app.json", {"schema": 1, "version": self.plan["version"], "runtime": "runtime", "platforms": {platform: {"asset": archive.name, "bytes": archive.stat().st_size, "sha256": release.digest(archive)}}})
            else:
                (folder / (target + ".bin")).write_bytes(target.encode())
            release.describe(self.plan, target, folder)
        with patch.object(release, "ROOT", self.root), patch.dict(os.environ, HAUNT_UPDATE_PRIVATE_KEY=key.decode()):
            release.assemble(self.plan, artifacts, self.root / "publish")
        envelope = json.loads((self.root / "publish/haunt-updates.json").read_text())
        check = "const fs=require('node:fs'),v=require(process.argv[1]);const e=JSON.parse(fs.readFileSync(process.argv[2])),c=JSON.parse(fs.readFileSync(process.argv[3]));for(const t of ['win32-x64','linux-x64','linux-arm64','darwin-arm64'])if(v.verifyManifest(e,c,...t.split('-')).version!=='0.17.9')throw Error('version')"
        subprocess.run(["node", "-e", check, str(client / "apps/desktop/updates.cjs"), str(self.root / "publish/haunt-updates.json"), str(client / "static/updates.json")], check=True)
        self.assertEqual(envelope["schema"], 1)
        (artifacts / "linux-x64/Haunt-linux-x64.rpm").write_bytes(b"corrupt")
        with patch.object(release, "ROOT", self.root), self.assertRaisesRegex(ValueError, "checksum"):
            release.assemble(self.plan, artifacts, self.root / "publish")


if __name__ == "__main__":
    unittest.main()
