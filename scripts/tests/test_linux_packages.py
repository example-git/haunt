import importlib.util
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location("linux_packages", Path(__file__).resolve().parents[1] / "configure-linux-packages.py")
packages = importlib.util.module_from_spec(spec)
spec.loader.exec_module(packages)


class LinuxPackageTests(unittest.TestCase):
    def test_runner_mirrors_keep_suites_signing_keys_and_unrelated_sources(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            sources = root / "sources.list.d"
            sources.mkdir()
            content = "Types: deb\nURIs: mirror+file:/etc/apt/apt-mirrors.txt\nSuites: noble noble-updates noble-backports\nComponents: main restricted universe multiverse\nSigned-By: /usr/share/keyrings/ubuntu-archive-keyring.gpg\n"
            (sources / "ubuntu.sources").write_text(content)
            (root / "apt-mirrors.txt").write_text("http://azure.archive.ubuntu.com/ubuntu/\tpriority:1\nhttp://archive.ubuntu.com/ubuntu/\tpriority:2\n")
            third_party = "deb [signed-by=/usr/share/keyrings/vendor.gpg] https://packages.microsoft.com/repos/azure-cli/ noble main\n"
            (sources / "vendor.list").write_text(third_party)
            self.assertEqual(packages.configure(root), [str(root / "apt-mirrors.txt")])
            self.assertEqual((sources / "ubuntu.sources").read_text(), content)
            self.assertEqual((sources / "vendor.list").read_text(), third_party)
            self.assertEqual((root / "apt-mirrors.txt").read_text(), "https://archive.ubuntu.com/ubuntu/\tpriority:1\nhttps://archive.ubuntu.com/ubuntu/\tpriority:2\n")
            self.assertEqual(packages.configure(root), [])

    def test_direct_legacy_security_and_arm64_sources_keep_their_settings(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            sources = root / "sources.list.d"
            sources.mkdir()
            legacy = "deb [signed-by=/key.gpg] https://azure.archive.ubuntu.com/ubuntu noble main\n"
            (root / "sources.list").write_text(legacy)
            security = "Types: deb\nURIs: http://security.ubuntu.com/ubuntu/\nSuites: noble-security\nSigned-By: /key.gpg\n"
            ports = "Types: deb\nURIs: http://ports.ubuntu.com/ubuntu-ports/\nSuites: noble noble-updates\nArchitectures: arm64\nSigned-By: /key.gpg\n"
            (sources / "security.sources").write_text(security)
            (sources / "ports.sources").write_text(ports)
            self.assertEqual(len(packages.configure(root)), 3)
            self.assertEqual((root / "sources.list").read_text(), legacy.replace("https://azure.archive.ubuntu.com", "https://archive.ubuntu.com"))
            self.assertEqual((sources / "security.sources").read_text(), security.replace("http:", "https:"))
            self.assertEqual((sources / "ports.sources").read_text(), ports.replace("http:", "https:"))
