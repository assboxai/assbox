# SPDX-License-Identifier: GPL-3.0-or-later
"""Exercise bootstrap boundaries absent on a workstation with preinstalled Just."""
import copy
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
import clear_nix_credentials
import workflow_policy
import yaml


class BootstrapBoundaries(unittest.TestCase):
    def test_public_dispatch_works_without_just_on_path_and_preserves_arguments(self):
        executable = shutil.which('just')
        self.assertIsNotNone(executable, 'The verification environment must provide pinned Just')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            commands = root / 'commands'
            commands.mkdir()
            (commands / 'sh').symlink_to(shutil.which('sh'))
            env = {**os.environ, 'PATH': str(commands)}
            self.assertIsNone(shutil.which('just', path=env['PATH']))
            # Replace only the runtime transport boundary; retain every real public recipe.
            body = ('chainman +args:\n    #!/bin/sh\n    exec ' + shlex.quote(sys.executable)
                    + ' -I -B -c ' + shlex.quote('import json,sys; print(json.dumps(sys.argv[1:]))')
                    + ' "$@"\n')
            source = (ROOT / 'justfile').read_text()
            source, count = re.subn(r'chainman \+args:\n.*?(?=\n\[positional-arguments\])',
                                    lambda _: body, source, count=1, flags=re.S)
            self.assertEqual(count, 1)
            (root / 'justfile').write_text(source)
            for recipe, expected in [('setup', ['setup']), ('verify', ['run', 'verify', '--']),
                                     ('explain', ['explain'])]:
                arguments = ['--no-hooks', 'a b', '$(touch forbidden)', '`touch forbidden`', ';']
                result = subprocess.run([executable, recipe, *arguments], cwd=root, env=env,
                                        capture_output=True, text=True, timeout=20)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(json.loads(result.stdout), expected + arguments)
                self.assertFalse((root / 'forbidden').exists())

    def test_cleanup_removes_persisted_tokens_and_preserves_noncredential_settings(self):
        original = (b'trusted-users = root runner\n# settings\n'
                    b'access-tokens = github.com=dummy-secret\n'
                    b'extra-access-tokens = example.com=second-secret\\\n continued-secret\n'
                    b'experimental-features = nix-command flakes\n')
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / 'nix.conf'
            config.write_bytes(original)
            config.chmod(0o640)
            clear_nix_credentials.rewrite(config, os.getuid())
            self.assertEqual(config.read_bytes(), b'trusted-users = root runner\n# settings\n'
                             b'experimental-features = nix-command flakes\naccess-tokens =\n')
            self.assertEqual(config.stat().st_mode & 0o777, 0o640)
            self.assertEqual(list(Path(directory).iterdir()), [config])

    def test_indirect_or_oversized_configuration_cannot_claim_cleanup(self):
        for value in [b'!include another.conf\n', b'include another.conf\n',
                      b'a' * (clear_nix_credentials.MAX_CONFIG + 1)]:
            with self.assertRaises(ValueError):
                clear_nix_credentials.sanitized(value)

    def test_every_installer_requires_exact_unconditional_immediate_cleanup(self):
        for path in (ROOT / '.github/workflows').glob('*.yml'):
            original = yaml.load(path.read_text(), Loader=workflow_policy.WorkflowLoader)
            for name, job in original['jobs'].items():
                for index, step in enumerate(job['steps']):
                    if step.get('uses') != workflow_policy.NIX:
                        continue
                    for change in ('remove', 'conditional', 'reorder', 'alter', 'duplicate'):
                        with self.subTest(workflow=path.name, job=name, change=change):
                            document = copy.deepcopy(original)
                            steps = document['jobs'][name]['steps']
                            cleanup = steps[index + 1]
                            if change == 'remove':
                                steps.pop(index + 1)
                            elif change == 'conditional':
                                cleanup['if'] = 'false'
                            elif change == 'reorder':
                                steps[index], steps[index + 1] = cleanup, steps[index]
                            elif change == 'alter':
                                cleanup['run'] = 'true'
                            else:
                                steps.insert(index + 1, copy.deepcopy(cleanup))
                            self.assertTrue(workflow_policy.check_document(path.name, document))
