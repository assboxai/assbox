# SPDX-License-Identifier: GPL-3.0-or-later
"""Normalization preserves selected pins; the publication gate requires exactness."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
import release as publisher
import release_data as data
from test_release_data import core, lock


class ReleaseLockTests(unittest.TestCase):
    def test_normalization_accepts_only_equivalent_selected_inputs(self):
        selected = data.compose_lock(lock(), lock(), set())
        with patch.object(publisher, 'resolved_lock', return_value=lock()):
            self.assertEqual(publisher.normalized_lock(core(), selected), data.json_bytes(lock()))
        with patch.object(publisher, 'resolved_lock', return_value=lock('b')):
            with self.assertRaisesRegex(ValueError, 'changed a selected dependency'):
                publisher.normalized_lock(core(), selected)

    def test_gate_rejects_even_semantically_equivalent_unresolved_lock(self):
        with tempfile.TemporaryDirectory() as temp:
            tree = Path(temp)
            original = data.json_bytes(lock())
            (tree / 'flake.lock').write_bytes(original)
            with patch.object(publisher, 'resolved_lock', return_value=lock()):
                publisher.check_lock(tree)
            with patch.object(publisher, 'resolved_lock', return_value=data.compose_lock(lock(), lock(), set())):
                with self.assertRaisesRegex(ValueError, 'resolved graph differs'):
                    publisher.check_lock(tree)
            self.assertEqual((tree / 'flake.lock').read_bytes(), original)

    def test_metadata_resolution_disables_registries_and_lock_writes(self):
        with patch.object(publisher, 'run', return_value=data.json_bytes({'locks': lock()})) as run:
            self.assertEqual(publisher.resolved_lock(Path('/tmp/fixture')), lock())
            run.assert_called_once_with('nix', 'flake', 'metadata', '--json', '--no-use-registries',
                                        '--no-update-lock-file', '--no-write-lock-file', '/tmp/fixture')


if __name__ == '__main__': unittest.main()
