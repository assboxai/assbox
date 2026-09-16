# SPDX-License-Identifier: GPL-3.0-or-later
"""Real tar/Nix round trips on small trees, without evaluation, builds or network."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("source_mirror", ROOT / "tests/fixtures/source_mirror.py")
MIRROR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MIRROR)


class SourceMirrorTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="assbox-mirror-test-")
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.source = self.directory / "input"
        self.source.mkdir()
        (self.source / "lib").mkdir()
        (self.source / "lib/.version").write_text("disposable version\n")
        (self.source / ".version").symlink_to("lib/.version")
        (self.source / "lib/up").symlink_to("../.version")
        (self.source / "absolute").symlink_to("/disposable/absent/path")
        (self.source / "dangling").symlink_to("absent")
        (self.source / "empty").mkdir()
        executable = self.source / "executable"
        executable.write_text("#!/bin/sh\nexit 0\n")
        executable.chmod(0o755)
        os.link(executable, self.source / "hardlink")
        self.expected = MIRROR.nar_hash(self.source)
        self.archive = self.directory / "source.tar.gz"

    def test_archive_roundtrip_preserves_the_exact_nar(self):
        MIRROR.pack_source(self.source, self.archive, self.expected)
        extracted = self.directory / "extracted"
        extracted.mkdir()
        subprocess.run(["tar", "-xzf", str(self.archive), "-C", str(extracted)], check=True)
        tree = extracted / "source"
        self.assertEqual(MIRROR.nar_hash(tree), self.expected)
        for name in (".version", "lib/up", "absolute", "dangling"):
            self.assertEqual(os.readlink(tree / name), os.readlink(self.source / name))
        self.assertEqual((tree / ".version").read_text(), "disposable version\n")

    def test_old_symlink_transformation_is_rejected(self):
        subprocess.run(["tar", "-czf", str(self.archive), "--transform=s,^,source/,",
                        "-C", str(self.source), "."], check=True)
        with self.assertRaisesRegex(ValueError, "source archive NAR mismatch"):
            MIRROR.verify_archive(self.archive, self.expected)

    def test_mirror_rejects_wrong_lock_hash_before_publishing_routes(self):
        out = self.directory / "mirror"
        out.mkdir()
        record = dict(path=str(self.source), owner="fixture", repo="input", rev="a" * 40,
                      narHash="sha256-AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=")
        with self.assertRaisesRegex(ValueError, "source archive NAR mismatch"):
            MIRROR.build_mirror(out, [record])
        self.assertFalse((out / "routes.json").exists())
        record["narHash"] = self.expected
        MIRROR.build_mirror(out, [record, record])
        routes = json.loads((out / "routes.json").read_text())
        self.assertEqual(len(routes), 2)
        self.assertEqual(len(set(routes.values())), 1)
        self.assertTrue(all((out / archive).is_file() for archive in routes.values()))


if __name__ == "__main__":
    unittest.main()
