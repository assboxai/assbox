#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Read-only inspection of retained worker runtime artifacts; never runs GC."""
import importlib.util
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("worker", ROOT / "scripts/worker/worker.py")
w = importlib.util.module_from_spec(spec)
spec.loader.exec_module(w)


def immutable(path):
    resolved = path.resolve(strict=True)
    if not str(resolved).startswith("/nix/store/"):
        raise RuntimeError("expected a store-bound artifact/authority")
    return resolved


def main():
    nix_store = immutable(Path("/run/current-system/sw/bin/nix-store"))
    rows, artifacts = [], {}
    generations = sorted((p for p in Path("/nix/var/nix/profiles").iterdir()
                          if re.fullmatch(r"system-[0-9]+-link", p.name)),
                         key=lambda p: int(p.name.split("-")[1]))
    for link in generations:
        system = immutable(link)
        if (system / "assbox-worker-system").is_symlink() or (system / "assbox-worker-system").exists():
            raise RuntimeError("host generation retains a standalone worker-system link: " + link.name)
        artifact_link = system / "assbox-worker-image"
        receipt_file = system / "assbox-worker-policy.json"
        receipt = None
        if receipt_file.exists() or receipt_file.is_symlink():
            receipt_file = immutable(receipt_file)
            if receipt_file.stat().st_size > 16384:
                raise RuntimeError("oversize worker receipt")
            receipt = json.loads(receipt_file.read_text())
            if receipt.get("schema") != 1 or type(receipt.get("enabled")) is not bool:
                raise RuntimeError("invalid worker receipt")
        if not artifact_link.exists() and not artifact_link.is_symlink():
            if receipt and receipt["enabled"]:
                raise RuntimeError("required worker artifact missing")
            continue
        if not receipt or not receipt["enabled"]:
            raise RuntimeError("worker artifact without matching enabled receipt")
        artifact = immutable(artifact_link)
        manifest = w.artifact_manifest({"artifact": str(artifact), "buildId": receipt["buildId"]}, verify_hashes=True)
        refs = subprocess.run([str(nix_store), "--query", "--references", str(artifact)],
                              capture_output=True, text=True, check=True, timeout=30).stdout.splitlines()
        if refs:
            raise RuntimeError("artifact has external/self runtime references: " + repr(refs))
        size = sum(v["bytes"] for v in manifest["files"].values()) + (artifact / "manifest.json").stat().st_size
        artifacts[str(artifact)] = size
        rows.append({"generation": link.name, "artifact": str(artifact), "bytes": size,
                     "buildId": receipt["buildId"]})
    if not rows:
        raise RuntimeError("no retained enabled-worker generation found; no retention claim can be made")
    print(json.dumps({"generations": rows, "uniqueArtifacts": len(artifacts),
                      "uniqueFileBytes": sum(artifacts.values()), "garbageCollection": "not-run",
                      "scope": "runtime references and files; not peak build space or all administrator GC roots"}, indent=2))


if __name__ == "__main__":
    main()
