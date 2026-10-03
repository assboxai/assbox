# SPDX-License-Identifier: GPL-3.0-or-later
"""Ordinary installation cases cannot wait on the driver's inherited terminal."""
import ast
import os
from pathlib import Path
import pty
import shlex
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


class InstalledFixtureStdin(unittest.TestCase):
    def test_ordinary_install_closes_inherited_tty(self):
        tree = ast.parse((ROOT / 'tests/fixtures/installed_cases.py').read_text())
        assignments = [node for node in tree.body if isinstance(node, ast.Assign)
                       and any(isinstance(target, ast.Name) and target.id == 'INSTALL'
                               for target in node.targets)]
        self.assertEqual(len(assignments), 1)
        with tempfile.TemporaryDirectory() as directory:
            probe = Path(directory) / 'stdin probe'
            probe.write_text('#!' + sys.executable + '\n'
                             'import os, sys\n'
                             'assert sys.argv[1:] == ["--ignored", "--exact", '
                             '"acceptance::install_apply", "--nocapture"]\n'
                             'print(int(os.isatty(0)))\n')
            probe.chmod(0o700)
            expression = ast.Expression(assignments[0].value)
            command = eval(compile(expression, 'installed_cases.py', 'eval'),
                           {'harness': str(probe), 'shlex': shlex})
            master, slave = pty.openpty()
            try:
                baseline = subprocess.run([sys.executable, '-c', 'import os; print(int(os.isatty(0)))'],
                                          stdin=slave, capture_output=True, text=True, timeout=10, check=True)
                self.assertEqual(baseline.stdout, '1\n')
                result = subprocess.run(['bash', '--noprofile', '--norc', '-c', command],
                                        stdin=slave, capture_output=True, text=True, timeout=10, check=True)
                self.assertEqual(result.stdout, '0\n')
            finally:
                os.close(master)
                os.close(slave)


if __name__ == '__main__':
    unittest.main()
