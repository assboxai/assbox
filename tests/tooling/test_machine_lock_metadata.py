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
    def test_final_fetcher_marker_is_omitted_without_changing_authenticated_pins(self):
        dependencies = json.loads((ROOT / 'flake.lock').read_bytes())
        url = 'https://github.com/assboxai/assbox/releases/download/r-100/assbox-source.tar.gz'
        hash_value = 'sha256-' + 'A' * 43 + '='
        locked = dict(type='tarball', url=url, narHash=hash_value,
                      lastModified=1790000000, __final=True)
        original = dict(type='tarball', url=url, narHash=hash_value)
        metadata = dict(locks=dependencies, locked=locked, original=original)
        before = copy.deepcopy(metadata)
        jq = shutil.which('jq')
        self.assertIsNotNone(jq, 'The actual lock adapter requires jq')
        result = subprocess.run([jq, '-e', '-S', '--arg', 'url', url, '--arg', 'hash', hash_value,
                                 '-f', str(ROOT / 'nix/machine-lock.jq')],
                                input=json.dumps(metadata), capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        machine = json.loads(result.stdout)
        root = dependencies['root']
        self.assertEqual(machine['nodes'][root]['locked'],
                         {key: value for key, value in locked.items() if key != '__final'})
        self.assertEqual(machine['nodes'][root]['original'], original)
        self.assertEqual(machine['nodes']['_assbox_machine']['inputs'],
                         dict(assbox=root, nixpkgs=['assbox', 'nixpkgs']))
        for name, node in dependencies['nodes'].items():
            if name != root:
                self.assertEqual(machine['nodes'][name].get('locked'), node.get('locked'))
                self.assertEqual(machine['nodes'][name].get('original'), node.get('original'))
        self.assertEqual(metadata, before)


if __name__ == '__main__':
    unittest.main()
