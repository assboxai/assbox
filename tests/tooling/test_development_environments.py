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

    def test_targeted_install_entrypoint_realizes_cases_before_aggregate(self):
        x86 = [
            'install-boot-case-apple-refind-512',
            'install-boot-case-bios-gpt-512',
            'install-boot-case-bios-mbr-512',
            'install-boot-case-uefi-4096',
            'install-boot-case-uefi-512',
            'install-boot-vm',
        ]
        arm = [
            'install-boot-case-uefi-4096',
            'install-boot-case-uefi-512',
            'install-boot-vm',
        ]
        self.assertEqual(development_check.vm_check_names('install-boot-vm', 'x86_64-linux', x86), x86)
        self.assertEqual(development_check.vm_check_names('install-boot-vm', 'aarch64-linux', arm), arm)
        self.assertEqual(
            development_check.vm_check_names('activation-recovery-vm', 'x86_64-linux', []),
            ['activation-recovery-vm'],
        )
        with self.assertRaisesRegex(ValueError, 'install-boot-case-uefi-4096'):
            development_check.vm_check_names('install-boot-vm', 'aarch64-linux', arm[1:])
