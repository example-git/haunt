#!/usr/bin/env python3
import argparse
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import tarfile
import tempfile
from release import ROOT, load_plan, write


def validate_config(config):
    if config.get("kind") not in {"server", "sync"}:
        raise ValueError("Deployment kind must be server or sync")
    for name in ["ssh_target", "jump_host"]:
        if (name == "ssh_target" or name in config) and not re.fullmatch(r"[a-z_][a-z0-9_-]*@[A-Za-z0-9][A-Za-z0-9.-]*", config.get(name, "")):
            raise ValueError("Deployment " + name + " must be user@host")
    if type(config.get("ssh_port", 22)) is not int or not 1 <= config.get("ssh_port", 22) <= 65535:
        raise ValueError("Deployment ssh_port must be between 1 and 65535")
    required = ["binary", "data", "environment_file", "local_origin", "service", "database_port", "database_container", "arch", "preserved_files", "web_origin", "public_origins"] if config["kind"] == "server" else ["compose_directory", "container", "project", "updates_directory", "public_origins"]
    for key in required:
        if key not in config or config[key] in [None, "", []]:
            raise ValueError("Missing deployment configuration: " + key)
    if not config["public_origins"] or any(not re.fullmatch(r"https://[A-Za-z0-9.-]+", value) for value in config["public_origins"]):
        raise ValueError("Public deployment origins must use HTTPS")
    for key in ["binary", "data", "environment_file", "compose_directory", "updates_directory"]:
        if key in config and (not Path(config[key]).is_absolute() or ".." in Path(config[key]).parts):
            raise ValueError("Deployment paths must be absolute")
    if config["kind"] == "server":
        if config["arch"] not in {"amd64", "arm64"} or not isinstance(config["database_port"], int):
            raise ValueError("Invalid server deployment architecture or database port")
        if not all(Path(p).is_absolute() for p in config["preserved_files"]):
            raise ValueError("Preserved configuration paths must be absolute")
        if config["environment_file"] not in config["preserved_files"]:
            raise ValueError("The service environment must be included in preserved_files")
    return config


def ssh_command(config, key, hosts):
    validate_config(config)
    connection = ["ssh", "-F", "/dev/null", "-o", "BatchMode=yes", "-o", "IdentitiesOnly=yes", "-o", "StrictHostKeyChecking=yes", "-o", "ConnectTimeout=20", "-o", "UserKnownHostsFile=" + str(hosts), "-i", str(key)]
    proxy = ["-o", "ProxyCommand=" + shlex.join([*connection, "-W", "%h:%p", config["jump_host"]])] if "jump_host" in config else []
    return [*connection, *proxy, "-p", str(config.get("ssh_port", 22)), config["ssh_target"]]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("kind", choices=["server", "sync"])
    parser.add_argument("--plan", default="release/plan.json")
    parser.add_argument("--release", default="release/publish")
    args = parser.parse_args()
    plan = load_plan(args.plan)
    if plan["channel"] != "stable":
        raise ValueError("Development builds cannot deploy")
    config = validate_config(json.loads(os.environ["HAUNT_" + args.kind.upper() + "_DEPLOYMENT"]))
    if config["kind"] != args.kind:
        raise ValueError("Deployment target kind mismatch")
    key = os.environ["HAUNT_DEPLOY_SSH_KEY"]
    hosts = os.environ["HAUNT_DEPLOY_KNOWN_HOSTS"]
    if not key.strip() or not hosts.strip():
        raise ValueError("Deployment SSH authentication and pinned host keys are required")
    stage = "/var/backups/haunt/releases/" + plan["version"] + "-" + plan["revision"][:12] + "-" + args.kind
    with tempfile.TemporaryDirectory(prefix="haunt-deploy-") as temporary:
        temp = Path(temporary)
        (temp / "key").write_text(key + "\n")
        (temp / "key").chmod(0o600)
        (temp / "known_hosts").write_text(hosts + "\n")
        ssh = ssh_command(config, temp / "key", temp / "known_hosts")
        write(temp / "deployment.json", config)
        archive = temp / "deploy.tar.gz"
        with tarfile.open(archive, "w:gz") as bundle:
            for source, name in [(Path(args.plan), "plan.json"), (temp / "deployment.json", "deployment.json"),
                (ROOT / "scripts/deploy-remote.py", "deploy.py"), (ROOT / "scripts/sync-snapshot.py", "sync-snapshot.py"),
                (ROOT / "scripts/import-sync-updates.py", "import-sync-updates.py"), (ROOT / "client/static/updates.json", "publisher.json")]:
                bundle.add(source, arcname=name)
            for file in Path(args.release).iterdir():
                if file.is_file():
                    bundle.add(file, arcname="publish/" + file.name)
        quoted = shlex.quote(stage)
        command = "sudo install -d -m 700 " + quoted + " && sudo tar -xzf - -C " + quoted
        with archive.open("rb") as stream:
            subprocess.run([*ssh, command], stdin=stream, check=True)
        result = subprocess.run([*ssh, "sudo python3 " + shlex.quote(stage + "/deploy.py") + " " + quoted], text=True, stdout=subprocess.PIPE, check=True)
        records = [json.loads(line) for line in result.stdout.splitlines() if line.startswith("{")]
        if not records or records[-1].get("version") != plan["version"]:
            raise ValueError("Deployment completion record is missing")
        write(ROOT / "release" / (args.kind + "-deployment.json"), records[-1])
        print(json.dumps(records[-1]))


if __name__ == "__main__":
    main()
