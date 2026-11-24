#!/usr/bin/env python3
import base64
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tarfile
import time
import urllib.parse
import urllib.request
from release import ROOT, load_plan, write


def request(url, headers=None):
    return urllib.request.urlopen(urllib.request.Request(url, headers={"Cache-Control": "no-cache", "User-Agent": "HauntReleaseVerifier/1", **(headers or {})}), timeout=60)


def read(url, headers=None):
    with request(url, headers) as response:
        return json.load(response), response.headers


def check(value, message):
    if not value:
        raise ValueError(message)


def verify_archive(origin, archive, prefix, cloudflare=False):
    policies = []
    with tarfile.open(archive) as bundle:
        if cloudflare:
            control = next((item for item in bundle.getmembers() if item.isfile() and item.name == prefix + "_headers"), None)
            check(control is not None, "Cloudflare header rules are missing")
            for line in bundle.extractfile(control).read().decode().splitlines():
                if not line.strip() or line.lstrip().startswith("#"):
                    continue
                if not line[0].isspace():
                    policies.append((re.compile("^" + re.escape(line.strip()).replace(r"\*", ".*") + "$"), []))
                else:
                    check(bool(policies) and ":" in line, "Unsupported Cloudflare header rule")
                    name, value = line.strip().split(":", 1)
                    policies[-1][1].append((name.lower(), value.strip()))
            check(bool(policies), "Cloudflare header rules are empty")
        files = [(item.name[len(prefix):], hashlib.sha256(bundle.extractfile(item).read()).hexdigest())
            for item in bundle.getmembers() if item.isfile() and item.name.startswith(prefix)
            and not (cloudflare and item.name == prefix + "_headers")]
    check(bool(files), "Expected web assets are missing")
    def verify(item):
        name, expected = item
        path = "/" + name
        matched, headers = set(), {}
        for index, (pattern, entries) in enumerate(policies):
            if pattern.fullmatch(path):
                matched.add(index)
                for key, value in entries:
                    headers.setdefault(key, []).append(value)
        with request(origin + "/" + urllib.parse.quote(name, safe="/")) as response:
            check(hashlib.sha256(response.read()).hexdigest() == expected, "Deployed web asset mismatch: " + name)
            for key, values in headers.items():
                check(response.headers.get(key) == ", ".join(values), "Deployed web header mismatch: " + path + ": " + key)
        return matched
    with ThreadPoolExecutor(max_workers=4) as pool:
        matched = set().union(*pool.map(verify, files))
    if cloudflare:
        check("index.html" in dict(files), "Hosted web entry point is missing")
        matched.update(verify(("", dict(files)["index.html"])))
        check(matched == set(range(len(policies))), "Cloudflare header rules were not exercised")
    return len(files)


def verify_feed(base, plan, envelope, community=False):
    path = "/api/v1/client-updates" if community else "/client-updates"
    deadline = time.monotonic() + 360
    while True:
        try:
            current, _ = read(base + path + "/haunt-updates.json")
            check(current == envelope, "Public update feed does not match the release")
            break
        except Exception:
            if time.monotonic() >= deadline:
                raise
            time.sleep(3)
    payload = json.loads(base64.b64decode(envelope["payload"]))
    if community:
        installers, _ = read(base + path + "/installers")
        check(installers["manifest"] == envelope and set(installers["available"]) == set(payload["targets"]), "Public installer inventory mismatch")
    artifacts = [entry[kind] for entry in payload["targets"].values() for kind in ["asar", "installer", "rpm"] if kind in entry]
    check(len(artifacts) == 10, "Incomplete signed release")
    result = subprocess.run(["node", str(ROOT / "scripts/verify-client-downloads.mjs"), base, path, plan["version"]],
        input=json.dumps(envelope), text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    check(result.returncode == 0, "Public launcher download verification failed: " + result.stderr.strip())
    downloads = json.loads(result.stdout)
    check(len(downloads) == 10 and set(downloads) == {asset["file"] for asset in artifacts}, "Launcher download inventory mismatch")
    return downloads


def main():
    plan = load_plan(ROOT / "release/plan.json")
    check(plan["channel"] == "stable", "Development builds cannot verify production deployments")
    output = ROOT / "release/publish"
    server = json.loads(os.environ["HAUNT_SERVER_DEPLOYMENT"])
    sync = json.loads(os.environ["HAUNT_SYNC_DEPLOYMENT"])
    envelope = json.loads((output / "haunt-updates.json").read_text())
    server_record = json.loads((ROOT / "release/deployed/deployed-server/server-deployment.json").read_text())
    results = []
    for origin in server["public_origins"]:
        check(read(origin + "/readyz")[0]["status"] == "ok", "Public server is not ready")
        instance, headers = read(origin + "/api/v1/instance", {"Origin": server["web_origin"]})
        check(instance["instance_id"] == server_record["instance_id"], "Public server identity mismatch")
        check(headers.get("Access-Control-Allow-Origin") == server["web_origin"], "Public CORS verification failed")
        assets = verify_archive(origin, output / ("haunt-app-linux-" + server["arch"] + ".tar.gz"), "web/")
        downloads = verify_feed(origin, plan, envelope, community=True)
        results.append({"origin": origin, "assets": assets, "downloads": downloads})
    for origin in sync["public_origins"]:
        check(read(origin + "/healthz")[0]["status"] == "ready", "Public sync is not ready")
        check(read(origin + "/v1/config")[0]["issuer"] == origin, "Public sync issuer mismatch")
        results.append({"origin": origin, "downloads": verify_feed(origin, plan, envelope)})
    count = verify_archive(server["web_origin"], output / ("haunt-web-" + plan["version"] + ".tar.gz"), "./", cloudflare=True)
    results.append({"origin": server["web_origin"], "assets": count})
    result = {"version": plan["version"], "revision": plan["revision"], "passed": True, "origins": results}
    write(ROOT / "release/public-verification.json", result)
    for kind in ["server", "sync"]:
        file = ROOT / f"release/deployed/deployed-{kind}/{kind}-deployment.json"
        record = json.loads(file.read_text())
        record["public_verification"] = "passed"
        write(ROOT / f"release/{kind}-deployment.json", record)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
