#!/usr/bin/env python3
"""Capture the local app and refresh the README banner and demo gallery."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess


def main():
    def interrupted(signum, _frame):
        raise SystemExit(128 + signum)

    signal.signal(signal.SIGTERM, interrupted)
    hub = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server", type=Path, default=hub / "server",
                        help="server checkout containing its client submodule")
    parser.add_argument("--theme", default="Midnight", help="exact built-in theme name")
    parser.add_argument("--audio-plugin", type=Path,
                        default=hub / "audio-plugins/rnnoise/dist/haunt-plugin.zip",
                        help="built RNNoise package used by the isolated demo server")
    args = parser.parse_args()
    server, plugin = args.server.resolve(), args.audio_plugin.resolve()
    client = server / "client"
    if not (server / "internal/clienttest/server_test.go").is_file():
        parser.error("--server must contain the Haunt server and its initialized client submodule")
    if not plugin.is_file():
        parser.error("Build RNNoise first, or pass --audio-plugin with its haunt-plugin.zip")
    if not (client / "node_modules/@playwright/test").is_dir():
        parser.error(f"Install client dependencies first: npm ci --prefix {client}")
    for command in ["go", "npm", "docker", "google-chrome"]:
        if not shutil.which(command):
            parser.error(f"Required command not found: {command}")
    environment = dict(os.environ, HAUNT_CLIENT_CHECK="demo",
                       HAUNT_DEMO_THEME=args.theme,
                       HAUNT_AUDIO_PLUGIN_TEST_PACKAGE=str(plugin))
    # The Go harness verifies chatxo-identity-check and its loopback port before
    # creating disposable fixture databases. No hosted login or deployment env.
    subprocess.run(["npm", "run", "build"], cwd=client, env=environment, check=True)
    try:
        subprocess.run(["npm", "run", "test:integration"], cwd=client,
                       env=environment, check=True, start_new_session=True)
    finally:
        subprocess.run(["go", "clean", "-cache", "-testcache"], cwd=server, check=True)
    captures = client / "test-results/demo"
    banner = json.loads((captures / "banner.json").read_text())
    for item in [*banner["sources"], banner["output"]]:
        actual = hashlib.sha256((captures / item["file"]).read_bytes()).hexdigest()
        if actual != item["sha256"]:
            raise RuntimeError(f"Capture checksum mismatch: {item['file']}")
    index = json.loads((captures / "index.json").read_text())
    destination = hub / "assets/demo"
    destination.mkdir(parents=True, exist_ok=True)
    for name in [*(shot["file"] for shot in index["shots"]),
                 "index.json", "banner.json", banner["output"]["file"]]:
        if Path(name).name != name:
            raise RuntimeError(f"Capture filename must be a basename: {name}")
        shutil.copyfile(captures / name, destination / name)
    print(f"Updated {destination / banner['output']['file']} ({args.theme})")
    print("Inspect the banner and gallery, then commit the refreshed assets.")


if __name__ == "__main__":
    main()
