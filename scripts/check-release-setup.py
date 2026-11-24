#!/usr/bin/env python3
import json
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def main():
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


if __name__ == "__main__":
    main()
