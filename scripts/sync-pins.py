#!/usr/bin/env python3
"""Coordinate branch-specific component revisions and their embedded dependencies."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import configparser
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
IDENTITY = ["-c", "user.name=Haunt pin sync", "-c", "user.email=haunt-pins@users.noreply.github.com"]
PACKAGE_FILES = ["haunt-plugin.zip", "SHA256SUMS", "build.json", "THIRD-PARTY-NOTICES.txt"]


def git(directory, *args):
    return subprocess.check_output(["git", "-C", str(directory), *args], text=True).strip()


def components(root, branch):
    config = configparser.RawConfigParser()
    config.read(root / ".gitmodules")
    result = {}
    for section in config.sections():
        entry = dict(config[section])
        path = entry["path"]
        if Path(path).is_absolute() or ".." in Path(path).parts:
            raise ValueError("Invalid component path: " + path)
        tracking = entry["branch"]
        result[path] = {"url": entry["url"], "branch": branch if tracking == "." else tracking}
    if set(result) != {"client", "server", "sync", "audio-plugins/rnnoise", "extensions/tiktok-tts-plugin"}:
        raise ValueError("Unexpected coordinated component set")
    return result


def remote_heads(sources):
    def resolve(item):
        path, source = item
        reference = "refs/heads/" + source["branch"]
        rows = git(ROOT, "ls-remote", "--exit-code", source["url"], reference).splitlines()
        if len(rows) != 1 or rows[0].split()[1] != reference:
            raise ValueError("Missing component branch: " + path + "/" + source["branch"])
        return path, rows[0].split()[0]
    with ThreadPoolExecutor(max_workers=5) as pool:
        return dict(pool.map(resolve, sources.items()))


def pinned(root, path):
    entry = git(root, "ls-tree", "HEAD", path).split()
    if len(entry) != 4 or entry[0] != "160000":
        raise ValueError("Expected a component gitlink: " + path)
    return entry[2]


def require_clean(path):
    if git(path, "status", "--porcelain", "--untracked-files=no", "--ignore-submodules=all"):
        raise ValueError("Commit tracked changes before synchronizing: " + str(path))


def require_published(path):
    if not git(path, "branch", "--remotes", "--contains", "HEAD"):
        raise ValueError("Push component commits before synchronizing: " + str(path))


def checkout(path, source, revision):
    initialized = (path / ".git").exists()
    if not initialized:
        path.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "clone", "--no-checkout", source["url"], str(path)], check=True)
    else:
        require_clean(path)
    git(path, "fetch", "origin", "refs/heads/" + source["branch"])
    if git(path, "rev-parse", "FETCH_HEAD") != revision:
        raise ValueError("Component moved during synchronization; retry: " + str(path))
    if initialized:
        require_published(path)
    git(path, "checkout", "--detach", revision)


def commit(path, files, message):
    if files:
        git(path, "add", "--", *files)
    if not git(path, "diff", "--cached", "--name-only"):
        return False
    git(path, *IDENTITY, "commit", "-m", message)
    return True


def synchronize(root, branch, sources, heads, push=False):
    require_clean(root)
    if git(root, "ls-files", "--others", "--exclude-standard", "--", "docs/client", "docs/server", "docs/plugins/rnnoise"):
        raise ValueError("Move untracked files out of the generated documentation directories before synchronization")
    if git(root, "branch", "--show-current") != branch:
        raise ValueError("Check out the selected hub branch before synchronization")
    for name, source in sources.items():
        checkout(root / name, source, heads[name])
    server = root / "server"
    nested = server / "client"
    if not (nested / ".git").exists():
        subprocess.run(["git", "clone", "--no-checkout", sources["client"]["url"], str(nested)], check=True)
    else:
        require_clean(nested)
    git(nested, "fetch", "origin", "refs/heads/" + sources["client"]["branch"])
    require_published(nested)
    git(nested, "checkout", "--detach", heads["client"])
    distribution = root / "audio-plugins/rnnoise/dist"
    package = distribution / "haunt-plugin.zip"
    expected = (distribution / "SHA256SUMS").read_text().split()[0]
    if hashlib.sha256(package.read_bytes()).hexdigest() != expected:
        raise ValueError("RNNoise distribution checksum mismatch")
    bundled = server / "internal/audioplugin/default"
    for name in PACKAGE_FILES:
        source = root / "audio-plugins/rnnoise" / name if name == "THIRD-PARTY-NOTICES.txt" else distribution / name
        shutil.copyfile(source, bundled / name)
    server_changed = commit(server, ["client", *["internal/audioplugin/default/" + name for name in PACKAGE_FILES]],
                            "build: synchronize embedded client and RNNoise pins")
    previous_docs = set(json.loads((root / "docs/sources.json").read_text()))
    for script in ["check-pins.py", "sync-docs.py"]:
        subprocess.run(["python3", str(root / "scripts" / script)], cwd=root, check=True)
    current_docs = set(json.loads((root / "docs/sources.json").read_text()))
    owned = [*sources, "docs/sources.json", *sorted(previous_docs | current_docs)]
    git(root, "add", "--", *owned)
    subprocess.run(["python3", str(root / "scripts/check-docs.py")], cwd=root, check=True)
    changed = commit(root, [],
                     "build: synchronize " + branch + " component pins")
    if push:
        if server_changed:
            git(server, "push", "origin", "HEAD:refs/heads/" + branch)
        if changed:
            git(root, "push", "origin", "HEAD:refs/heads/" + branch)
    return {"changed": changed, "server_changed": server_changed, "revision": git(root, "rev-parse", "HEAD"),
            "branch": branch, "components": {path: git(root / path, "rev-parse", "HEAD") for path in sources}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--branch", required=True, choices=["main", "dev"])
    parser.add_argument("--check-remote", action="store_true")
    parser.add_argument("--push", action="store_true")
    args = parser.parse_args()
    sources = components(ROOT, args.branch)
    heads = remote_heads(sources)
    if args.check_remote:
        result = {"needed": any(pinned(ROOT, path) != revision for path, revision in heads.items())}
    else:
        result = synchronize(ROOT, args.branch, sources, heads, args.push)
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a") as output:
            for name in ["needed", "changed", "revision"]:
                if name in result:
                    output.write(name + "=" + (str(result[name]).lower() if isinstance(result[name], bool) else result[name]) + "\n")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
