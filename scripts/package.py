# -*- coding: utf-8 -*-
"""Build a deploy tarball for the auxiliary plugin.

Usage:
    python scripts/package.py [--name bili_platform_aux] [--out DIR]

The archive contains a single top-level directory (the AstrBot plugin module
name). Only RUNTIME_FILES are included; the name carries the current git short
hash when available. Local credentials, data and developer files are excluded.
"""

from __future__ import annotations

import argparse
import pathlib
import re
import subprocess
import tarfile
import tempfile

RUNTIME_FILES = (
    "__init__.py", "main.py", "config_manager.py", "platform_client.py",
    "render.py", "admin_cli.py", "_conf_schema.json", "metadata.yaml",
    "requirements.txt", "README.md", "USAGE.md", "CHANGELOG.md",
    "LICENSE", "THIRD_PARTY_NOTICES.md", "docs/PERMISSIONS.md",
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", default="bili_platform_aux")
    parser.add_argument("--out", default="")
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", args.name):
        parser.error("--name must be a Python module name")

    root = pathlib.Path(__file__).resolve().parents[1]
    sha = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        cwd=root,
        capture_output=True,
        text=True,
    ).stdout.strip() or "nogn"
    out_dir = (
        pathlib.Path(args.out).expanduser()
        if args.out
        else pathlib.Path(tempfile.gettempdir())
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    archive = out_dir / f"{args.name}-{sha}.tar.gz"

    files = [(root / name, pathlib.Path(name)) for name in RUNTIME_FILES]
    for path, rel in files:
        if not path.is_file() or path.is_symlink():
            raise ValueError(f"Missing or unsafe runtime file: {rel}")

    with tarfile.open(archive, "w:gz") as tar:
        for path, rel in files:
            tar.add(path, arcname=f"{args.name}/" + "/".join(rel.parts))

    print(f"archive={archive}")
    print(f"sha={sha}")
    print(f"files={len(files)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
