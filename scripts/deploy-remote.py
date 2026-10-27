#!/usr/bin/env python3
import base64
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
import time
import urllib.parse
import urllib.request


def run(*args, **kwargs):
    result = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **kwargs)
    if result.returncode:
        raise RuntimeError("Deployment command failed: " + args[0])
    return result.stdout.decode().strip()


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def read(origin, route, headers=None):
    with urllib.request.urlopen(urllib.request.Request(origin + route, headers=headers or {}), timeout=10) as response:
        return json.load(response), response.headers


def ready(check, seconds=90):
    deadline = time.monotonic() + seconds
    while True:
        try:
            return check()
        except Exception as error:
            if time.monotonic() >= deadline:
                raise RuntimeError("Deployment did not become ready") from error
            time.sleep(1)


def check(condition, message):
    if not condition:
        raise ValueError(message)


def atomic_file(source, destination, mode=0o755):
    destination = Path(destination)
    stage = destination.with_name(destination.name + ".haunt-release")
    created = False
    try:
        with stage.open("xb") as stream:
            created = True
            with Path(source).open("rb") as original:
                shutil.copyfileobj(original, stream)
            stream.flush()
            os.fchmod(stream.fileno(), mode)
            os.fsync(stream.fileno())
        os.replace(stage, destination)
    finally:
        if created:
            stage.unlink(missing_ok=True)


def server(stage, config, plan):
    binary = Path(config["binary"])
    data = Path(config["data"])
    service = config["service"]
    prop = lambda name: run("systemctl", "show", service, "--property=" + name, "--value")
    pid = prop("MainPID")
    check(prop("ActiveState") == "active", "Server service is not active")
    live = dict(x.split("=", 1) for x in Path("/proc/" + pid + "/environ").read_bytes().decode().split("\0") if "=" in x)
    connection = urllib.parse.urlsplit(live["HAUNT_DATABASE_URL"])
    check(connection.hostname == "127.0.0.1" and connection.port == config["database_port"], "Unexpected database endpoint")
    container = config["database_container"]
    check(run("docker", "port", container, "5432/tcp") == "127.0.0.1:" + str(config["database_port"]), "Database binding changed")
    env = {**os.environ, "PGUSER": urllib.parse.unquote(connection.username or ""),
        "PGPASSWORD": urllib.parse.unquote(connection.password or ""), "PGDATABASE": urllib.parse.unquote(connection.path[1:])}
    db = ["docker", "exec", "-i", "-e", "PGUSER", "-e", "PGPASSWORD", "-e", "PGDATABASE", "-e", "PGHOST=127.0.0.1", "-e", "PGSSLMODE=disable", container]
    sql = lambda query: run(*db, "psql", "-X", "-At", "-v", "ON_ERROR_STOP=1", "-c", query, env=env)
    schema = sql("SELECT max(version) FROM chatxo.schema_migrations")
    settings = json.loads(sql("SELECT to_jsonb(i)::text FROM chatxo.instances i WHERE singleton"))
    roles = json.loads(sql("SELECT COALESCE(jsonb_object_agg(id::text,permissions),'{}'::jsonb)::text FROM chatxo.roles"))
    before, _ = read(config["local_origin"], "/api/v1/instance")
    check(before["instance_id"] == live["HAUNT_INSTANCE_ID"], "Server identity mismatch")
    source = stage / "publish" / ("haunt-server-linux-" + config["arch"])
    expected = digest(source)
    source.chmod(0o755)
    check(run(str(source), "-version") == plan["version"], "Server binary version mismatch")
    previous = digest(binary)
    backup = stage / "rollback"
    backup.mkdir(mode=0o700, exist_ok=True)
    if not (backup / "before.json").exists():
        if any(backup.iterdir()):
            backup.rename(stage / ("rollback-incomplete-" + str(time.time_ns())))
            backup.mkdir(mode=0o700)
        run("systemctl", "stop", service)
        try:
            shutil.copy2(binary, backup / "haunt")
            with (backup / "database.dump").open("xb") as stream:
                result = subprocess.run([*db, "pg_dump", "-Fc", "--no-owner", "--no-acl"], env=env, stdout=stream, stderr=subprocess.PIPE)
                check(result.returncode == 0, "Server database backup failed")
            with (backup / "database.dump").open("rb") as stream:
                check("schema_migrations" in run(*db, "pg_restore", "--list", env=env, stdin=stream), "Server database backup is unreadable")
            run("tar", "--acls", "--xattrs", "-cpf", str(backup / "data.tar"), "--exclude=" + data.name + "/client-updates", "-C", str(data.parent), data.name)
            paths = [Path(p) for p in config["preserved_files"]]
            paths += [p for folder in ["server-extensions", "audio-plugins"] for p in (data / folder).rglob("*") if p.is_file()]
            paths += [p for p in data.glob("*.json") if p.is_file()]
            preserved = {str(path): digest(path) for path in paths}
            for index, path in enumerate(config["preserved_files"]):
                shutil.copy2(path, backup / ("config-" + str(index)))
            state = {"previous_sha256": previous, "schema": schema, "settings": settings, "roles": roles, "files": preserved, "instance": before}
            (backup / "before.json").write_text(json.dumps(state))
            (backup / "SHA256SUMS").write_text("".join(digest(p) + "  " + p.name + "\n" for p in backup.iterdir() if p.is_file() and p.name != "SHA256SUMS"))
        except Exception:
            run("systemctl", "start", service)
            raise
    state = json.loads((backup / "before.json").read_text())
    try:
        if digest(binary) != expected:
            run("systemctl", "stop", service)
            atomic_file(source, binary)
        run("systemctl", "start", service)
        def verify():
            check(read(config["local_origin"], "/readyz")[0]["status"] == "ok", "Server is not ready")
            info, headers = read(config["local_origin"], "/api/v1/instance", {"Origin": config["web_origin"]})
            check(info["instance_id"] == state["instance"]["instance_id"], "Server identity changed")
            check(headers.get("Access-Control-Allow-Origin") == config["web_origin"], "Hosted client CORS failed")
            return info
        ready(verify)
        current = json.loads(sql("SELECT to_jsonb(i)::text FROM chatxo.instances i WHERE singleton"))
        check(all(current.get(key) == value for key, value in state["settings"].items()), "Server settings changed")
        current_roles = json.loads(sql("SELECT COALESCE(jsonb_object_agg(id::text,permissions),'{}'::jsonb)::text FROM chatxo.roles"))
        check(all(current_roles.get(key) == value for key, value in state["roles"].items()), "Server role permissions changed")
        check(all(digest(p) == value for p, value in state["files"].items()), "Server configuration or extension files changed")
        pid = prop("MainPID")
        check(digest("/proc/" + pid + "/exe") == expected and prop("NRestarts") == "0", "Server executable or restart verification failed")
        app = stage / "publish" / ("haunt-app-linux-" + config["arch"] + ".tar.gz")
        with tarfile.open(app) as archive:
            marker = json.load(archive.extractfile("web/haunt-build.json"))
        check(read(config["local_origin"], "/haunt-build.json")[0] == marker, "Embedded web build mismatch")
        return {"version": plan["version"], "sha256": expected, "instance_id": before["instance_id"], "rollback": str(backup), "preserved_files": len(state["files"]), "public_verification": "pending"}
    except Exception:
        if sql("SELECT max(version) FROM chatxo.schema_migrations") == state["schema"]:
            run("systemctl", "stop", service)
            atomic_file(backup / "haunt", binary)
            run("systemctl", "start", service)
        else:
            print(json.dumps({"rollback": "database schema advanced; retained database and rollback snapshot", "backup": str(backup)}), flush=True)
        raise


def sync_snapshot(container):
    code = Path(__file__).with_name("sync-snapshot.py").read_bytes()
    return json.loads(run("docker", "exec", "-i", container, "python3", "-", input=code))


def sync(stage, config, plan):
    directory = Path(config["compose_directory"])
    env_file = directory / ".env"
    compose_file = directory / "compose.yml"
    container = config["container"]
    compose = ["docker", "compose", "-p", config["project"], "-f", str(compose_file), "--env-file", str(env_file)]
    inspect = lambda: json.loads(run("docker", "inspect", container))[0]
    old = inspect()
    image = "ghcr.io/example-git/haunt-sync:" + plan["version"]
    run("docker", "pull", image)
    new_image = json.loads(run("docker", "image", "inspect", image))[0]
    labels = new_image["Config"]["Labels"]
    check(labels["org.opencontainers.image.version"] == plan["version"] and labels["org.opencontainers.image.revision"] == plan["components"]["sync"] and labels["vg.xo.haunt.hub-revision"] == plan["revision"], "Sync image source mismatch")
    backup = stage / "rollback"
    backup.mkdir(mode=0o700, exist_ok=True)
    before_file = backup / "before.json"
    if not before_file.exists():
        before = sync_snapshot(container)
        shutil.copy2(env_file, backup / ".env")
        shutil.copy2(compose_file, backup / "compose.yml")
        before["image"] = old["Image"]
        before["mounts"] = {m["Destination"]: [m["Type"], m.get("Name"), m["Source"]] for m in old["Mounts"]}
        before["environment"] = hashlib.sha256(json.dumps(sorted(v for v in old["Config"]["Env"] if v.startswith("HAUNT_"))).encode()).hexdigest()
        volume = next(m for m in old["Mounts"] if m["Destination"] == "/data")
        check(volume["Type"] == "volume", "Sync data must use a named volume")
        dump = b"import os,subprocess,sys;from pathlib import Path;e=dict(os.environ,PGPASSWORD=Path('/data/database-password').read_text().strip());p=subprocess.run(['pg_dump','-h','127.0.0.1','-U','haunt_sync','-d','haunt_sync','-Fc'],env=e,stdout=sys.stdout.buffer,stderr=subprocess.PIPE);sys.exit(p.returncode)"
        with (backup / "database.dump").open("xb") as stream:
            result = subprocess.run(["docker", "exec", "-i", container, "python3", "-"], input=dump, stdout=stream, stderr=subprocess.PIPE)
            check(result.returncode == 0, "Sync database backup failed")
        with (backup / "database.dump").open("rb") as stream:
            check("vaults" in run("docker", "exec", "-i", container, "pg_restore", "-l", stdin=stream), "Sync backup verification failed")
        run(*compose, "stop", "nexus")
        try:
            code = "import tarfile;t=tarfile.open('/backup/data.tar.gz','w:gz');t.add('/source',arcname='data');t.close()"
            run("docker", "run", "--rm", "--user", "0", "--entrypoint", "python3", "--mount", "type=volume,source=" + volume["Name"] + ",target=/source,readonly", "--mount", "type=bind,source=" + str(backup) + ",target=/backup", old["Image"], "-c", code)
            before_file.write_text(json.dumps(before))
        except Exception:
            run(*compose, "up", "-d", "--no-build", "nexus")
            raise
    before = json.loads(before_file.read_text())
    old_env = (backup / ".env").read_text()
    setting = "HAUNT_SYNC_IMAGE=" + image
    text = re.sub(r"^HAUNT_SYNC_IMAGE=.*$", setting, old_env, flags=re.M) if re.search(r"^HAUNT_SYNC_IMAGE=", old_env, re.M) else old_env.rstrip("\n") + "\n" + setting + "\n"
    staged_env = stage / "next.env"
    staged_env.write_text(text)
    atomic_file(staged_env, env_file, 0o600)
    try:
        run(*compose, "up", "-d", "--no-build", "--pull", "never", "nexus")
        def verify():
            value = sync_snapshot(container)
            check(value["healthz"]["status"] == "ready" and value["version"] == plan["version"], "Sync is not ready")
            return value
        after = ready(verify)
        for key in ["configuration", "accounts", "vaults", "saved_password_sha256"]:
            check(before[key] == after[key], "Sync preservation failed: " + key)
        current = inspect()
        mounts = {m["Destination"]: [m["Type"], m.get("Name"), m["Source"]] for m in current["Mounts"]}
        check(mounts == before["mounts"] and current["RestartCount"] == 0 and current["Image"] == new_image["Id"], "Sync mounts, image or restarts changed")
        environment = hashlib.sha256(json.dumps(sorted(v for v in current["Config"]["Env"] if v.startswith("HAUNT_"))).encode()).hexdigest()
        check(environment == before["environment"], "Sync runtime configuration changed")
        run("python3", str(stage / "import-sync-updates.py"), str(stage / "publish"), "--destination", config["updates_directory"], "--publisher-config", str(stage / "publisher.json"))
        return {"version": plan["version"], "image": new_image["Id"], "rollback": str(backup), "accounts": after["accounts"]["rows"], "vaults": after["vaults"]["rows"], "public_verification": "pending"}
    except Exception:
        atomic_file(backup / ".env", env_file, 0o600)
        run(*compose, "up", "-d", "--no-build", "--pull", "never", "nexus")
        raise


def main():
    os.umask(0o077)
    stage = Path(sys.argv[1]).resolve()
    plan = json.loads((stage / "plan.json").read_text())
    check(plan["channel"] == "stable" and re.fullmatch(r"\d+\.\d+\.\d+", plan["version"]), "Development releases cannot deploy")
    for line in (stage / "publish/SHA256SUMS").read_text().splitlines():
        expected, name = line.split("  ", 1)
        check(Path(name).name == name and digest(stage / "publish" / name) == expected, "Release staging hash mismatch")
    config = json.loads((stage / "deployment.json").read_text())
    completed = stage / "result.json"
    if completed.exists():
        result = json.loads(completed.read_text())
        check(result["version"] == plan["version"], "Deployment retry version mismatch")
        if config["kind"] == "server":
            pid = run("systemctl", "show", config["service"], "--property=MainPID", "--value")
            check(digest("/proc/" + pid + "/exe") == result["sha256"], "Completed server deployment no longer matches")
            check(read(config["local_origin"], "/readyz")[0]["status"] == "ok", "Completed server deployment is not ready")
        else:
            current = json.loads(run("docker", "inspect", config["container"]))[0]
            check(current["Image"] == result["image"] and sync_snapshot(config["container"])["healthz"]["status"] == "ready", "Completed sync deployment no longer matches")
        print(json.dumps(result))
        return
    result = server(stage, config, plan) if config["kind"] == "server" else sync(stage, config, plan)
    result["completed_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    (stage / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
