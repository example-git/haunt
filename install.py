#!/usr/bin/env python3
"""Fetch Haunt's pinned components and start the terminal installer."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parent


def main() -> int:
    if not (ROOT / ".git").exists():
        print("haunt installer: run this from a Haunt repository checkout", file=sys.stderr)
        return 1

    print("Preparing the pinned Haunt server, client, and sync components…", flush=True)
    try:
        subprocess.run(
            ["git", "submodule", "update", "--init", "--recursive", "server", "client", "sync"],
            cwd=ROOT,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError) as error:
        print(f"haunt installer: could not prepare pinned components: {error}", file=sys.stderr)
        return 1

    installer = ROOT / "server" / "scripts" / "install.py"
    if not installer.is_file():
        print("haunt installer: pinned server does not contain the terminal installer", file=sys.stderr)
        return 1
    os.execv(sys.executable, [sys.executable, str(installer), *sys.argv[1:]])
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
