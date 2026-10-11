# SPDX-License-Identifier: GPL-3.0-or-later
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts'))
import verify_candidate
from candidate_snapshot import git, materialize


class CoordinatorInterruptionTests(unittest.TestCase):
    def test_interrupted_gate_records_sigint_and_never_dispatches_canonical(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / 'source'
            materialize({'ordinary.txt': ('100644', b'base\n')}, root)
            head, index = git(root, 'rev-parse', 'HEAD'), (root / '.git/index').read_bytes()
            original = verify_candidate.subprocess.run
            calls = []

            def gate(command, *args, **kwargs):
                if command[0] == 'git':
                    return original(command, *args, **kwargs)
                calls.append(command)
                if command[-1] == 'scripts/release-check':
                    raise KeyboardInterrupt

            with (mock.patch.object(verify_candidate, 'ROOT', root),
                  mock.patch.object(sys, 'argv', ['verify', '--oracle-source', str(root)]),
                  mock.patch.dict(os.environ, {'XDG_STATE_HOME': str(Path(temporary) / 'state')}),
                  mock.patch.object(verify_candidate.subprocess, 'run', side_effect=gate),
                  mock.patch.object(verify_candidate.shutil, 'which', return_value='/reviewed/nix')):
                with self.assertRaises(KeyboardInterrupt):
                    verify_candidate.main()
            self.assertEqual(len(calls), 5)
            self.assertFalse(any('canonical' in command for command in calls))
            summary = json.loads(next((Path(temporary) / 'state').rglob('summary.json')).read_bytes())
            self.assertEqual(summary['status'], 'cancelled')
            self.assertEqual(summary['exit_code'], 130)
            self.assertIsNone(summary['canonical_summary_sha256'])
            self.assertEqual(git(root, 'rev-parse', 'HEAD'), head)
            self.assertEqual((root / '.git/index').read_bytes(), index)


if __name__ == '__main__':
    unittest.main()
