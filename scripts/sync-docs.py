#!/usr/bin/env python3
"""Centralize documentation from the exact source pins, with working links."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
COMPONENTS = {"server": "haunt-server", "client": "haunt-client", "audio-plugins/rnnoise": "haunt-audio-rnnoise"}
LINK = re.compile(r"(!?\[[^\]]*\]\()([^\s)]+)(\))")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    mapping, revisions = {}, {}
    for component in COMPONENTS:
        base = ROOT / component
        revisions[component] = subprocess.check_output(["git", "-C", str(base), "rev-parse", "HEAD"], text=True).strip()
        destination = ROOT / "docs" / ("plugins/rnnoise" if component == "audio-plugins/rnnoise" else component)
        for path in (base / "docs").rglob("*"):
            if path.is_file() and path.suffix in {".md", ".json"}:
                mapping[path.resolve()] = destination / path.relative_to(base / "docs")
        mapping[(base / "README.md").resolve()] = destination / "index.md"
    sources = {}
    failed = []
    for path, destination in sorted(mapping.items()):
        component = next(key for key in COMPONENTS if path.is_relative_to(ROOT / key))
        base = ROOT / component
        repo = "example-git/" + COMPONENTS[component]
        relative = path.relative_to(base)
        original = path.read_bytes()
        content = original
        if path.suffix == ".md":
            text = original.decode()
            if component == "server" and relative == Path("docs/container.md"):
                text = text.replace("HAUNT_APP_UPDATE_REPOSITORY=example-git/haunt-server",
                                    "HAUNT_APP_UPDATE_REPOSITORY=example-git/haunt")
                text = text.replace("The `All-in-one container` GitHub workflow", "The hub's `Hub stable release` GitHub workflow")
                text = "For the published image and first-login instructions, use the [central installation guide](../installation.md). The detailed source-build and runtime guide follows.\n\n" + text
            def link(match):
                target = match[2]
                if target.startswith(("#", "/", "http:", "https:", "mailto:", "data:")):
                    return match[0]
                target_path, separator, anchor = target.partition("#")
                resolved = (path.parent / target_path).resolve()
                shared_assets = {
                    "haunt-wordmark.png": ROOT / "assets/haunt-wordmark.png",
                    "09-voice-pip.png": ROOT / "assets/demo/09-voice-pip.png",
                    "07-audio-plugin.png": ROOT / "assets/demo/07-audio-plugin.png",
                }
                if resolved in mapping:
                    target = os.path.relpath(mapping[resolved], destination.parent)
                elif resolved.parent == base / "assets" and resolved.name in shared_assets:
                    target = os.path.relpath(shared_assets[resolved.name], destination.parent)
                else:
                    if not resolved.is_relative_to(base):
                        return match[0]
                    relative_target = resolved.relative_to(base).as_posix()
                    target = f"https://github.com/{repo}/blob/{revisions[component]}/{relative_target}"
                if separator:
                    target += "#" + anchor
                return match[1] + target + match[3]
            text = LINK.sub(link, text)
            text = re.sub(r"https://github.com/example-git/haunt-(server|client)/blob/main/docs/([^\s)]+)",
                          lambda m: "https://github.com/example-git/haunt/blob/main/docs/" + m[1] + "/" + m[2], text)
            source = f"https://github.com/{repo}/blob/{revisions[component]}/{relative}"
            content = (f"> Documentation from the pinned [{repo}]({source}) source. Refresh with `python3 scripts/sync-docs.py`.\n\n" + text).encode()
        sources[destination.relative_to(ROOT).as_posix()] = {"repository": repo, "revision": revisions[component],
                                                           "path": relative.as_posix(), "source_sha256": hashlib.sha256(original).hexdigest()}
        if args.check:
            if not destination.is_file() or destination.read_bytes() != content:
                failed.append(str(destination.relative_to(ROOT)))
        else:
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(content)
    index = ROOT / "docs/sources.json"
    content = (json.dumps(sources, indent=2, sort_keys=True) + "\n").encode()
    if args.check:
        if not index.is_file() or index.read_bytes() != content:
            failed.append("docs/sources.json")
    else:
        index.write_bytes(content)
    if failed:
        raise SystemExit("Documentation differs from pinned inputs: " + ", ".join(failed))
    print(f"{'Checked' if args.check else 'Centralized'} {len(sources)} documentation files")


if __name__ == "__main__":
    main()
