#!/usr/bin/env python3
"""Verify a complete Nexus image using only disposable containers and volumes."""
import argparse
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import tempfile
import time
import urllib.request

D = ["docker", "--host=unix:///var/run/docker.sock"]
def run(args, **kwargs):
    return subprocess.run(args, check=True, capture_output=True, text=True, **kwargs)
def logs(name):
    result = run(D + ["logs", name])
    return result.stdout + result.stderr
def main():
    parser = argparse.ArgumentParser(); parser.add_argument("image"); parser.add_argument("--client", required=True); args = parser.parse_args()
    token = "synthetic-token-must-not-be-logged"
    version = run(D+["run","--rm",args.image,"--version"])
    assert "Haunt Sync" in version.stderr
    rejected = subprocess.run(D+["run","--rm",args.image,"unknown-argument"],capture_output=True,text=True)
    assert rejected.returncode != 0 and "Unsupported container arguments" in rejected.stderr
    for settings, error in [([], "Set HAUNT_SYNC_TUNNEL_TOKEN"), (["HAUNT_SYNC_QUICK_TUNNEL=invalid"], "must be true or false"), (["HAUNT_SYNC_QUICK_TUNNEL=true", "HAUNT_SYNC_TUNNEL_TOKEN="+token], "not both")]:
        command = D + ["run", "--rm", "--read-only", "--cap-drop", "ALL"]
        for value in settings: command += ["-e", value]
        result = subprocess.run(command + [args.image], capture_output=True, text=True)
        assert result.returncode != 0 and error in result.stderr and token not in result.stderr
    print("PASS: missing, invalid and conflicting tunnel modes refuse startup", flush=True)
    volumes, containers = [], []
    try:
        # The literal default entrypoint must convert a supplied environment
        # token into a private file. An invalid synthetic token must fail visibly.
        volume = "haunt-sync-bundle-"+secrets.token_hex(6); name = "haunt-sync-check-"+secrets.token_hex(6)
        run(D+["volume","create",volume]); volumes.append(volume); containers.append(name)
        run(D+["run","-d","--name",name,"--read-only","--cap-drop","ALL","--security-opt","no-new-privileges:true","--tmpfs","/tmp:size=32m,mode=1777","-v",volume+":/data","-e","HAUNT_SYNC_HOST=nexus.example.test","-e","HAUNT_SYNC_TUNNEL_TOKEN="+token,args.image])
        for _ in range(240):
            state=json.loads(run(D+["inspect",name]).stdout)[0]["State"]
            if not state["Running"]: break
            time.sleep(.25)
        else: raise RuntimeError("Invalid synthetic tunnel token did not fail")
        assert state["ExitCode"] != 0 and token not in logs(name)
        assert "not valid" in logs(name).lower() and "token" in logs(name).lower()
        check = "from pathlib import Path; p=Path('/data/run/cloudflared-token'); assert p.read_text().strip() == '"+token+"'; assert p.stat().st_mode & 0o777 == 0o600; print('PASS private startup token file')"
        print(run(D+["run","--rm","--entrypoint","python3","--read-only","-v",volume+":/data:ro",args.image,"-c",check]).stdout,flush=True)
        volume = "haunt-sync-bundle-"+secrets.token_hex(6); name = "haunt-sync-check-"+secrets.token_hex(6)
        run(D+["volume","create",volume]); volumes.append(volume); containers.append(name)
        run(D+["run","-d","--name",name,"--read-only","--cap-drop","ALL","--security-opt","no-new-privileges:true","--tmpfs","/tmp:size=32m,mode=1777","-v",volume+":/data","-e","HAUNT_SYNC_QUICK_TUNNEL=true",args.image])
        def ready(previous=""):
            deadline=time.monotonic()+120
            while time.monotonic()<deadline:
                current=logs(name)[len(previous):]
                match=re.search(r"Haunt Nexus temporary address: (https://[a-z0-9-]+\.trycloudflare\.com)",current)
                if match and "Haunt Nexus ready:" in current: break
                state=json.loads(run(D+["inspect",name]).stdout)[0]["State"]
                if not state["Running"]: raise RuntimeError("Quick bundle startup failed: "+current)
                time.sleep(.5)
            else: raise RuntimeError("Quick bundle did not initialize")
            issuer=match.group(1)
            for _ in range(100):
                try:
                    with urllib.request.urlopen(issuer+"/healthz",timeout=5) as response:
                        if response.status==200: return issuer
                except Exception: pass
                time.sleep(.25)
            raise RuntimeError("Full bundle is not reachable through public HTTPS")
        issuer=ready(); print("Disposable full-bundle URL:",issuer,flush=True)
        # A named-mode directory must survive both temporary launches intact.
        marker="from pathlib import Path; p=Path('/data/postgres'); p.mkdir(exist_ok=True); (p/'named-data-sentinel').write_text('preserve named data')"
        run(D+["exec",name,"python3","-c",marker])
        info=json.loads(run(D+["inspect",name]).stdout)[0]
        assert info["Config"]["User"]=="65532:65532" and not info["HostConfig"]["PortBindings"]
        client=Path(args.client).resolve()
        def encrypted_restore(issuer):
            env=os.environ.copy();env["HAUNT_SYNC_BUNDLE_ISSUER"]=issuer
            with tempfile.NamedTemporaryFile(prefix="nexus-bundle-",suffix=".test.ts",dir=client/"tests",delete=False) as generated:
                fixture=Path(generated.name)
            try:
                fixture.write_text((Path(__file__).resolve().parents[1]/"sync/tests/sync-bundle.test.ts").read_text())
                result=subprocess.run(["npm","exec","--","vitest","run",str(fixture.relative_to(client)),"--maxWorkers=1"],cwd=client,env=env,capture_output=True,text=True)
            finally:
                fixture.unlink()
            print(result.stdout);print(result.stderr)
            if result.returncode: raise RuntimeError("Single-container encrypted sync check failed")
        def database_accounts(expected):
            query="import os,subprocess; from pathlib import Path; directory=Path(Path('/data/run/database-directory').read_text().strip()); assert directory.parent==Path('/data') and directory.name.startswith('nexus-quick-'); e=dict(os.environ, PGPASSWORD=(directory/'database-password').read_text().strip()); p=subprocess.run(['psql','-h','127.0.0.1','-U','haunt_sync','-d','haunt_sync','-Atc',\"SELECT count(*) FROM haunt_sync.accounts\"],env=e,capture_output=True,text=True,check=True); assert int(p.stdout)=="+str(expected)+"; assert Path('/data/postgres/named-data-sentinel').read_text()=='preserve named data'; print('PASS private account count and named-data preservation')"
            print(run(D+["exec",name,"python3","-c",query]).stdout,flush=True)
        encrypted_restore(issuer)
        database_accounts(2)
        # Quick mode is a disposable service. A full restart must be usable with
        # a new address and empty snapshots, without touching named-mode data.
        run(D+["stop","-t","90",name]); previous=logs(name); run(D+["start",name])
        replacement=ready(previous)
        assert replacement != issuer
        database_accounts(0)
        encrypted_restore(replacement)
        database_accounts(2)
        print("PASS: complete encrypted sync, fresh Quick restart, and preserved named data",flush=True)
    finally:
        for name in containers:
            subprocess.run(D+["stop","-t","90",name],capture_output=True)
            subprocess.run(D+["rm","-v",name],capture_output=True)
        for volume in volumes:
            subprocess.run(D+["volume","rm",volume],capture_output=True)
if __name__ == "__main__": main()
