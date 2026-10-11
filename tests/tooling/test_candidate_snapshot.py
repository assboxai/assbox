# SPDX-License-Identifier: GPL-3.0-or-later
"""Exercise raw source identities and independent Git snapshots with toy trees."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts'))
import candidate_snapshot as snap


class Snapshots(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'caller'
        self.root.mkdir()
        snap.git(self.root, 'init', '--quiet', '--template=')
        (self.root / 'file').write_bytes(b'original\n')
        snap.git(self.root, 'add', 'file')
        snap.git(self.root, '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid',
                 '-c', 'commit.gpgsign=false', 'commit', '-qm', 'fixture')

    def test_working_bytes_modes_deletion_and_new_inclusion_preserve_caller(self):
        (self.root / 'file').write_bytes(b'working\r\n')
        (self.root / 'file').chmod(0o755)
        (self.root / 'new').write_bytes(b'new')
        before = (self.root / '.git/index').read_bytes()
        with self.assertRaisesRegex(ValueError, 'include-new'):
            snap.capture(self.root)
        files, records = snap.capture(self.root, ['new'])
        self.assertEqual(files['file'], ('100755', b'working\r\n'))
        receipts = [snap.materialize(files, Path(self.temp.name) / name) for name in ('one', 'two')]
        self.assertEqual(receipts[0], receipts[1])
        self.assertEqual((self.root / '.git/index').read_bytes(), before)
        self.assertEqual(snap.git(Path(self.temp.name) / 'one', 'status', '--porcelain'), b'')
        (self.root / 'file').unlink()
        self.assertNotIn('file', snap.capture(self.root, ['new'])[0])

    def test_symlink_and_hidden_index_flags_refuse(self):
        (self.root / 'file').unlink()
        (self.root / 'file').symlink_to('/etc/passwd')
        with self.assertRaises(OSError):
            snap.capture(self.root)
        (self.root / 'file').unlink()
        (self.root / 'file').write_text('normal')
        snap.git(self.root, 'update-index', '--assume-unchanged', 'file')
        with self.assertRaisesRegex(ValueError, 'flags'):
            snap.capture(self.root)

    def test_hostile_git_environment_cannot_redirect_source(self):
        with patch.dict(os.environ, {'GIT_DIR': '/missing', 'GIT_WORK_TREE': '/etc',
                                    'GIT_CONFIG_COUNT': '1', 'GIT_CONFIG_KEY_0': 'core.autocrlf',
                                    'GIT_CONFIG_VALUE_0': 'true'}):
            self.assertEqual(snap.capture(self.root)[0]['file'][1], b'original\n')

    def test_golden_commit_vector_and_policy(self):
        root = Path(__file__).resolve().parents[2]
        vector = json.loads((root / 'tests/fixtures/candidate-snapshot-vector.json').read_bytes())
        import base64
        files = {f['path']: (f['mode'], base64.b64decode(f['content_base64'], validate=True)) for f in vector['files']}
        self.assertEqual(snap.materialize(files, Path(self.temp.name) / 'golden'), vector['expected_identity'])

    def test_prohibited_paths_and_secret_new_files(self):
        for path in ('../escape', '/absolute', 'a/.git/config', 'a\\b', 'a\nname'):
            with self.assertRaises(ValueError):
                snap.safe_path(path)
        for path in ('key.pem', 'target/output', '.chainman/state', 'disk.qcow2', '.env', '.env.production'):
            self.assertFalse(snap.admitted_new(path))

    def test_developer_authority_is_whole_core_and_changes_identity(self):
        for name in ('AGENTS.md', 'chainman.lock', 'nix/dev/flake.lock', 'development/policy.json'):
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'reviewed bytes\n')
        names = ['AGENTS.md', 'chainman.lock', 'nix/dev/flake.lock', 'development/policy.json']
        files, _ = snap.capture(self.root, names)
        first = snap.materialize(files, Path(self.temp.name) / 'whole')
        (self.root / 'chainman.lock').write_bytes(b'changed developer pin\n')
        changed, _ = snap.capture(self.root, names)
        second = snap.materialize(changed, Path(self.temp.name) / 'changed')
        self.assertTrue(set(names) <= set(files))
        for field in ('source_content_sha256', 'git_tree_oid', 'synthetic_commit_oid'):
            self.assertNotEqual(first[field], second[field])
