#!/usr/bin/env python3
"""Verify and atomically import a signed desktop release into a public sync feed."""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("release_directory", type=Path)
    parser.add_argument("--destination", type=Path, default=Path(__file__).resolve().parents[1]/".local/sync-updates")
    parser.add_argument("--publisher-config", type=Path, default=Path(__file__).resolve().parents[1]/"client/static/updates.json")
    args = parser.parse_args()
    data = (args.release_directory/"haunt-updates.json").read_bytes()
    if len(data) > 128*1024: raise ValueError("Manifest exceeds size limit")
    envelope = json.loads(data)
    if envelope["schema"] != 1: raise ValueError("Unsupported manifest schema")
    payload = base64.b64decode(envelope["payload"], validate=True)
    signature = base64.b64decode(envelope["signature"], validate=True)
    config = json.loads(args.publisher_config.read_text())
    with tempfile.TemporaryDirectory(prefix="haunt-publisher-check-") as check:
        check = Path(check)
        (check/"key.pem").write_text(config["publicKey"])
        (check/"payload").write_bytes(payload)
        (check/"signature").write_bytes(signature)
        result = subprocess.run(["openssl", "pkeyutl", "-verify", "-pubin", "-inkey", str(check/"key.pem"), "-rawin", "-in", str(check/"payload"), "-sigfile", str(check/"signature")], capture_output=True)
        if result.returncode: raise ValueError("Publisher signature verification failed")
    release = json.loads(payload)
    version = release["version"]
    if release.get("schema") != 1 or release["repository"] != config["repository"] or not re.fullmatch(r"(0|[1-9][0-9]{0,5})\.(0|[1-9][0-9]{0,5})\.(0|[1-9][0-9]{0,5})", version): raise ValueError("Invalid signed release metadata")
    targets = release["targets"]
    if set(targets) != {"win32-x64", "linux-x64", "linux-arm64", "darwin-arm64"}: raise ValueError("Release must include all supported desktop targets")
    args.destination.mkdir(parents=True, exist_ok=True)
    target = args.destination/("client-v"+version)
    with tempfile.TemporaryDirectory(prefix=".import-", dir=args.destination) as stage:
        stage = Path(stage)
        stage.chmod(0o755)
        for entry in targets.values():
            for kind in ["asar", "installer"] + (["rpm"] if "rpm" in entry else []):
                asset = entry[kind]
                name, size, digest = asset["file"], asset["size"], asset["sha256"]
                if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,160}", name) or not re.fullmatch(r"[a-f0-9]{64}", digest) or not isinstance(size, int) or not 0 < size <= 1<<30: raise ValueError("Invalid signed artifact")
                source = args.release_directory/name
                if source.is_symlink() or not source.is_file() or source.stat().st_size != size: raise ValueError("Missing or mismatched release file: "+name)
                with source.open("rb") as stream:
                    if hashlib.file_digest(stream, "sha256").hexdigest() != digest: raise ValueError("Release hash mismatch: "+name)
                shutil.copyfile(source, stage/name)
                (stage/name).chmod(0o644)
                with (stage/name).open("rb") as stream:
                    if hashlib.file_digest(stream, "sha256").hexdigest() != digest: raise ValueError("Imported hash mismatch: "+name)
                    os.fsync(stream.fileno())
        (stage/"haunt-updates.json").write_bytes(data)
        (stage/"haunt-updates.json").chmod(0o644)
        if target.exists():
            if (target/"haunt-updates.json").read_bytes() != data: raise ValueError("Refusing to replace an immutable release")
            for file in stage.iterdir():
                with file.open("rb") as expected, (target/file.name).open("rb") as existing:
                    if hashlib.file_digest(expected,"sha256").digest() != hashlib.file_digest(existing,"sha256").digest(): raise ValueError("Existing release differs: "+file.name)
        else:
            # Keep TemporaryDirectory's original directory for its cleanup.
            os.rename(stage, target)
            stage.mkdir()
    # Publish the new pointer only after the entire verified release is visible.
    with tempfile.NamedTemporaryFile(prefix=".manifest-", dir=args.destination, delete=False) as pointer:
        pointer.write(data); pointer.flush(); os.fsync(pointer.fileno()); os.fchmod(pointer.fileno(), 0o644)
    os.replace(pointer.name, args.destination/"haunt-updates.json")
    print("Verified and imported desktop release", version, "into", args.destination)

if __name__ == "__main__": main()
