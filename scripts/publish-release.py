#!/usr/bin/env python3
"""Assemble verified pinned component artifacts into the central release.

Uses the operator's existing gh authentication. Signing keys stay in the client
repository. Downloads are cached in ignored release/ and checked on every run.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import struct
import subprocess
import tarfile

ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = "example-git/haunt"
SEMVER = re.compile(r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)")


def run(*args):
    return subprocess.check_output(args, cwd=ROOT, text=True).strip()


def api(path):
    return json.loads(run("gh", "api", path))


def sha(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def tag_commit(repo, tag):
    item = api(f"repos/{repo}/git/ref/tags/{tag}")["object"]
    for _ in range(8):
        if item["type"] == "commit":
            return item["sha"]
        if item["type"] != "tag":
            break
        item = api(f"repos/{repo}/git/tags/{item['sha']}")["object"]
    raise ValueError("Release tag must resolve to a commit")


def download(repo, tag, revision, directory):
    if tag_commit(repo, tag) != revision:
        raise ValueError(f"{repo}/{tag} does not match its master source pin")
    release = api(f"repos/{repo}/releases/tags/{tag}")
    if release["draft"] or release["prerelease"]:
        raise ValueError("Only completed stable component releases can be published")
    directory.mkdir(parents=True, exist_ok=True)
    run("gh", "release", "download", tag, "--repo", repo, "--dir", str(directory), "--skip-existing")
    for asset in release["assets"]:
        name = asset["name"]
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,160}", name):
            raise ValueError("Unsafe release asset name")
        path = directory / name
        if path.stat().st_size != asset["size"]:
            raise ValueError(f"Asset size mismatch: {name}")
        digest = asset.get("digest")
        if digest and digest != "sha256:" + sha(path):
            raise ValueError(f"GitHub asset digest mismatch: {name}")
    return release


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("version")
    parser.add_argument("--server-tag")
    parser.add_argument("--publish", action="store_true", help="Publish after verification; otherwise stage only")
    args = parser.parse_args()
    if not SEMVER.fullmatch(args.version):
        parser.error("Version must be major.minor.patch")
    run("python3", "scripts/check-pins.py")
    revision = run("git", "rev-parse", "HEAD")
    client_revision = run("git", "-C", "client", "rev-parse", "HEAD")
    server_revision = run("git", "-C", "server", "rev-parse", "HEAD")
    client_version = json.loads((ROOT / "client/package.json").read_text())["version"]
    client_tag = "client-v" + client_version
    server_tag = args.server_tag or "server-v" + args.version
    if not server_tag.startswith("server-v") or not SEMVER.fullmatch(server_tag[8:]):
        parser.error("Server tag must be server-vMAJOR.MINOR.PATCH")
    tag = "v" + args.version
    output = ROOT / "release" / tag
    client = output / ".client"
    server = output / ".server"
    download("example-git/haunt-client", client_tag, client_revision, client)
    download("example-git/haunt-server", server_tag, server_revision, server)

    # Use the same signature verifier as the shipped permanent desktop launcher.
    verify = r"""
    const fs=require('node:fs');
    const {verifyManifest}=require('./client/apps/desktop/updates.cjs');
    const config=JSON.parse(fs.readFileSync('client/static/updates.json'));
    const envelope=JSON.parse(fs.readFileSync(process.argv[1]));
    for (const target of ['win32-x64','linux-x64','linux-arm64','darwin-arm64']) {
      const [platform,arch]=target.split('-'); verifyManifest(envelope,config,platform,arch);
    }
    process.stdout.write(Buffer.from(envelope.payload,'base64'));
    """
    signed = json.loads(run("node", "-e", verify, str(client / "haunt-updates.json")))
    if signed["version"] != client_version:
        raise ValueError("Signed client version does not match the source pin")
    if set(signed["targets"]) != {"win32-x64", "linux-x64", "linux-arm64", "darwin-arm64"}:
        raise ValueError("Unexpected signed client platform set")
    selected = [client / "haunt-updates.json"]
    for target in signed["targets"].values():
        for key in ["asar", "installer"]:
            artifact = target[key]
            path = client / artifact["file"]
            if path.stat().st_size != artifact["size"] or sha(path) != artifact["sha256"]:
                raise ValueError("Signed client artifact mismatch")
            selected.append(path)

    manifest = json.loads((server / "haunt-app.json").read_text())
    if manifest["version"] != server_tag[8:] or set(manifest["platforms"]) != {"linux/amd64", "linux/arm64"}:
        raise ValueError("Server manifest version or platform mismatch")
    checksums = dict((name.lstrip("*"), digest) for digest, name in
                     (line.split(maxsplit=1) for line in (server / "SHA256SUMS").read_text().splitlines()))
    for name, digest in checksums.items():
        if Path(name).name != name or sha(server / name) != digest:
            raise ValueError("Server release checksum mismatch")
    for platform, artifact in manifest["platforms"].items():
        name = artifact["asset"]
        if name != "haunt-app-linux-" + platform.split("/")[1] + ".tar.gz":
            raise ValueError("Unexpected application asset name")
        path = server / name
        if path.stat().st_size != artifact["bytes"] or sha(path) != artifact["sha256"]:
            raise ValueError("Application archive checksum mismatch")
        with tarfile.open(path) as bundle:
            metadata = json.load(bundle.extractfile("release.json"))
            binary = bundle.extractfile("haunt").read(20)
            if (metadata["version"] != manifest["version"] or metadata["platform"] != platform or
                    metadata["runtime"] != manifest["runtime"] or binary[:4] != b"\x7fELF" or
                    struct.unpack("<H", binary[18:20])[0] != {"linux/amd64": 62, "linux/arm64": 183}[platform]):
                raise ValueError("Application archive metadata or executable mismatch")
        artifact["url"] = f"https://github.com/{REPOSITORY}/releases/download/{tag}/{name}"
        selected += [path, server / ("haunt-server-linux-" + platform.split("/")[1])]

    output.mkdir(parents=True, exist_ok=True)
    for path in selected:
        shutil.copyfile(path, output / path.name)
    (output / "haunt-app.json").write_text(json.dumps(manifest, indent=2) + "\n")
    shutil.copyfile(ROOT / "audio-plugins/rnnoise/dist/haunt-plugin.zip", output / "haunt-plugin-rnnoise.zip")
    provenance = {"schema": 1, "version": args.version, "repository": REPOSITORY, "revision": revision,
                  "client": {"revision": client_revision, "tag": client_tag, "version": client_version},
                  "server": {"revision": server_revision, "tag": server_tag, "version": manifest["version"]},
                  "rnnoise": {"revision": run("git", "-C", "audio-plugins/rnnoise", "rev-parse", "HEAD")},
                  "image": f"ghcr.io/{REPOSITORY}:{args.version}"}
    (output / "haunt-release.json").write_text(json.dumps(provenance, indent=2) + "\n")
    files = sorted(path for path in output.iterdir() if path.is_file() and path.name not in {"SHA256SUMS", "release-notes.md"})
    (output / "SHA256SUMS").write_text("".join(f"{sha(path)}  {path.name}\n" for path in files))
    notes = output / "release-notes.md"
    notes.write_text(f"Haunt {args.version}: coordinated downloads and container application updates.\n\n"
                     f"Client {client_version} (`{client_revision}`), server {manifest['version']} (`{server_revision}`).\n"
                     "Client manifests and payloads retain their original verified signatures and bytes.\n\n"
                     f"Container: `ghcr.io/{REPOSITORY}:{args.version}` for Linux amd64 and arm64.\n"
                     "Installation, first-owner credentials and member invitations: [central guide](https://github.com/example-git/haunt/blob/main/docs/installation.md).\n")
    print(f"Verified and staged {len(files)} files in {output}")
    if args.publish:
        if tag_commit(REPOSITORY, tag) != revision:
            raise ValueError("Master release tag does not match this checkout")
        existing = subprocess.run(["gh", "release", "view", tag, "--repo", REPOSITORY, "--json", "isDraft"], capture_output=True, text=True)
        if existing.returncode == 0:
            if not json.loads(existing.stdout)["isDraft"]:
                raise ValueError("Refusing to replace an already published master release")
        else:
            run("gh", "release", "create", tag, "--repo", REPOSITORY, "--verify-tag", "--draft", "--title", "Haunt " + args.version, "--notes-file", str(notes))
        run("gh", "release", "upload", tag, "--repo", REPOSITORY, "--clobber", *map(str, files), str(output / "SHA256SUMS"))
        run("gh", "release", "edit", tag, "--repo", REPOSITORY, "--draft=false", "--notes-file", str(notes))
        print(f"Published https://github.com/{REPOSITORY}/releases/tag/{tag}")


if __name__ == "__main__":
    main()
