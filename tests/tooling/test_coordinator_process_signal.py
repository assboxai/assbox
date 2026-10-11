# SPDX-License-Identifier: GPL-3.0-or-later
"""Cancellation must retain its status across subprocess and task wrappers."""
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[2]

CHILD = r'''
import ast, json, os, pathlib, subprocess, sys, time
from unittest import mock
root, state, entry = map(pathlib.Path, sys.argv[1:])
sys.path.insert(0, str(root / 'scripts'))
import verify_candidate
from candidate_snapshot import materialize
source = state / 'source'
materialize({'ordinary.txt': ('100644', b'base\n')}, source)
original = subprocess.run
def gate(command, *args, **kwargs):
    if command[0] == 'git':
        return original(command, *args, **kwargs)
    if command[-1] == 'scripts/release-check':
        (state / 'ready').write_text('ready')
        return original([sys.executable, '-c', 'import time; time.sleep(60)'],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
tree = ast.parse(entry.read_text())
guards = [node for node in tree.body if isinstance(node, ast.If)
          and isinstance(node.test, ast.Compare)
          and isinstance(node.test.left, ast.Name)
          and node.test.left.id == '__name__']
assert len(guards) == 1
with (mock.patch.object(verify_candidate, 'ROOT', source),
      mock.patch.object(sys, 'argv', ['verify', '--oracle-source', str(source)]),
      mock.patch.dict(os.environ, {'XDG_STATE_HOME': str(state / 'evidence')}),
      mock.patch.object(subprocess, 'run', side_effect=gate),
      mock.patch.object(verify_candidate.shutil, 'which', return_value='/reviewed/nix')):
    exec(compile(ast.Module(body=guards, type_ignores=[]), str(entry), 'exec'),
         {'__name__': '__main__', 'main': verify_candidate.main})
'''


class CoordinatorProcessSignal(unittest.TestCase):
    def test_sigint_returns_normal_130_and_records_cancellation(self):
        import json
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory)
            entry = Path(os.environ.get('ASSBOX_TEST_COORDINATOR_ENTRY', ROOT / 'scripts/verify_candidate.py'))
            process = subprocess.Popen([sys.executable, '-c', CHILD, str(ROOT), str(state), str(entry)],
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
            try:
                deadline = time.monotonic() + 10
                while not (state / 'ready').exists() and process.poll() is None and time.monotonic() < deadline:
                    time.sleep(0.02)
                self.assertTrue((state / 'ready').exists(), 'coordinator did not reach its blocking gate')
                process.send_signal(signal.SIGINT)
                stdout, stderr = process.communicate(timeout=15)
                self.assertEqual(process.returncode, 130, (stdout + stderr).decode())
                summary = json.loads(next((state / 'evidence').rglob('summary.json')).read_bytes())
                self.assertEqual(summary['status'], 'cancelled')
                self.assertEqual(summary['exit_code'], 130)
                self.assertIsNone(summary['canonical_summary_sha256'])
            finally:
                # This group contains only the coordinator and its disposable
                # blocking helper, created above with a new session.
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                process.communicate(timeout=10)


if __name__ == '__main__':
    unittest.main()
