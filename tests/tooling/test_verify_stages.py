# SPDX-License-Identifier: GPL-3.0-or-later
"""Exercise the real dispatcher with inert tools; never run heavy gates here."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ('cargo', 'rustc', 'rustfmt', 'nix', 'nixfmt', 'python3', 'node',
         'shellcheck', 'actionlint', 'jq', 'systemd-analyze')


class VerifyStagesTests(unittest.TestCase):
    def run_stage(self, *args, fail=None):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'scripts').mkdir()
            shutil.copy2(ROOT / 'scripts/verify', root / 'scripts/verify')
            (root / 'flake.lock').write_text('{}')
            (root / 'fixture.nix').write_text('{}')
            (root / 'modules/sessions').mkdir(parents=True)
            (root / 'modules/sessions/fixture.sh').write_text('#!/bin/sh\ntrue\n')
            tools = root / 'tools'; tools.mkdir()
            log = root / 'calls.jsonl'
            stub = ('#!' + sys.executable + '\n'
                    'import json, os, pathlib, sys\n'
                    'call = [pathlib.Path(sys.argv[0]).name] + sys.argv[1:]\n'
                    'with open(os.environ["CALLS"], "a") as out: out.write(json.dumps(call) + "\\n")\n'
                    'if call[0] == "nix" and call[1] == "eval": print("aarch64-linux" if "builtins.currentSystem" in call else json.dumps(["one", "two"]))\n'
                    'if call[0] == "jq": print("one\\ntwo")\n'
                    'sys.exit(71 if call == json.loads(os.environ["FAIL_CALL"]) else 0)\n')
            for name in TOOLS:
                path = tools / name; path.write_text(stub); path.chmod(0o755)
            env = dict(os.environ, PATH=str(tools) + os.pathsep + os.environ['PATH'],
                       CALLS=str(log), FAIL_CALL=json.dumps(fail))
            result = subprocess.run([str(root / 'scripts/verify'), *args], cwd=root, env=env,
                                    capture_output=True, text=True, timeout=20)
            calls = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
            return result, calls

    def test_default_runs_every_stage_in_order(self):
        result, all_calls = self.run_stage()
        self.assertEqual(result.returncode, 0, result.stderr)
        individual = []
        for stage in ('static', 'rust', 'mutations', 'nix'):
            selected, calls = self.run_stage(stage)
            self.assertEqual(selected.returncode, 0, selected.stderr)
            individual.extend(calls)
        self.assertEqual(all_calls, individual)
        for required in (['python3', 'scripts/architecture.py'], ['python3', 'scripts/workflow_policy.py'],
                         ['python3', '-m', 'unittest', 'discover', '-s', 'tests/tooling', '-v'],
                         ['python3', '-m', 'unittest', 'discover', '-s', 'tests/worker', '-v'],
                         ['python3', 'scripts/model_check.py'], ['cargo', 'fmt', '--all', '--check'],
                         ['cargo', 'clippy', '--workspace', '--all-targets', '--locked', '--', '-D', 'warnings'],
                         ['cargo', 'build', '--workspace', '--locked'],
                         ['cargo', 'test', '--workspace', '--all-targets', '--locked'],
                         ['python3', 'scripts/mutations.py'],
                         ['nix', 'build', '--no-link', '--no-update-lock-file', '--no-write-lock-file', '--keep-going', '.#checks.aarch64-linux.two']):
            self.assertIn(required, all_calls)
        for tool in ('node', 'nixfmt', 'shellcheck', 'actionlint', 'systemd-analyze'):
            self.assertIn(tool, [call[0] for call in all_calls])

    def test_static_never_runs_build_mutation_or_flake_evaluation(self):
        result, calls = self.run_stage('static')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(any(call[0] == 'nix' for call in calls))
        self.assertEqual([call for call in calls if call[0] == 'cargo'],
                         [['cargo', 'fmt', '--all', '--check']])
        self.assertNotIn(['python3', 'scripts/mutations.py'], calls)

    def test_failure_stops_default_and_preserves_exit_status(self):
        for failed in (['python3', 'scripts/architecture.py'],
                       ['cargo', 'clippy', '--workspace', '--all-targets', '--locked', '--', '-D', 'warnings'],
                       ['python3', 'scripts/mutations.py'],
                       ['nix', 'build', '--no-link', '--no-update-lock-file', '--no-write-lock-file', '--keep-going', '.#checks.aarch64-linux.two']):
            with self.subTest(failed=failed):
                result, calls = self.run_stage(fail=failed)
                self.assertEqual(result.returncode, 71, result.stderr)
                self.assertEqual(calls[-1], failed)

    def test_failed_nix_check_does_not_skip_later_checks_or_become_success(self):
        first = ['nix', 'build', '--no-link', '--no-update-lock-file', '--no-write-lock-file', '--keep-going', '.#checks.aarch64-linux.one']
        result, calls = self.run_stage('nix', fail=first)
        self.assertEqual(result.returncode, 71)
        self.assertIn(first, calls)
        self.assertIn(first[:-1] + ['.#checks.aarch64-linux.two'], calls)

    def test_bad_arguments_execute_nothing(self):
        for args in (('unknown',), ('',), ('static', 'rust')):
            result, calls = self.run_stage(*args)
            self.assertEqual(result.returncode, 2)
            self.assertEqual(calls, [])


if __name__ == '__main__':
    unittest.main()
