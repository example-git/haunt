#!/usr/bin/env python3
import argparse
import json
from pathlib import Path

REPLACEMENTS = [
    ("http://azure.archive.ubuntu.com/ubuntu", "https://archive.ubuntu.com/ubuntu"),
    ("https://azure.archive.ubuntu.com/ubuntu", "https://archive.ubuntu.com/ubuntu"),
    ("http://archive.ubuntu.com/ubuntu", "https://archive.ubuntu.com/ubuntu"),
    ("http://security.ubuntu.com/ubuntu", "https://security.ubuntu.com/ubuntu"),
    ("http://ports.ubuntu.com/ubuntu-ports", "https://ports.ubuntu.com/ubuntu-ports"),
]


def configure(root):
    files = {root / "sources.list", *root.glob("apt-mirrors*.txt"),
             *(root / "sources.list.d").glob("*.sources"), *(root / "sources.list.d").glob("*.list")}
    changed = []
    for path in sorted(files):
        if not path.is_file():
            continue
        original = path.read_text()
        current = original
        for source, target in REPLACEMENTS:
            current = current.replace(source, target)
        if current != original:
            path.write_text(current)
            changed.append(str(path))
    return changed


def main():
    parser = argparse.ArgumentParser(description="Configure official Ubuntu HTTPS package endpoints on CI runners")
    parser.add_argument("--apt-root", type=Path, default=Path("/etc/apt"))
    args = parser.parse_args()
    print(json.dumps({"updated": configure(args.apt_root)}))


if __name__ == "__main__":
    main()
