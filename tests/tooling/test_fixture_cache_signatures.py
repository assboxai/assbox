# SPDX-License-Identifier: GPL-3.0-or-later
"""Real Nix signatures in fresh private stores; no host store or VM mutation."""
from __future__ import annotations
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


class FixtureCacheSignatures(unittest.TestCase):
    def test_unsigned_fixture_is_refused_and_disposable_signature_is_accepted(self):
        with tempfile.TemporaryDirectory(prefix='assbox-fixture-signatures-') as temporary:
            directory = Path(temporary)
            source, target = directory / 'source', directory / 'target'
            physical = source / 'nix/store'
            physical.mkdir(parents=True)
            logical = '/nix/store/' + '0' * 32 + '-assbox-disposable-signature-control'
            content = b'public disposable fixture signature control\n'
            path = physical / Path(logical).name
            path.write_bytes(content)
            path.chmod(0o444)
            environment = {name: os.environ[name] for name in ('PATH', 'LANG', 'LC_ALL') if name in os.environ}
            environment.update(HOME=str(directory), NIX_USER_CONF_FILES='/dev/null',
                               NIX_CONFIG='accept-flake-config = false\naccess-tokens =\n')
            def run(*arguments, input_bytes=None):
                return subprocess.run(arguments, input=input_bytes, env=environment, capture_output=True, timeout=30)
            source_uri, target_uri = 'local?root=' + str(source), 'local?root=' + str(target)
            registered = run('nix-store', '--store', source_uri, '--register-validity',
                             input_bytes=(logical + '\n\n0\n').encode())
            self.assertEqual(registered.returncode, 0, registered.stderr)
            info = run('nix', 'path-info', '--store', source_uri, '--json', '--json-format', '1', logical)
            self.assertEqual(info.returncode, 0, info.stderr)
            proof = json.loads(info.stdout)[logical]
            self.assertIsNone(proof['ca'])
            self.assertFalse(proof['ultimate'])
            self.assertEqual(proof['signatures'], [])
            public = (ROOT / 'tests/fixtures/nix-cache-test.pub').read_text().strip()
            command = ['nix', 'copy', '--from', source_uri, '--to', target_uri,
                       '--option', 'require-sigs', 'true', '--option', 'trusted-public-keys', public, logical]
            before = run(*command)
            self.assertNotEqual(before.returncode, 0)
            self.assertIn(b'lacks a signature', before.stderr)
            self.assertFalse((target / logical.removeprefix('/')).exists())
            signed = run('nix', 'store', 'sign', '--store', source_uri, '--recursive',
                         '--key-file', str(ROOT / 'tests/fixtures/nix-cache-test.key'), logical)
            self.assertEqual(signed.returncode, 0, signed.stderr)
            after = run(*command)
            self.assertEqual(after.returncode, 0, after.stderr)
            self.assertEqual((target / logical.removeprefix('/')).read_bytes(), content)
            received = run('nix', 'path-info', '--store', target_uri, '--json', '--json-format', '1', logical)
            self.assertEqual(received.returncode, 0, received.stderr)
            signatures = json.loads(received.stdout)[logical]['signatures']
            self.assertEqual(len([value for value in signatures if value.startswith('assbox-disposable-vm-1:')]), 1)


if __name__ == '__main__':
    unittest.main()
