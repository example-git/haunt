#!/usr/bin/env python3
"""Check a coordinated checkout without building or running components."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
ROOT = Path(__file__).resolve().parents[1]
def git(path, *args):
    return subprocess.check_output(['git', '-C', str(ROOT / path), *args], text=True).strip()
def main():
    installer = ROOT / 'install.py'
    if not installer.is_file() or not os.access(installer, os.X_OK):
        raise SystemExit('Top-level installer is missing or is not executable')
    if not (ROOT / 'server/scripts/install.py').is_file():
        raise SystemExit('Pinned server does not contain the terminal installer')
    if not (ROOT / 'sync/go.mod').is_file():
        raise SystemExit('Initialize/update the pinned sync submodule')
    client = git('client', 'rev-parse', 'HEAD')
    embedded = git('server', 'ls-tree', 'HEAD', 'client').split()[2]
    if client != embedded:
        raise SystemExit('Top-level client differs from the server client pin')
    if git('server/client', 'rev-parse', 'HEAD') != client:
        raise SystemExit('Initialize/update the server/client submodule to its pinned revision')
    bundled = ROOT / 'server/internal/audioplugin/default/haunt-plugin.zip'
    plugin = ROOT / 'audio-plugins/rnnoise/dist/haunt-plugin.zip'
    checksum = hashlib.sha256(plugin.read_bytes()).hexdigest()
    if hashlib.sha256(bundled.read_bytes()).hexdigest() != checksum:
        raise SystemExit('Server default package differs from pinned RNNoise package')
    if (plugin.parent / 'SHA256SUMS').read_text().split()[0] != checksum:
        raise SystemExit('RNNoise package checksum mismatch')
    print(json.dumps({'server': git('server', 'rev-parse', 'HEAD'), 'client': client,
                      'sync': git('sync', 'rev-parse', 'HEAD'),
                      'rnnoise': git('audio-plugins/rnnoise', 'rev-parse', 'HEAD'),
                      'client_version': json.loads((ROOT / 'client/package.json').read_text())['version'],
                      'rnnoise_sha256': checksum}, indent=2))
if __name__ == '__main__': main()
