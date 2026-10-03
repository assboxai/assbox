# SPDX-License-Identifier: GPL-3.0-or-later
"""Resource configuration is selected before a session and checked on every entry."""
import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
import repair_loop
import test_repair_loop
import verify_candidate


class ResourceGuardrails(unittest.TestCase):
    def test_default_and_explicit_creation_freeze_exact_resource_policy(self):
        with tempfile.TemporaryDirectory() as directory:
            source, path, session = test_repair_loop.Sessions().make(directory)
            self.assertEqual(session['resource_policy'], repair_loop.resource_policy(10, 100))
            selected = repair_loop.initialise(source, Path(directory) / 'selected', memory_gib=12, disk_gib=110)
            record = json.loads((selected / 'session.json').read_bytes())
            self.assertEqual(record['resource_policy'], repair_loop.resource_policy(12, 110))
            self.assertEqual(json.loads((selected / 'resource-policy.json').read_bytes()), record['resource_policy'])
            self.assertEqual((selected / 'resource-policy.json').stat().st_mode & 0o777, 0o400)
            repair_loop.check_oracle(selected, record)

    def test_changing_session_threshold_or_frozen_copy_cannot_claim_integrity(self):
        for change in ('session', 'file', 'symlink', 'missing'):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as directory:
                source, path, session = test_repair_loop.Sessions().make(directory)
                policy = path / 'resource-policy.json'
                if change == 'session':
                    session['resource_policy']['available_disk_bytes'] -= 1024**3
                elif change == 'file':
                    policy.chmod(0o600)
                    policy.write_bytes(b'{}\n')
                elif change == 'symlink':
                    policy.unlink()
                    policy.symlink_to(path / 'session.json')
                else:
                    policy.unlink()
                with self.assertRaises(repair_loop.Blocked):
                    repair_loop.candidate_files(path, session)

    def test_invalid_creation_limits_do_not_create_state_or_launch_backend(self):
        for value in (0, -1, True, 1.5, 2**23):
            with tempfile.TemporaryDirectory() as directory, self.subTest(value=value):
                destination = Path(directory) / 'never-created'
                with mock.patch.object(repair_loop, 'capture', side_effect=AssertionError('Source read')):
                    with self.assertRaises(ValueError):
                        repair_loop.initialise(Path(directory) / 'source', destination, disk_gib=value)
                self.assertFalse(destination.exists())

    def test_existing_session_commands_cannot_override_thresholds(self):
        for operation in ('preflight', 'once', 'build', 'status', 'finalize'):
            with self.subTest(operation=operation), mock.patch.object(sys, 'argv',
                    ['repair', operation, '--session', '/unused', '--minimum-disk-gib', '110']):
                with mock.patch.object(repair_loop, 'locked', side_effect=AssertionError('Session entered')), \
                     mock.patch.object(sys, 'stderr', io.StringIO()):
                    with self.assertRaises(SystemExit) as error:
                        repair_loop.main()
                self.assertEqual(error.exception.code, 2)

    def test_full_gate_rejects_resource_options_for_production_only_before_freezing(self):
        with mock.patch.object(sys, 'argv', ['verify', '--production-only', '--minimum-disk-gib', '110']), \
             mock.patch.object(verify_candidate, 'capture', side_effect=AssertionError('Source read')), \
             mock.patch.object(sys, 'stderr', io.StringIO()):
            with self.assertRaises(SystemExit) as error:
                verify_candidate.main()
        self.assertEqual(error.exception.code, 2)

    def test_unreported_inode_counts_are_distinct_from_real_exhaustion(self):
        with tempfile.TemporaryDirectory() as directory:
            source, path, session = test_repair_loop.Sessions().make(directory)
            for total, available, blocked in [(0, 0, False), (100, 0, True), (100, 10, False)]:
                filesystem = SimpleNamespace(f_bavail=1024**3, f_frsize=1024,
                                             f_files=total, f_favail=available)
                with self.subTest(total=total, available=available), \
                     mock.patch.object(repair_loop.os, 'statvfs', return_value=filesystem), \
                     mock.patch.object(repair_loop.os, 'access', return_value=True), \
                     mock.patch.object(repair_loop, 'memory_available', return_value=64 * 1024**3), \
                     mock.patch.object(repair_loop.shutil, 'which', return_value='/fixture/tool'), \
                     mock.patch.object(repair_loop.platform, 'system', return_value='Linux'), \
                     mock.patch.object(repair_loop.platform, 'machine', return_value='x86_64'):
                    result = repair_loop.capabilities(path, session)
                self.assertEqual(result['status'] == 'blocked', blocked)
                self.assertEqual(result['volumes']['state']['inode_capacity_reported'], total > 0)
                self.assertEqual(result['volumes']['state']['available_inodes'], available if total else None)
                self.assertFalse(result['vm_executed'])

    def test_different_executing_controller_cannot_reuse_an_existing_session(self):
        with tempfile.TemporaryDirectory() as directory:
            source, path, session = test_repair_loop.Sessions().make(directory)
            changed = Path(directory) / 'changed-controller.py'
            changed.write_text('# replacement controller\n')
            with mock.patch.object(repair_loop, '__file__', str(changed)), \
                 mock.patch.object(repair_loop, 'process', side_effect=AssertionError('Backend launched')):
                with self.assertRaises(repair_loop.Blocked):
                    repair_loop.once(path, session)
