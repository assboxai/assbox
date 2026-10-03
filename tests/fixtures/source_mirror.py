# SPDX-License-Identifier: GPL-3.0-or-later
"""Package exact locked input trees for the isolated acceptance HTTPS mirror."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile


def nar_hash(path):
    return subprocess.check_output(
        ["nix", "--extra-experimental-features", "nix-command", "hash", "path", str(path)],
        text=True,
    ).strip()


def verify_archive(archive, expected_hash):
    # Match flake tarball unpacking: discard the single archive root directory.
    # Check the extracted tree, not the original source or compressed bytes.
    with tempfile.TemporaryDirectory(prefix="assbox-source-roundtrip-") as temporary:
        subprocess.run(
            ["tar", "-xzf", str(archive), "--strip-components=1", "-C", temporary],
            check=True,
        )
        actual_hash = nar_hash(temporary)
        if actual_hash != expected_hash:
            raise ValueError(
                f"source archive NAR mismatch: {archive}: expected {expected_hash}, got {actual_hash}"
            )


def pack_source(path, archive, expected_hash):
    subprocess.run(
        ["tar", "-czf", str(archive), "--transform=flags=rh;s,^,source/,", "-C", str(path), "."],
        check=True,
    )
    # Transform member names and hardlink references, preserving symlink text.
    verify_archive(archive, expected_hash)


def build_mirror(out, sources):
    routes = {}
    checked = set()
    for source in sources:
        path = Path(source["path"])
        filename = hashlib.sha256(str(path).encode()).hexdigest() + ".tar.gz"
        identity = (filename, source["narHash"])
        if identity not in checked:
            pack_source(path, out / filename, source["narHash"])
            checked.add(identity)
        routes["/repos/{owner}/{repo}/tarball/{rev}".format(**source)] = filename
        routes["/{owner}/{repo}/archive/{rev}.tar.gz".format(**source)] = filename
    (out / "routes.json").write_text(json.dumps(routes))


if __name__ == "__main__":
    build_mirror(Path(os.environ["out"]), json.loads(os.environ["sourceRecords"]))
