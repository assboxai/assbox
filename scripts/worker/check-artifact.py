#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Validate an immutable runtime artifact; no VM or provider session is opened."""
import argparse
import json
from pathlib import Path
from worker import artifact_manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifact", type=Path)
    args = parser.parse_args()
    root = args.artifact.resolve(strict=True)
    manifest = root / "manifest.json"
    if manifest.is_symlink() or manifest.stat().st_size > 16384:
        parser.error("invalid manifest")
    identity = json.loads(manifest.read_text())["buildId"]
    artifact_manifest({"artifact": str(root), "buildId": identity}, verify_hashes=True)
    if {p.name for p in root.iterdir()} != {"manifest.json", "system.qcow2", "kernel", "initrd", "cmdline"}:
        parser.error("unexpected runtime artifact contents")
    print("Artifact hashes, regular-file layout and manifest passed.")


if __name__ == "__main__":
    main()
