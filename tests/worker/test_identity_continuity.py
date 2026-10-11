# SPDX-License-Identifier: GPL-3.0-or-later
"""Refuse damaged persistent state and canonical identities before any effects."""
import os
from pathlib import Path
import shutil
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from test_worker import configuration, w


class StateContinuity(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.data = Path(self.tmp.name)
        self.c = configuration()
        self.c['dataDir'] = str(self.data)
        self.home = self.data / 'home.raw'
        with self.home.open('wb') as stream:
            stream.truncate(self.c['stateGiB'] * w.GIB)
        self.home.chmod(0o600)
        self.owner = os.geteuid()

    def test_exact_disk_mode_required_before_admission_and_existing_disk_reuse(self):
        for mode in (0o400, 0o200, 0o000, 0o700, 0o1600, 0o640):
            with self.subTest(mode=oct(mode)):
                self.home.chmod(mode)
                with self.assertRaises(w.Refusal):
                    w.disk_admission(self.c, {'rootVirtualBytes': 8*w.GIB}, owner=self.owner)
                with patch.object(w, 'run') as run:
                    with self.assertRaises(w.Refusal):
                        w.create_state_disk(self.home, self.c['stateGiB']*w.GIB, '/unused')
                    run.assert_not_called()
                self.assertEqual(self.home.stat().st_mode & 0o7777, mode)
        # Nix's unprivileged build sandbox refuses chmod(04600). Exercise that
        # exact metadata through the same admission paths with a synthetic stat
        # result, while the ordinary and sticky modes above use real files.
        fields = list(self.home.lstat())
        fields[0] = (fields[0] & ~0o7777) | 0o4600
        synthetic = os.stat_result(fields)
        with self.subTest(mode=oct(0o4600)), \
             patch.object(w, 'require_regular', return_value=synthetic):
            with self.assertRaises(w.Refusal):
                w.disk_admission(self.c, {'rootVirtualBytes': 8*w.GIB}, owner=self.owner)
            with patch.object(w, 'run') as run:
                with self.assertRaises(w.Refusal):
                    w.create_state_disk(self.home, self.c['stateGiB']*w.GIB, '/unused')
                run.assert_not_called()
            self.assertEqual(synthetic.st_mode & 0o7777, 0o4600)
        self.home.chmod(0o600)
        self.assertTrue(w.existing_state(self.c, self.owner))

    def test_lost_home_with_overlay_refuses_before_provisioning(self):
        self.home.unlink()
        overlay = self.data / 'root.qcow2'
        overlay.write_bytes(b'old root')
        overlay.chmod(0o600)
        owner = SimpleNamespace(pw_uid=self.owner, pw_gid=os.getegid())
        with patch.object(w, 'require_user'), patch.object(w.pwd, 'getpwnam', return_value=owner), \
             patch.object(w, 'transport_preflight') as keys, patch.object(w, 'ensure_data_dir') as directory:
            with self.assertRaisesRegex(w.Refusal, 'home is missing'):
                w.provision(self.c)
            keys.assert_not_called()
            directory.assert_not_called()
        self.assertFalse(self.home.exists())
        self.assertEqual(overlay.read_bytes(), b'old root')

    def test_missing_key_never_reaches_provisioning_effects(self):
        owner = SimpleNamespace(pw_uid=self.owner, pw_gid=os.getegid())
        for index in range(3):
            calls = [None] * index + [FileNotFoundError('missing canonical key')]
            with self.subTest(index=index), patch.object(w, 'require_user'), \
                 patch.object(w.pwd, 'getpwnam', return_value=owner), \
                 patch.object(w, 'check_private_dir'), \
                 patch.object(w, 'key_public', side_effect=calls) as read, \
                 patch.object(w, 'ensure_key') as create, patch.object(w, 'private_dir') as directory, \
                 patch.object(w, 'ensure_data_dir') as data:
                with self.assertRaises(FileNotFoundError):
                    w.provision(self.c)
                self.assertEqual(read.call_count, index+1)
                create.assert_not_called()
                directory.assert_not_called()
                data.assert_not_called()

    def test_candidate_admission_also_validates_transport_without_writes(self):
        # No metadata/keys are created even when sufficient space is available.
        uid = max(1, self.owner)
        with patch.object(w, 'require_user'), patch.object(w.pwd, 'getpwnam',
                   return_value=SimpleNamespace(pw_uid=uid)), \
             patch.object(w, 'artifact_manifest'), patch.object(w, 'disk_admission', return_value={}), \
             patch.object(w, 'existing_state', return_value=True), \
             patch.object(w, 'transport_preflight', side_effect=w.Refusal('missing key')) as preflight, \
             patch.object(w, 'atomic_write') as write:
            with self.assertRaises(w.Refusal):
                w.admit(self.c)
            preflight.assert_called_once_with(self.c, preserved=True)
            write.assert_not_called()


class CanonicalKeyValidation(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.key = self.root / 'key'
        self.key.write_text('opaque private key')
        self.key.chmod(0o600)

    def test_permissions_type_links_and_owner_are_checked_before_parsing(self):
        with patch.object(w, 'run') as run:
            for mode in (0o400, 0o700, 0o640):
                self.key.chmod(mode)
                with self.assertRaises(w.Refusal):
                    w.key_public(self.key, '/unused', owner=os.geteuid())
            fields = list(self.key.lstat())
            fields[0] = (fields[0] & ~0o7777) | 0o4600
            synthetic = os.stat_result(fields)
            with patch.object(w, 'require_regular', return_value=synthetic):
                with self.assertRaises(w.Refusal):
                    w.key_public(self.key, '/unused', owner=os.geteuid())
            self.assertEqual(synthetic.st_mode & 0o7777, 0o4600)
            self.key.chmod(0o600)
            with self.assertRaises(w.Refusal):
                w.key_public(self.key, '/unused', owner=os.geteuid()+1)
            link = self.root / 'link'
            link.symlink_to(self.key)
            with self.assertRaises(w.Refusal):
                w.key_public(link, '/unused', owner=os.geteuid())
            link.unlink()
            os.link(self.key, link)
            with self.assertRaises(w.Refusal):
                w.key_public(self.key, '/unused', owner=os.geteuid())
            run.assert_not_called()

    def test_invalid_parsed_key_refuses(self):
        with patch.object(w, 'run', return_value='not an ed25519 public key'):
            with self.assertRaises(w.Refusal):
                w.key_public(self.key, '/unused', owner=os.geteuid())

    def test_first_setup_validates_all_existing_keys_before_generating_any(self):
        c = configuration()
        c['controlDir'] = str(self.root / 'control')
        c['identityDir'] = str(self.root / 'identity')
        Path(c['controlDir']).mkdir()
        Path(c['identityDir']).mkdir()
        last = Path(c['identityDir']) / 'health_ed25519'
        last.write_text('malformed retained key')
        with patch.object(w.pwd, 'getpwnam', return_value=SimpleNamespace(pw_uid=1000, pw_gid=100)), \
             patch.object(w, 'check_private_dir'), patch.object(w, 'key_public', side_effect=w.Refusal('malformed')) as read:
            with self.assertRaises(w.Refusal):
                w.transport_preflight(c, preserved=False)
            read.assert_called_once_with(last, c['tools']['sshKeygen'], owner=0)
        self.assertEqual(list(Path(c['controlDir']).iterdir()), [])

    def test_clean_first_setup_allows_missing_keys_without_generating_them_in_preflight(self):
        c = configuration()
        c['controlDir'], c['identityDir'] = str(self.root/'control'), str(self.root/'identity')
        with patch.object(w.pwd, 'getpwnam', return_value=SimpleNamespace(pw_uid=1000, pw_gid=100)), \
             patch.object(w, 'key_public') as read:
            w.transport_preflight(c, preserved=False)
            read.assert_not_called()
        self.assertFalse(Path(c['controlDir']).exists())

    @unittest.skipUnless(shutil.which('ssh-keygen'), 'OpenSSH key parser unavailable')
    def test_real_key_parser_accepts_ed25519_and_refuses_corruption(self):
        self.key.unlink()
        w.run(['ssh-keygen', '-q', '-t', 'ed25519', '-N', '', '-f', str(self.key)])
        public = w.key_public(self.key, 'ssh-keygen', owner=os.geteuid())
        self.assertTrue(public.startswith('ssh-ed25519 '))
        self.key.write_text('corrupt key')
        with self.assertRaises(w.Refusal):
            w.key_public(self.key, 'ssh-keygen', owner=os.geteuid())
