#!/usr/bin/env python3
import argparse
import json
import os
from pathlib import Path
import runpy
import subprocess
import tempfile
import urllib.request

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--connections", action="store_true")
    args = parser.parse_args()
    names = ["HAUNT_UPDATE_PRIVATE_KEY", "CLOUDFLARE_API_TOKEN", "CLOUDFLARE_ACCOUNT_ID", "HAUNT_DEPLOY_SSH_KEY", "HAUNT_DEPLOY_KNOWN_HOSTS", "HAUNT_SERVER_DEPLOYMENT", "HAUNT_SYNC_DEPLOYMENT"]
    missing = [name for name in names if not os.environ.get(name, "").strip()]
    if missing:
        raise ValueError("Release setup is incomplete: " + ", ".join(missing))
    transport = runpy.run_path(str(ROOT / "scripts/deploy-release.py"))
    validate = transport["validate_config"]
    for kind in ["server", "sync"]:
        config = validate(json.loads(os.environ["HAUNT_" + kind.upper() + "_DEPLOYMENT"]))
        if config["kind"] != kind:
            raise ValueError("Deployment configuration kind mismatch")
    code = """
    const fs=require('node:fs'), crypto=require('node:crypto');
    const expected=JSON.parse(fs.readFileSync('client/static/updates.json')).publicKey.trim();
    const key=crypto.createPrivateKey(process.env.HAUNT_UPDATE_PRIVATE_KEY);
    if(key.asymmetricKeyType!=='ed25519'||crypto.createPublicKey(key).export({type:'spki',format:'pem'}).toString().trim()!==expected)
      throw Error('Release key does not match the client trust key');
    """
    subprocess.run(["node", "-e", code], cwd=ROOT, check=True)
    print("Release signing, hosted web and deployment configuration are present")
    if args.connections:
        account = os.environ["CLOUDFLARE_ACCOUNT_ID"].strip()
        if not account.isalnum():
            raise ValueError("Invalid hosted web account identifier")
        request = urllib.request.Request("https://api.cloudflare.com/client/v4/accounts/" + account + "/workers/scripts/haunt-web/deployments", headers={"Authorization": "Bearer " + os.environ["CLOUDFLARE_API_TOKEN"].strip(), "User-Agent": "HauntReleaseVerifier/1"})
        with urllib.request.urlopen(request, timeout=30) as response:
            if not json.load(response).get("success"):
                raise ValueError("Hosted web deployment access failed")
        print("Hosted web deployment authentication passed")
        with tempfile.TemporaryDirectory(prefix="haunt-setup-") as temporary:
            temporary = Path(temporary)
            key, hosts = temporary / "key", temporary / "known_hosts"
            key.write_text(os.environ["HAUNT_DEPLOY_SSH_KEY"].strip() + "\n")
            key.chmod(0o600)
            hosts.write_text(os.environ["HAUNT_DEPLOY_KNOWN_HOSTS"].strip() + "\n")
            for kind in ["server", "sync"]:
                config = validate(json.loads(os.environ["HAUNT_" + kind.upper() + "_DEPLOYMENT"]))
                diagnostic = """
import json, platform, shutil, subprocess, sys, urllib.request
from pathlib import Path
c = CONFIG
assert sys.version_info >= (3, 11), 'Python 3.11 or later is required'
assert shutil.which('docker'), 'Docker is required'
assert Path('/var/backups').is_dir(), 'Backup directory is unavailable'
if c['kind'] == 'server':
    assert subprocess.check_output(['systemctl', 'is-active', c['service']], text=True).strip() == 'active'
    assert Path(c['binary']).is_file() and Path(c['data']).is_dir()
    assert all(Path(p).is_file() for p in c['preserved_files'])
    container = c['database_container']
    origin, route, expected = c['local_origin'], '/readyz', 'ok'
else:
    assert Path(c['compose_directory'], '.env').is_file() and Path(c['compose_directory'], 'compose.yml').is_file()
    subprocess.run(['docker', 'compose', 'version'], check=True, stdout=subprocess.DEVNULL)
    container = c['container']
    origin, route, expected = c['public_origins'][0], '/healthz', 'ready'
assert json.loads(subprocess.check_output(['docker', 'inspect', container], text=True))[0]['State']['Running']
with urllib.request.urlopen(urllib.request.Request(origin + route, headers={'User-Agent': 'HauntReleaseVerifier/1'}), timeout=20) as response:
    assert json.load(response)['status'] == expected
print(json.dumps({'kind': c['kind'], 'connection': 'passed', 'architecture': platform.machine()}))
""".replace("CONFIG", repr(config))
                result = subprocess.run([*transport["ssh_command"](config, key, hosts), "sudo -n python3 -"], input=diagnostic, text=True, capture_output=True, timeout=90)
                if result.returncode:
                    raise RuntimeError(kind + " deployment connection failed: " + result.stderr.strip())
                print(result.stdout.strip())


if __name__ == "__main__":
    main()
