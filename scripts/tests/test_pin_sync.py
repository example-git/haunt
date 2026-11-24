import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("sync_pins", SCRIPTS / "sync-pins.py")
pins = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pins)


class PinSyncTests(unittest.TestCase):
    def git(self, path, *args):
        return subprocess.check_output(["git", "-C", str(path), *pins.IDENTITY, *args], text=True, stderr=subprocess.PIPE).strip()

    def write(self, base, name, data):
        target = base / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data if isinstance(data, bytes) else data.encode())

    def save(self, path):
        self.git(path, "add", ".")
        self.git(path, "commit", "-m", "fixture update")
        return self.git(path, "rev-parse", "HEAD")

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / "hub"
        self.root.mkdir()
        self.git(self.root, "init", "-b", "main")
        self.paths = ["client", "audio-plugins/rnnoise", "server", "sync", "extensions/tiktok-tts-plugin"]
        self.remotes = {}
        self.seeds = {}
        for index, name in enumerate(self.paths):
            seed = self.base / f"source-{index}"
            seed.mkdir()
            self.git(seed, "init", "-b", "main")
            self.write(seed, "README.md", "# Component\n")
            self.write(seed, "docs/notes.md", "# Component notes\n")
            if name == "client":
                self.write(seed, "package.json", '{"version":"0.1.0"}')
            if name == "audio-plugins/rnnoise":
                package = b"packaged model fixture"
                self.write(seed, "dist/haunt-plugin.zip", package)
                self.write(seed, "dist/SHA256SUMS", hashlib.sha256(package).hexdigest() + "  haunt-plugin.zip\n")
                self.write(seed, "dist/build.json", '{}\n')
                self.write(seed, "THIRD-PARTY-NOTICES.txt", "Fixture notices\n")
            if name == "server":
                self.git(seed, "-c", "protocol.file.allow=always", "submodule", "add", str(self.remotes["client"]), "client")
                bundle = seed / "internal/audioplugin/default"
                bundle.mkdir(parents=True)
                plugin = self.seeds["audio-plugins/rnnoise"]
                for file in pins.PACKAGE_FILES:
                    shutil.copyfile(plugin / file if file.endswith("NOTICES.txt") else plugin / "dist" / file, bundle / file)
                self.write(seed, "scripts/install.py", "# installer fixture\n")
            if name == "sync":
                self.write(seed, "go.mod", "module fixture\n")
            self.save(seed)
            self.git(seed, "branch", "dev")
            remote = self.base / f"remote-{index}.git"
            self.git(seed, "clone", "--bare", str(seed), str(remote))
            self.git(seed, "remote", "add", "origin", str(remote))
            self.remotes[name] = remote
            self.seeds[name] = seed
            (self.root / name).parent.mkdir(parents=True, exist_ok=True)
            self.git(self.root, "clone", str(remote), str(self.root / name))
        sections = []
        for name in self.paths:
            branch = "." if name in {"client", "server", "sync"} else "main"
            sections.append(f'[submodule "{name}"]\n\tpath = {name}\n\turl = {self.remotes[name]}\n\tbranch = {branch}\n')
        self.write(self.root, ".gitmodules", "\n".join(sections))
        self.write(self.root, "README.md", "# Hub\n")
        self.write(self.root, "install.py", "#!/usr/bin/env python3\n")
        (self.root / "install.py").chmod(0o755)
        for name in ["check-pins.py", "sync-docs.py", "check-docs.py"]:
            self.write(self.root, "scripts/" + name, (SCRIPTS / name).read_bytes())
        subprocess.run(["python3", str(self.root / "scripts/sync-docs.py")], check=True, stdout=subprocess.DEVNULL)
        self.save(self.root)
        self.git(self.root, "branch", "dev")
        self.hub_remote = self.base / "hub.git"
        self.git(self.root, "clone", "--bare", str(self.root), str(self.hub_remote))
        self.git(self.root, "remote", "add", "origin", str(self.hub_remote))

    def synchronize(self, branch):
        sources = pins.components(self.root, branch)
        with patch.object(pins, "ROOT", self.root):
            heads = pins.remote_heads(sources)
        return pins.synchronize(self.root, branch, sources, heads, push=True)

    def test_remote_dev_changes_update_embedded_client_and_docs_without_moving_main(self):
        original = self.git(self.hub_remote, "rev-parse", "main")
        seed = self.seeds["client"]
        self.git(seed, "checkout", "dev")
        (seed / "docs/notes.md").unlink()
        self.write(seed, "docs/new.md", "# New document\n")
        revision = self.save(seed)
        self.git(seed, "push", "origin", "dev")
        self.git(self.root, "checkout", "dev")
        result = self.synchronize("dev")
        self.assertTrue(result["changed"])
        self.assertTrue(result["server_changed"])
        self.assertEqual(self.git(self.hub_remote, "rev-parse", "main"), original)
        server = self.git(self.remotes["server"], "rev-parse", "dev")
        self.assertEqual(self.git(self.remotes["server"], "ls-tree", server, "client").split()[2], revision)
        self.assertEqual(pins.pinned(self.root, "client"), revision)
        self.assertEqual(pins.pinned(self.root, "server"), server)
        self.assertFalse((self.root / "docs/client/notes.md").exists())
        self.assertTrue((self.root / "docs/client/new.md").is_file())
        docs = json.loads((self.root / "docs/sources.json").read_text())
        self.assertEqual(docs["docs/client/new.md"]["revision"], revision)
        self.assertFalse(self.synchronize("dev")["changed"])

    def test_hub_client_pin_updates_are_propagated_to_server_on_main(self):
        seed = self.seeds["client"]
        self.write(seed, "docs/new.md", "# Main change\n")
        revision = self.save(seed)
        self.git(seed, "push", "origin", "main")
        self.git(self.root / "client", "fetch", "origin", "main")
        self.git(self.root / "client", "checkout", "--detach", revision)
        self.save(self.root)
        result = self.synchronize("main")
        self.assertTrue(result["changed"])
        self.assertEqual(self.git(self.remotes["server"], "ls-tree", "main", "client").split()[2], revision)

    def test_unchanged_heads_do_not_create_commits(self):
        original = self.git(self.hub_remote, "rev-parse", "main")
        self.write(self.root, "scratch.txt", "Unrelated untracked work\n")
        result = self.synchronize("main")
        self.assertFalse(result["changed"])
        self.assertFalse(result["server_changed"])
        self.assertEqual(self.git(self.hub_remote, "rev-parse", "main"), original)
        self.assertEqual((self.root / "scratch.txt").read_text(), "Unrelated untracked work\n")
        self.assertEqual(self.git(self.root, "ls-files", "scratch.txt"), "")

    def test_plugin_updates_copy_the_package_metadata_and_notices_together(self):
        seed = self.seeds["audio-plugins/rnnoise"]
        package = b"updated packaged model fixture"
        self.write(seed, "dist/haunt-plugin.zip", package)
        self.write(seed, "dist/SHA256SUMS", hashlib.sha256(package).hexdigest() + "  haunt-plugin.zip\n")
        self.write(seed, "dist/build.json", '{"updated":true}\n')
        self.write(seed, "THIRD-PARTY-NOTICES.txt", "Updated fixture notices\n")
        self.save(seed)
        self.git(seed, "push", "origin", "main")
        self.assertTrue(self.synchronize("main")["server_changed"])
        bundle = self.root / "server/internal/audioplugin/default"
        self.assertEqual((bundle / "haunt-plugin.zip").read_bytes(), package)
        self.assertEqual((bundle / "build.json").read_text(), '{"updated":true}\n')
        self.assertEqual((bundle / "THIRD-PARTY-NOTICES.txt").read_text(), "Updated fixture notices\n")

    def test_tracked_work_is_preserved_and_shared_plugins_track_main_on_dev(self):
        sources = pins.components(self.root, "dev")
        self.assertEqual(sources["client"]["branch"], "dev")
        self.assertEqual(sources["audio-plugins/rnnoise"]["branch"], "main")
        self.assertEqual(sources["extensions/tiktok-tts-plugin"]["branch"], "main")
        self.write(self.root, "README.md", "Uncommitted work\n")
        with self.assertRaisesRegex(ValueError, "Commit tracked changes"):
            self.synchronize("main")
        self.assertEqual((self.root / "README.md").read_text(), "Uncommitted work\n")

    def test_unpublished_component_commits_are_preserved(self):
        client = self.root / "client"
        self.write(client, "README.md", "Unpublished component work\n")
        revision = self.save(client)
        with self.assertRaisesRegex(ValueError, "Push component commits"):
            self.synchronize("main")
        self.assertEqual(self.git(client, "rev-parse", "HEAD"), revision)
