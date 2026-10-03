# SPDX-License-Identifier: GPL-3.0-or-later
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
import development_check
import verify_prepare
import verify_candidate


class Environments(unittest.TestCase):
    def test_config_and_finite_preparation_dispatch(self):
        development_check.configuration()
        self.assertEqual([c[1] for c in verify_prepare.commands()[:3]], ['static', 'rust', 'mutations'])
        self.assertFalse(any('nix' == c[0] or 'repair_loop.py' in ' '.join(c) for c in verify_prepare.commands()))

    def test_dev_flake_is_self_contained_and_production_has_named_shells(self):
        dev = (ROOT / 'nix/dev/flake.nix').read_text()
        self.assertNotIn('../..', dev)
        self.assertNotIn('inputs.assbox', dev)
        root = (ROOT / 'flake.nix').read_text()
        self.assertNotIn('nix/dev', root)
        self.assertNotIn('chainman', root)
        self.assertIn('release-check', (ROOT / 'nix/release-environments.nix').read_text())
        lock = json.loads((ROOT / 'nix/dev/flake.lock').read_text())
        self.assertEqual(set(lock['nodes']), {'root', 'nixpkgs'})

    def test_production_adapter_uses_clean_git_flake_without_shortcuts(self):
        command = verify_candidate.production_command('/reviewed/nix')
        self.assertIn('.#release-check', command)
        self.assertEqual(command[-1], 'scripts/release-check')
        self.assertNotIn('--candidate', command)
        self.assertNotIn('--bootstrap', command)
