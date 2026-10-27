#!/usr/bin/env python3
import json
import os
from pathlib import Path
import runpy
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def main():
    names = ["HAUNT_UPDATE_PRIVATE_KEY", "CLOUDFLARE_API_TOKEN", "CLOUDFLARE_ACCOUNT_ID", "HAUNT_DEPLOY_SSH_KEY", "HAUNT_DEPLOY_KNOWN_HOSTS", "HAUNT_SERVER_DEPLOYMENT", "HAUNT_SYNC_DEPLOYMENT"]
    missing = [name for name in names if not os.environ.get(name, "").strip()]
    if missing:
        raise ValueError("Release setup is incomplete: " + ", ".join(missing))
    validate = runpy.run_path(str(ROOT / "scripts/deploy-release.py"))["validate_config"]
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


if __name__ == "__main__":
    main()
