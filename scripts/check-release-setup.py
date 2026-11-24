#!/usr/bin/env python3
import argparse
import json
import os
from pathlib import Path
import subprocess
import urllib.request

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--connections", action="store_true")
    args = parser.parse_args()
    names = ["HAUNT_UPDATE_PRIVATE_KEY", "CLOUDFLARE_API_TOKEN", "CLOUDFLARE_ACCOUNT_ID"]
    missing = [name for name in names if not os.environ.get(name, "").strip()]
    if missing:
        raise ValueError("Release setup is incomplete: " + ", ".join(missing))
    code = """
    const fs=require('node:fs'), crypto=require('node:crypto');
    const expected=JSON.parse(fs.readFileSync('client/static/updates.json')).publicKey.trim();
    const key=crypto.createPrivateKey(process.env.HAUNT_UPDATE_PRIVATE_KEY);
    if(key.asymmetricKeyType!=='ed25519'||crypto.createPublicKey(key).export({type:'spki',format:'pem'}).toString().trim()!==expected)
      throw Error('Release key does not match the client trust key');
    """
    subprocess.run(["node", "-e", code], cwd=ROOT, check=True)
    print("Release signing and hosted web configuration are present")
    if args.connections:
        account = os.environ["CLOUDFLARE_ACCOUNT_ID"].strip()
        if not account.isalnum():
            raise ValueError("Invalid hosted web account identifier")
        request = urllib.request.Request("https://api.cloudflare.com/client/v4/accounts/" + account + "/workers/scripts/haunt-web/deployments", headers={"Authorization": "Bearer " + os.environ["CLOUDFLARE_API_TOKEN"].strip(), "User-Agent": "HauntReleaseVerifier/1"})
        with urllib.request.urlopen(request, timeout=30) as response:
            if not json.load(response).get("success"):
                raise ValueError("Hosted web deployment access failed")
        print("Hosted web deployment authentication passed")


if __name__ == "__main__":
    main()
