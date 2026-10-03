# SPDX-License-Identifier: GPL-3.0-or-later
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
import verify_candidate
from candidate_snapshot import git, materialize


class Coordinator(unittest.TestCase):
    def test_failed_production_gate_never_dispatches_canonical_vm(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'worktree'
            materialize({'ordinary.txt': ('100644', b'base\n')}, root)
            real_run = verify_candidate.subprocess.run
            observed = []
            def gate(command, *args, **kwargs):
                if command[0] == 'git': return real_run(command, *args, **kwargs)
                observed.append(command)
                if command[-1] == 'scripts/release-check':
                    raise verify_candidate.subprocess.CalledProcessError(17, command)
            with (mock.patch.object(verify_candidate, 'ROOT', root),
                  mock.patch.object(sys, 'argv', ['verify', '--oracle-source', str(root)]),
                  mock.patch.dict(os.environ, {'XDG_STATE_HOME': str(Path(directory) / 'state')}),
                  mock.patch.object(verify_candidate.subprocess, 'run', side_effect=gate),
                  mock.patch.object(verify_candidate.shutil, 'which', return_value='/reviewed/nix')):
                with self.assertRaises(verify_candidate.subprocess.CalledProcessError): verify_candidate.main()
            self.assertEqual(len(observed), 5)
            self.assertFalse(any('canonical' in command for command in observed))
            summary = json.loads(next((Path(directory) / 'state').rglob('summary.json')).read_bytes())
            self.assertEqual(summary['exit_code'], 17)
            self.assertEqual(summary['status'], 'failed')

    def test_full_gate_uses_same_snapshot_and_enters_scrubbed_repair_profile(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'worktree'
            materialize({'ordinary.txt': ('100644', b'base\n')}, root)
            real_run = verify_candidate.subprocess.run
            observed = []
            snapshot = []
            def gate(command, *args, **kwargs):
                if command[0] == 'git': return real_run(command, *args, **kwargs)
                observed.append(command)
                if command[-1] == 'scripts/release-check': snapshot.append(kwargs['cwd'])
                if 'canonical' in command:
                    self.assertIn('path:' + str(root / 'nix/dev') + '#repair', command)
                    self.assertNotIn('GH_TOKEN', kwargs['env'])
                    self.assertNotIn('GITHUB_OUTPUT', kwargs['env'])
                    self.assertEqual(command[command.index('--snapshot') + 1], str(snapshot[0]))
                    receipt = json.loads((snapshot[0].parent / 'candidate-snapshot.json').read_bytes())
                    output = Path(command[command.index('--summary-output') + 1])
                    output.write_text(json.dumps(dict(status='passed', vm_executed=True, candidate_snapshot=receipt)))
            with (mock.patch.object(verify_candidate, 'ROOT', root),
                  mock.patch.object(sys, 'argv', ['verify', '--oracle-source', str(root)]),
                  mock.patch.dict(os.environ, {'XDG_STATE_HOME': str(Path(directory) / 'state'), 'GH_TOKEN': 'never-forward', 'GITHUB_OUTPUT': '/runner/channel'}),
                  mock.patch.object(verify_candidate.subprocess, 'run', side_effect=gate),
                  mock.patch.object(verify_candidate.shutil, 'which', return_value='/reviewed/nix')):
                verify_candidate.main()
            self.assertEqual(len(observed), 6)
            summary = json.loads((snapshot[0].parent / 'summary.json').read_bytes())
            self.assertEqual([s['name'] for s in summary['stages']], ['configuration', 'static', 'rust', 'mutations', 'production', 'canonical'])
            self.assertIsNotNone(summary['canonical_summary_sha256'])

    def test_freezes_raw_candidate_before_gate_and_preserves_dirty_caller_index(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'worktree'
            materialize({'ordinary.txt': ('100644', b'base\n')}, root)
            (root / 'ordinary.txt').write_bytes(b'working change\r\n')
            head = git(root, 'rev-parse', 'HEAD'); index = (root / '.git/index').read_bytes()
            observed = []
            real_run = verify_candidate.subprocess.run
            def gate(command, *args, **kwargs):
                if command[0] == 'git':
                    return real_run(command, *args, **kwargs)
                cwd, env = kwargs['cwd'], kwargs['env']
                self.assertEqual(command[-1], 'scripts/release-check')
                self.assertNotIn('--candidate', command)
                self.assertEqual((cwd / 'ordinary.txt').read_bytes(), b'working change\r\n')
                self.assertFalse(git(cwd, 'status', '--porcelain'))
                self.assertNotIn('GH_TOKEN', env)
                observed.append(cwd)
            with (mock.patch.object(verify_candidate, 'ROOT', root), mock.patch.object(sys, 'argv', ['verify', '--production-only']),
                 mock.patch.dict(os.environ, {'XDG_STATE_HOME': str(Path(directory) / 'state'), 'GH_TOKEN': 'never-forward'}),
                 mock.patch.object(verify_candidate.subprocess, 'run', side_effect=gate), mock.patch.object(verify_candidate.shutil, 'which', return_value='/reviewed/nix')):
                verify_candidate.main()
            self.assertEqual(len(observed), 1)
            summary = json.loads((observed[0].parent / 'summary.json').read_bytes())
            self.assertEqual(summary['status'], 'passed')
            self.assertIsNone(summary['canonical_summary_sha256'])
            self.assertEqual(git(root, 'rev-parse', 'HEAD'), head)
            self.assertEqual((root / '.git/index').read_bytes(), index)
            self.assertEqual((root / 'ordinary.txt').read_bytes(), b'working change\r\n')
