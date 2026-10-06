# SPDX-License-Identifier: GPL-3.0-or-later
"""Test the observer with disposable commands, never with actual Nix builds."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('verify_observed', ROOT / 'scripts/verify_observed.py')
OBSERVER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(OBSERVER)


class ObservedVerificationTests(unittest.TestCase):
    def test_only_selected_numeric_metrics_are_collected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            proc = root / 'proc'; (proc / 'self').mkdir(parents=True)
            (proc / 'pressure').mkdir()
            (proc / 'meminfo').write_text('MemTotal: 123 kB\nMemAvailable: 12 kB\nTOKEN: private-value\n')
            (proc / 'pressure/memory').write_text('some avg10=1.5 total=123 secret=private-value\n')
            (proc / 'self/cgroup').write_text('0::/job\n')
            cgroup = root / 'cgroup'; (cgroup / 'job').mkdir(parents=True)
            (cgroup / 'job/memory.events').write_text('oom 2\noom_kill 1\nsecret private-value\n')
            (cgroup / 'memory.events').write_text('oom_kill 3\n')
            result = OBSERVER.snapshot(root, proc, cgroup)
            self.assertEqual(result['memory_kib'], {'MemTotal': 123, 'MemAvailable': 12})
            self.assertEqual(result['cgroup_memory_events']['self']['oom_kill'], 1)
            self.assertEqual(result['cgroup_memory_events']['ancestor-1']['oom_kill'], 3)
            self.assertEqual(result['pressure']['memory'], {'some': {'avg10': 1.5, 'total': 123.0}})
            self.assertIsNone(result['pressure']['cpu'])
            self.assertNotIn('private-value', json.dumps(result))
            (proc / 'self/cgroup').write_text('0::/../outside\n')
            self.assertIsNone(OBSERVER.snapshot(root, proc, cgroup)['cgroup_memory_events'])

    def test_periodic_records_and_original_failure_status(self):
        with tempfile.TemporaryDirectory() as temporary, contextlib.redirect_stdout(io.StringIO()), \
                patch.object(OBSERVER, 'INTERVAL', 0.01), patch.object(OBSERVER, 'snapshot', return_value={}):
            directory = Path(temporary)
            code = OBSERVER.observe('rust', directory,
                                    [sys.executable, '-c', 'import time; time.sleep(.25); raise SystemExit(71)'])
            self.assertEqual(code, 71)
            records = [json.loads(line) for line in (directory / 'rust.jsonl').read_text().splitlines()]
            self.assertEqual(records[0]['event'], 'start')
            self.assertIn('sample', [record['event'] for record in records])
            self.assertEqual(records[-1]['exit_code'], 71)

    def test_missing_metrics_and_unwritable_log_do_not_mask_command_status(self):
        with tempfile.TemporaryDirectory() as temporary, contextlib.redirect_stdout(io.StringIO()), \
                contextlib.redirect_stderr(io.StringIO()), patch.object(OBSERVER, 'snapshot', side_effect=PermissionError):
            directory = Path(temporary) / 'not-a-directory'; directory.write_text('fixture')
            for expected in (0, 42):
                code = OBSERVER.observe('static', directory, [sys.executable, '-c', f'raise SystemExit({expected})'])
                self.assertEqual(code, expected)

    def test_log_cap_keeps_the_final_status(self):
        with tempfile.TemporaryDirectory() as temporary, contextlib.redirect_stdout(io.StringIO()), \
                patch.object(OBSERVER, 'MAX_LOG_BYTES', 1), patch.object(OBSERVER, 'snapshot', return_value={}):
            log = OBSERVER.Diagnostics('nix', Path(temporary))
            for event in ('start', 'sample', 'sample'):
                log.emit(event)
            log.emit('finish', exit_code=73); log.close()
            records = [json.loads(line) for line in (Path(temporary) / 'nix.jsonl').read_text().splitlines()]
            self.assertEqual([record['event'] for record in records], ['start', 'finish'])
            self.assertEqual(records[-1]['exit_code'], 73)

    def test_cli_cancellation_is_forwarded_and_reported_without_secrets(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); tools = root / 'tools'; tools.mkdir()
            ready = root / 'ready'
            nix = tools / 'nix'
            nix.write_text('#!' + sys.executable + '\nimport json, os, pathlib, signal, sys, time\n'
                           'signal.signal(signal.SIGINT, signal.SIG_IGN)\n'
                           'ready = pathlib.Path(os.environ["READY"])\n'
                           'pending = ready.with_suffix(".pending")\n'
                           'pending.write_text(json.dumps([os.getpid(), sys.argv[1:]]))\n'
                           'pending.replace(ready)\n'
                           'time.sleep(30)\n')
            nix.chmod(0o755)
            env = dict(os.environ, PATH=str(tools) + os.pathsep + os.environ['PATH'], RUNNER_TEMP=str(root),
                       READY=str(ready), PRIVATE_TEST_TOKEN='never-log-this-value')
            process = subprocess.Popen([sys.executable, str(ROOT / 'scripts/verify_observed.py'), 'static'],
                                       env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            helper = None
            try:
                deadline = time.monotonic() + 5
                while not ready.exists() and process.poll() is None and time.monotonic() < deadline:
                    time.sleep(.01)
                self.assertTrue(ready.exists(), 'observer did not launch disposable command')
                helper, args = json.loads(ready.read_text())
                self.assertEqual(args, ['develop', '.#release-check', '--no-update-lock-file',
                                        '--no-write-lock-file', '--command', 'scripts/verify', 'static'])
                process.send_signal(signal.SIGINT)
                time.sleep(.2)
                self.assertIsNone(process.poll())
                # The observer must forward escalation, not swallow the second signal.
                process.send_signal(signal.SIGTERM)
                stdout, stderr = process.communicate(timeout=5)
                self.assertEqual(process.returncode, 143, stderr)
                records_text = (root / 'assbox-verification/static.jsonl').read_text()
                records = [json.loads(line) for line in records_text.splitlines()]
                self.assertEqual([r['signal'] for r in records if r['event'] == 'signal'],
                                 [signal.SIGINT, signal.SIGTERM])
                self.assertEqual(records[-1]['exit_code'], 143)
                self.assertFalse(Path(f'/proc/{helper}').exists())
                self.assertNotIn('never-log-this-value', stdout + stderr + records_text)
            finally:
                if process.poll() is None:
                    process.kill(); process.communicate()
                if helper and Path(f'/proc/{helper}').exists():
                    os.kill(helper, signal.SIGKILL)

    def test_cli_refuses_unknown_stage(self):
        result = subprocess.run([sys.executable, str(ROOT / 'scripts/verify_observed.py'), 'unknown'],
                                capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 2)


if __name__ == '__main__':
    unittest.main()
