#!/usr/bin/env python3
import json
import os
from pathlib import Path
import subprocess
from release import load_plan, ROOT, stamp


def main():
    plan = load_plan(ROOT / "release/plan.json")
    component = os.environ["COMPONENT"]
    arch = os.environ["ARCH"]
    target = f"{component}-linux-{arch}"
    if target not in plan["targets"]:
        raise ValueError("Service target was not selected")
    output = ROOT / "release" / target
    output.mkdir(parents=True, exist_ok=True)
    origin = json.loads((ROOT / "client/web-deployment.json").read_text())["origin"]
    module = "github.com/example-git/haunt-" + component
    symbol = "internal/config.HostedClientOrigin" if component == "server" else "internal/service.HostedClientOrigin"
    command = ["go", "build", "-trimpath", f"-ldflags=-s -w -X main.version={plan['version']} -X {module}/{symbol}={origin}",
        "-o", str(output / ("haunt-" + component + "-linux-" + arch)), "./cmd/haunt" + ("-sync" if component == "sync" else "")]
    if component == "server":
        stamp(plan, ROOT / "server/client")
        command[2:2] = ["-tags", "webclient"]
        subprocess.run(["cp", "-a", str(ROOT / "client/dist"), str(ROOT / "server/client/dist")], check=True)
    environment = {**os.environ, "CGO_ENABLED": "0", "GOOS": "linux", "GOARCH": arch}
    subprocess.run(command, cwd=ROOT / component, env=environment, check=True)
    executable = output / ("haunt-" + component + "-linux-" + arch)
    version = subprocess.check_output([str(executable), "-version" if component == "server" else "--version"], text=True, stderr=subprocess.STDOUT).strip().split()[-1]
    if version != plan["version"]:
        raise ValueError("Standalone service version does not match the release plan")
    if component == "server" and plan["channel"] == "stable":
        subprocess.run(["python3", "scripts/package-container-app.py", plan["version"], str(output), "--arch", arch],
            cwd=ROOT / "server", env={**os.environ, "HAUNT_WEB_CLIENT_ORIGIN": origin}, check=True)


if __name__ == "__main__":
    main()
