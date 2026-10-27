#!/usr/bin/env python3
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parents[1]
REPO = "example-git/haunt"
STABLE = re.compile(r"(0|[1-9][0-9]{0,5})\.(0|[1-9][0-9]{0,5})\.(0|[1-9][0-9]{0,5})")
DEV = re.compile(STABLE.pattern + r"-dev\.([1-9][0-9]{0,14})")
DESKTOP = {
    "win32-x64": {"os": "windows-2022", "platform": "win", "arch": "x64"},
    "linux-x64": {"os": "ubuntu-24.04", "platform": "linux", "arch": "x64"},
    "linux-arm64": {"os": "ubuntu-24.04-arm", "platform": "linux", "arch": "arm64"},
    "darwin-arm64": {"os": "macos-14", "platform": "mac", "arch": "arm64"},
}
SERVICES = {
    f"{component}-linux-{arch}": {"component": component, "arch": arch,
        "os": "ubuntu-24.04-arm" if arch == "arm64" else "ubuntu-24.04"}
    for component in ["server", "sync"] for arch in ["amd64", "arm64"]
}
TARGETS = [*DESKTOP, "web", *SERVICES]


def run(*args, cwd=ROOT, **kwargs):
    return subprocess.check_output(args, cwd=cwd, text=True, **kwargs).strip()


def api(route, *args):
    return json.loads(run("gh", "api", route, *args))


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n")


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def stable_tuple(version):
    if not isinstance(version, str) or not STABLE.fullmatch(version):
        raise ValueError("Expected a stable X.Y.Z version")
    return tuple(map(int, version.split(".")))


def increment(version, bump):
    major, minor, patch = stable_tuple(version)
    if bump == "major":
        return f"{major + 1}.0.0"
    if bump == "minor":
        return f"{major}.{minor + 1}.0"
    if bump == "patch":
        return f"{major}.{minor}.{patch + 1}"
    raise ValueError("Unknown version increment")


def selected_targets(channel, raw):
    if channel == "stable":
        if raw:
            raise ValueError("Stable releases always build every target")
        return TARGETS.copy()
    if channel != "dev":
        raise ValueError("Unknown release channel")
    values = [x.strip() for x in raw.split(",")]
    if not values or any(x not in TARGETS for x in values):
        raise ValueError("Select targets from: " + ", ".join(TARGETS))
    if len(set(values)) != len(values):
        raise ValueError("Duplicate development target")
    return values


def load_plan(path):
    plan = json.loads(Path(path).read_text())
    if plan.get("schema") != 1 or plan.get("channel") not in {"dev", "stable"}:
        raise ValueError("Invalid release plan")
    pattern = STABLE if plan["channel"] == "stable" else DEV
    if not pattern.fullmatch(plan["version"]):
        raise ValueError("Release version does not match its channel")
    tag = ("dev-v" if plan["channel"] == "dev" else "v") + plan["version"]
    if plan.get("repository") != REPO or plan.get("tag") != tag:
        raise ValueError("Release repository or tag does not match its channel")
    if set(plan["components"]) != {"client", "server", "sync", "rnnoise"}:
        raise ValueError("Release plan has an invalid component set")
    expected = selected_targets(plan["channel"], ",".join(plan["targets"]) if plan["channel"] == "dev" else "")
    if plan["targets"] != expected:
        raise ValueError("Incomplete release target set")
    for revision in [plan["revision"], *plan["components"].values()]:
        if not re.fullmatch(r"[a-f0-9]{40}", revision):
            raise ValueError("Full source revisions are required")
    return plan


def github_output(values):
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a") as stream:
            for key, value in values.items():
                stream.write(key + "=" + (value if isinstance(value, str) else json.dumps(value, separators=(",", ":"))) + "\n")


def restore_artifact(name, directory, plan=None, target=None):
    pages = api(f"repos/{REPO}/actions/runs/{os.environ['GITHUB_RUN_ID']}/artifacts?per_page=100", "--paginate", "--slurp")
    candidates = [item for page in pages for item in page["artifacts"] if item["name"] == name]
    if any(item["expired"] for item in candidates):
        raise ValueError("Saved release artifact expired: " + name)
    if len(candidates) > 1:
        raise ValueError("Ambiguous saved artifact")
    if not candidates:
        if name == "release-plan" and int(os.environ.get("GITHUB_RUN_ATTEMPT", "1")) > 1:
            raise ValueError("No saved release plan is available; start a new workflow run")
        github_output({"restored": "false"})
        return False
    run("gh", "run", "download", os.environ["GITHUB_RUN_ID"], "--repo", REPO, "--name", name, "--dir", str(directory))
    if target:
        found = verify_artifacts(plan, Path(directory).parent, complete=False)
        if found.get(target) != Path(directory):
            raise ValueError("Saved artifact target mismatch")
    if name == "verified-release":
        if json.loads((Path(directory) / "haunt-release.json").read_text()) != {**plan, "schema": 2}:
            raise ValueError("Saved release belongs to another plan")
        for line in (Path(directory) / "SHA256SUMS").read_text().splitlines():
            expected, file = line.split("  ", 1)
            if Path(file).name != file or digest(Path(directory) / file) != expected:
                raise ValueError("Saved release artifact is damaged")
    github_output({"restored": "true", "artifact_id": str(candidates[0]["id"])})
    print(json.dumps({"reused_artifact": name, "id": candidates[0]["id"], "run_id": os.environ["GITHUB_RUN_ID"]}))
    return True


def plan_release(args):
    if args.channel == "stable" and os.environ.get("GITHUB_REF", "refs/heads/main") != "refs/heads/main":
        raise ValueError("Stable releases must run from main")
    output = Path(args.plan)
    revision = run("git", "rev-parse", "HEAD")
    if output.exists():
        plan = load_plan(output)
        if plan["revision"] != revision or plan["channel"] != args.channel:
            raise ValueError("Saved release plan belongs to a different source or channel")
        if args.version and plan["version"] != args.version:
            raise ValueError("Saved release version cannot be changed during retry")
        if args.targets and selected_targets(args.channel, args.targets) != plan["targets"]:
            raise ValueError("Saved release targets cannot be changed during retry")
    else:
        releases = json.loads(run("gh", "release", "list", "--repo", REPO, "--exclude-pre-releases", "--limit", "100", "--json", "tagName,isPrerelease,isDraft"))
        versions = [r["tagName"][1:] for r in releases if not r["isPrerelease"] and r["tagName"].startswith("v") and STABLE.fullmatch(r["tagName"][1:])]
        if not versions:
            raise ValueError("A stable hub release is required to establish the version baseline")
        latest = max(versions, key=stable_tuple)
        version = args.version or increment(latest, args.bump)
        stable_tuple(version)
        if stable_tuple(version) <= stable_tuple(latest):
            raise ValueError("Release version must exceed reserved and published versions")
        if args.channel == "dev":
            if not re.fullmatch(r"[1-9][0-9]{0,14}", os.environ.get("GITHUB_RUN_NUMBER", "")):
                raise ValueError("Development builds require a GitHub run number")
            version += "-dev." + os.environ["GITHUB_RUN_NUMBER"]
        components = {name: run("git", "ls-tree", "HEAD", path).split()[2] for name, path in {
            "client": "client", "server": "server", "sync": "sync", "rnnoise": "audio-plugins/rnnoise"}.items()}
        plan = {"schema": 1, "repository": REPO, "channel": args.channel, "version": version,
            "revision": revision, "components": components, "targets": selected_targets(args.channel, args.targets),
            "run_id": os.environ["GITHUB_RUN_ID"], "tag": ("dev-v" if args.channel == "dev" else "v") + version}
        write(output, plan)
    github_output({"version": plan["version"], "tag": plan["tag"], "targets": plan["targets"],
        "desktop": {"include": [{"target": t, **DESKTOP[t]} for t in plan["targets"] if t in DESKTOP]},
        "services": {"include": [{"target": t, **SERVICES[t]} for t in plan["targets"] if t in SERVICES]},
        "has_desktop": str(any(t in DESKTOP for t in plan["targets"])).lower(),
        "has_services": str(any(t in SERVICES for t in plan["targets"])).lower(),
        "has_web": str("web" in plan["targets"]).lower()})
    print(json.dumps(plan))


def stamp(plan, directory):
    directory = Path(directory).resolve()
    run("node", str(ROOT / "client/scripts/version-main.mjs"), plan["version"], str(directory))
    if plan["channel"] == "dev":
        file = directory / "electron-builder.config.json"
        config = json.loads(file.read_text())
        config.update(appId="com.exampleuser.haunt.dev", productName="Haunt Dev")
        config["win"]["executableName"] = "haunt-dev"
        config["linux"]["executableName"] = "haunt-dev"
        config["linux"]["target"] = [{"target": "AppImage"}]
        config["protocols"] = [{"name": "Haunt development links", "schemes": ["haunt-dev"]}]
        config["mac"]["extraResources"] = [entry for entry in config["mac"]["extraResources"] if entry["to"] != "local-install"]
        config["dmg"]["contents"] = [{"x": 140, "y": 170}, {"x": 400, "y": 170, "type": "link", "path": "/Applications"}]
        write(file, config)
        for name in ["package.json", "electron-app/package.json"]:
            file = directory / name
            value = json.loads(file.read_text())
            value.update(productName="Haunt Dev", desktopName="com.exampleuser.haunt.dev.desktop")
            write(file, value)


def describe(plan, target, directory):
    if target not in plan["targets"]:
        raise ValueError("Target was not selected")
    directory = Path(directory)
    files = []
    for file in sorted(directory.iterdir()):
        if file.name in {"SHA256SUMS", "target.json"}:
            continue
        if file.is_symlink() or not file.is_file() or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,160}", file.name):
            raise ValueError("Unsafe build artifact")
        files.append({"file": file.name, "size": file.stat().st_size, "sha256": digest(file)})
    if not files:
        raise ValueError("Build produced no artifacts")
    write(directory / "target.json", {"schema": 1, "target": target, "version": plan["version"],
        "channel": plan["channel"], "revision": plan["revision"], "components": plan["components"], "files": files})
    (directory / "SHA256SUMS").write_text("".join(f"{a['sha256']}  {a['file']}\n" for a in files))


def verify_artifacts(plan, directory, complete=True):
    directory = Path(directory)
    found = {}
    for metadata in directory.glob("*/target.json"):
        item = json.loads(metadata.read_text())
        target = item["target"]
        if target not in plan["targets"] or target in found:
            raise ValueError("Unexpected or duplicate build target")
        if any(item[key] != plan[key] for key in ["version", "channel", "revision", "components"]):
            raise ValueError("Artifact source does not match the release plan")
        actual = {p.name for p in metadata.parent.iterdir() if p.name not in {"SHA256SUMS", "target.json"}}
        if actual != {a["file"] for a in item["files"]} or not actual:
            raise ValueError("Artifact inventory mismatch")
        for asset in item["files"]:
            name = asset["file"]
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,160}", name):
                raise ValueError("Unsafe artifact name")
            file = metadata.parent / name
            if file.is_symlink() or file.stat().st_size != asset["size"] or digest(file) != asset["sha256"]:
                raise ValueError("Build artifact checksum mismatch: " + name)
        found[target] = metadata.parent
    if complete and set(found) != set(plan["targets"]):
        raise ValueError("Missing targets: " + ", ".join(sorted(set(plan["targets"]) - set(found))))
    return found


def copy_checked(source, destination):
    if destination.exists() and digest(source) != digest(destination):
        raise ValueError("Conflicting artifact filename: " + destination.name)
    shutil.copyfile(source, destination)


def assemble(plan, directory, output):
    if plan["channel"] != "stable":
        raise ValueError("Only stable releases can create update feeds")
    found = verify_artifacts(plan, directory)
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    client = output / ".client"
    client.mkdir(exist_ok=True)
    for target in DESKTOP:
        for file in found[target].iterdir():
            if file.name not in {"target.json", "SHA256SUMS"}:
                copy_checked(file, client / file.name)
    run("node", "scripts/release-client.mjs", "manifest", str(client), cwd=ROOT / "client")
    envelope = json.loads((client / "haunt-updates.json").read_text())
    payload = json.loads(base64.b64decode(envelope["payload"]))
    if payload["version"] != plan["version"] or set(payload["targets"]) != set(DESKTOP):
        raise ValueError("Signed desktop release is incomplete")
    for target in payload["targets"].values():
        for kind in ["asar", "installer", "rpm"]:
            if kind in target:
                copy_checked(client / target[kind]["file"], output / target[kind]["file"])
    copy_checked(client / "haunt-updates.json", output / "haunt-updates.json")
    server = {"schema": 1, "version": plan["version"], "platforms": {}}
    for target, folder in found.items():
        if target in DESKTOP:
            continue
        for file in folder.iterdir():
            if file.name in {"target.json", "SHA256SUMS", "haunt-app.json"} or file.name.endswith(".docker.tar.gz"):
                continue
            copy_checked(file, output / file.name)
        if target.startswith("server-"):
            app = json.loads((folder / "haunt-app.json").read_text())
            arch = SERVICES[target]["arch"]
            platform = "linux/" + arch
            if app["version"] != plan["version"] or set(app["platforms"]) != {platform}:
                raise ValueError("Server application target mismatch")
            if server.get("runtime", app["runtime"]) != app["runtime"]:
                raise ValueError("Server runtime mismatch")
            server["runtime"] = app["runtime"]
            asset = app["platforms"][platform]
            path = folder / asset["asset"]
            if path.stat().st_size != asset["bytes"] or digest(path) != asset["sha256"]:
                raise ValueError("Server application archive mismatch")
            with tarfile.open(path) as archive:
                metadata = json.load(archive.extractfile("release.json"))
                header = archive.extractfile("haunt").read(20)
                if metadata != {"schema": 1, "version": plan["version"], "runtime": app["runtime"], "platform": platform} or header[:4] != b"\x7fELF" or struct.unpack("<H", header[18:20])[0] != {"amd64": 62, "arm64": 183}[arch]:
                    raise ValueError("Server executable or release metadata mismatch")
            asset["url"] = f"https://github.com/{REPO}/releases/download/{plan['tag']}/{path.name}"
            server["platforms"][platform] = asset
    write(output / "haunt-app.json", server)
    shutil.copyfile(ROOT / "audio-plugins/rnnoise/dist/haunt-plugin.zip", output / "haunt-plugin-rnnoise.zip")
    write(output / "haunt-release.json", {**plan, "schema": 2})
    files = [p for p in sorted(output.iterdir()) if p.is_file() and p.name != "SHA256SUMS"]
    (output / "SHA256SUMS").write_text("".join(f"{digest(p)}  {p.name}\n" for p in files))


def optional_api(route):
    result = subprocess.run(["gh", "api", route], cwd=ROOT, text=True, capture_output=True)
    if result.returncode:
        try:
            error = json.loads(result.stdout)
        except json.JSONDecodeError:
            raise RuntimeError("Could not inspect the release") from None
        if str(error.get("status")) == "404":
            return None
        raise RuntimeError(f"Release API returned {error.get('status')}: {error.get('message')}")
    return json.loads(result.stdout)


def find_release(tag):
    published = optional_api(f"repos/{REPO}/releases/tags/{tag}")
    if published:
        return published
    page = 1
    while True:
        releases = api(f"repos/{REPO}/releases?per_page=100&page={page}")
        found = next((release for release in releases if release["tag_name"] == tag), None)
        if found or len(releases) < 100:
            return found
        page += 1


def ensure_release(plan, draft=False):
    release = find_release(plan["tag"])
    reference = optional_api(f"repos/{REPO}/git/ref/tags/{plan['tag']}")
    if reference:
        ref = reference["object"]
        for _ in range(8):
            if ref["type"] != "tag":
                break
            ref = api(f"repos/{REPO}/git/tags/{ref['sha']}")["object"]
        if ref["type"] != "commit" or ref["sha"] != plan["revision"]:
            raise ValueError("Release tag belongs to different source")
    if release:
        if release["prerelease"] != (plan["channel"] == "dev"):
            raise ValueError("Release channel conflict")
        if not reference and not (release["draft"] and release["target_commitish"] == plan["revision"]):
            raise ValueError("Release source tag is missing")
        return release
    return api(f"repos/{REPO}/releases", "--method", "POST", "-f", "tag_name=" + plan["tag"],
        "-f", "target_commitish=" + plan["revision"], "-f", "name=Haunt " + plan["version"],
        "-f", "body=Components and source revisions are recorded in haunt-release.json.",
        "-f", "make_latest=false", "-F", "prerelease=" + str(plan["channel"] == "dev").lower(),
        "-F", "draft=" + str(draft).lower())


def upload(plan, files, draft=False):
    release = ensure_release(plan, draft)
    existing = {asset["name"]: asset for asset in release["assets"]}
    for path in files:
        if path.name in existing:
            asset = existing[path.name]
            if asset["size"] != path.stat().st_size:
                raise ValueError("Published artifact differs: " + path.name)
            if asset.get("digest"):
                if asset["digest"] != "sha256:" + digest(path):
                    raise ValueError("Published artifact differs: " + path.name)
                continue
            with tempfile.TemporaryDirectory() as temporary:
                run("gh", "release", "download", plan["tag"], "--repo", REPO, "--pattern", path.name, "--dir", temporary)
                if digest(Path(temporary) / path.name) != digest(path):
                    raise ValueError("Published artifact differs: " + path.name)
        else:
            run("gh", "release", "upload", plan["tag"], "--repo", REPO, str(path))


def dev_upload(plan, target, directory):
    if plan["channel"] != "dev" or target not in plan["targets"]:
        raise ValueError("Development publication requires a selected dev target")
    directory = Path(directory)
    verify_artifacts(plan, directory.parent, complete=False)
    upload(plan, [directory / item["file"] for item in json.loads((directory / "target.json").read_text())["files"]
        if not item["file"].endswith(".docker.tar.gz")])
    with tempfile.TemporaryDirectory() as temporary:
        target_file = Path(temporary) / (target + ".provenance.json")
        shutil.copyfile(directory / "target.json", target_file)
        upload(plan, [target_file])


def publish_images(plan, artifacts, promote=False):
    if plan["channel"] != "stable":
        raise ValueError("Development builds cannot publish stable container images")
    found = verify_artifacts(plan, artifacts)
    records = {}
    for component, repository in [("server", "haunt"), ("sync", "haunt-sync")]:
        image = "ghcr.io/example-git/" + repository
        sources = []
        if not promote:
            for arch in ["amd64", "arm64"]:
                directory = found[f"{component}-linux-{arch}"]
                archive = next(directory.glob("*.docker.tar.gz"))
                subprocess.run(["docker", "load", "--input", str(archive)], check=True, stdout=subprocess.DEVNULL)
                local = "haunt:check" if component == "server" else "haunt-sync:check"
                info = json.loads(run("docker", "image", "inspect", local))[0]
                labels = info["Config"]["Labels"]
                if info["Architecture"] != arch or labels["org.opencontainers.image.version"] != plan["version"] or labels["vg.xo.haunt.hub-revision"] != plan["revision"]:
                    raise ValueError("Container image does not match the tested release")
                if labels["org.opencontainers.image.revision"] != plan["components"][component]:
                    raise ValueError("Container component source mismatch")
                if labels["vg.xo.haunt.client-revision"] != plan["components"]["client"]:
                    raise ValueError("Container client source mismatch")
                tag = image + ":" + plan["version"] + "-" + arch
                run("docker", "tag", local, tag)
                run("docker", "push", tag)
                sources.append(json.loads(run("docker", "image", "inspect", tag))[0]["RepoDigests"][0])
            run("docker", "buildx", "imagetools", "create", "--tag", image + ":" + plan["version"], *sources)
        raw = run("docker", "buildx", "imagetools", "inspect", image + ":" + plan["version"], "--raw")
        manifest = json.loads(raw)
        if {(m["platform"]["os"], m["platform"]["architecture"]) for m in manifest["manifests"]} != {("linux", "amd64"), ("linux", "arm64")}:
            raise ValueError("Incomplete container platform set")
        with tempfile.TemporaryDirectory(prefix="haunt-public-image-") as empty_config:
            anonymous = json.loads(run("docker", "buildx", "imagetools", "inspect", image + ":" + plan["version"], "--raw", env={**os.environ, "DOCKER_CONFIG": empty_config}))
            if anonymous != manifest:
                raise ValueError("Anonymous container manifest differs from the release")
        if promote:
            run("docker", "buildx", "imagetools", "create", "--tag", image + ":latest", image + ":" + plan["version"])
            if json.loads(run("docker", "buildx", "imagetools", "inspect", image + ":latest", "--raw")) != manifest:
                raise ValueError("Latest image differs from verified release")
        records[component] = {"image": image + ":" + plan["version"], "manifest": manifest}
    write(ROOT / "release/images.json", records)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["plan", "restore-plan", "restore-target", "restore-release", "reserve", "stamp", "describe", "assemble", "dev-upload", "publish", "images", "activate", "promote", "summary"])
    parser.add_argument("--plan", default="release/plan.json")
    parser.add_argument("--channel", choices=["stable", "dev"])
    parser.add_argument("--bump", choices=["patch", "minor", "major"], default="patch")
    parser.add_argument("--version", default="")
    parser.add_argument("--targets", default="")
    parser.add_argument("--target")
    parser.add_argument("--directory", default="release/artifacts")
    parser.add_argument("--output", default="release/publish")
    args = parser.parse_args()
    if args.command == "restore-plan":
        restore_artifact("release-plan", Path(args.plan).parent)
        return
    if args.command == "plan":
        plan_release(args)
        return
    plan = load_plan(args.plan)
    if args.command == "restore-target":
        if args.target not in plan["targets"]:
            raise ValueError("Cannot restore an unselected target")
        restore_artifact("build-" + args.target, args.directory, plan, args.target)
    elif args.command == "restore-release":
        restore_artifact("verified-release", args.output, plan)
    elif args.command == "reserve":
        ensure_release(plan, draft=plan["channel"] == "stable")
        if plan["channel"] == "dev":
            file = ROOT / "release/haunt-release.json"
            write(file, {**plan, "schema": 2})
            upload(plan, [file])
    elif args.command == "stamp":
        stamp(plan, args.directory)
    elif args.command == "describe":
        describe(plan, args.target, args.directory)
    elif args.command == "assemble":
        assemble(plan, args.directory, args.output)
    elif args.command == "dev-upload":
        dev_upload(plan, args.target, args.directory)
    elif args.command == "publish":
        if plan["channel"] != "stable":
            raise ValueError("Stable publication requires a stable release plan")
        output = Path(args.output)
        upload(plan, [p for p in output.iterdir() if p.is_file()], draft=True)
        run("gh", "release", "edit", plan["tag"], "--repo", REPO, "--draft=false", "--latest=false")
    elif args.command in {"images", "promote"}:
        publish_images(plan, args.directory, args.command == "promote")
        if args.command == "promote":
            run("gh", "release", "edit", plan["tag"], "--repo", REPO, "--latest")
    elif args.command == "activate":
        if plan["channel"] != "stable":
            raise ValueError("Development builds cannot activate stable feeds")
        run("gh", "release", "edit", plan["tag"], "--repo", REPO, "--latest")
    elif args.command == "summary":
        if plan["channel"] != "stable":
            raise ValueError("Stable completion requires a stable release")
        record = json.loads((ROOT / "release/public-verification.json").read_text())
        if not record.get("passed") or record["version"] != plan["version"]:
            raise ValueError("Public deployment verification is incomplete")
        text = f"Haunt {plan['version']} published and deployed.\n\nSource: `{plan['revision']}`\n\nAll target builds, signatures, hashes, native upgrades and public deployments verified."
        run("gh", "release", "edit", plan["tag"], "--repo", REPO, "--notes", text)
        if os.environ.get("GITHUB_STEP_SUMMARY"):
            with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as stream:
                stream.write(text + "\n")


if __name__ == "__main__":
    main()
