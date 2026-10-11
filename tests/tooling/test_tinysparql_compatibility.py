# SPDX-License-Identifier: GPL-3.0-or-later
"""Preserve the upstream query oracle while upgrading SQLite."""
import json
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[2]


class TinySparqlCompatibilityTests(unittest.TestCase):
    def test_compatibility_patch_changes_product_code_only(self):
        patch = (ROOT / 'nix/patches/tinysparql-sqlite-precision.patch').read_text()
        files = [line[4:] for line in patch.splitlines() if line.startswith('+++ ')]
        self.assertEqual(files, ['b/src/libtinysparql/core/tracker-db-interface-sqlite.c'])
        self.assertNotIn('tests/', patch)

    def test_real_package_keeps_full_checks_and_the_sqlite_security_release(self):
        expression = '''let
          f = builtins.getFlake (toString ./.);
          p = f.nixosConfigurations.x86_64-linux-apple-11-1-chatgpt.pkgs;
        in {
          version = p.tinysparql.version;
          check = p.tinysparql.doCheck;
          patches = map toString p.tinysparql.patches;
          sqliteVersion = p.sqlite.version;
          interactiveVersion = p.sqlite-interactive.version;
        }'''
        result = subprocess.run([
            'nix', 'eval', '--impure', '--json', '--no-update-lock-file',
            '--no-write-lock-file', '--expr', expression,
        ], cwd=ROOT, capture_output=True, text=True, timeout=180)
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(data['version'], '3.11.1')
        self.assertIs(data['check'], True)
        self.assertTrue(any(path.endswith('/nix/patches/tinysparql-sqlite-precision.patch')
                            for path in data['patches']))
        self.assertEqual(data['sqliteVersion'], '3.53.3')
        self.assertEqual(data['interactiveVersion'], '3.53.3')


if __name__ == '__main__':
    unittest.main()
