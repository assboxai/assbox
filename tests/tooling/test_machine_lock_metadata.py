# SPDX-License-Identifier: GPL-3.0-or-later
"""Regression for Nix metadata's runtime attributes crossing into lock files."""
import copy
import json
from pathlib import Path
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[2]


class MachineLockMetadataTests(unittest.TestCase):
    def test_local_metadata_is_rebound_to_authenticated_release_pins(self):
        dependencies = json.loads((ROOT / 'flake.lock').read_bytes())
        url = 'https://github.com/assboxai/assbox/releases/download/r-100/assbox-source.tar.gz'
        hash_value = 'sha256-' + 'A' * 43 + '='
        path = '/nix/store/' + '0' * 32 + '-source'
        locked = dict(type='path', path=path, narHash=hash_value,
                      lastModified=0, __final=True)
        original = dict(type='path', path=path)
        metadata = dict(path=path, locks=dependencies, locked=locked, original=original)
        before = copy.deepcopy(metadata)
        jq = shutil.which('jq')
        self.assertIsNotNone(jq, 'The actual lock adapter requires jq')
        result = subprocess.run([jq, '-e', '-S', '--arg', 'url', url, '--arg', 'hash', hash_value,
                                 '--arg', 'path', path,
                                 '-f', str(ROOT / 'nix/machine-lock.jq')],
                                input=json.dumps(metadata), capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        machine = json.loads(result.stdout)
        root = dependencies['root']
        release = dict(type='tarball', url=url, narHash=hash_value)
        self.assertEqual(machine['nodes'][root]['locked'], release)
        self.assertEqual(machine['nodes'][root]['original'], release)
        self.assertEqual(machine['nodes']['_assbox_machine']['inputs'],
                         dict(assbox=root, nixpkgs=['assbox', 'nixpkgs']))
        for name, node in dependencies['nodes'].items():
            if name != root:
                self.assertEqual(machine['nodes'][name].get('locked'), node.get('locked'))
                self.assertEqual(machine['nodes'][name].get('original'), node.get('original'))
        self.assertEqual(metadata, before)


if __name__ == '__main__':
    unittest.main()
