# SPDX-License-Identifier: GPL-3.0-or-later
import importlib.util
import ast
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
import repair_loop
from candidate_snapshot import capture, git, materialize


def fixture_module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / ('tests/fixtures/' + name + '.py'))
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


terminal = fixture_module('installer_cli_terminal')
transport = fixture_module('installer_cli_transport')
INVENTORY = dict(root='/dev/vdc2', esp='/dev/vdc1', backup='/dev/vdd1',
    target_by_id='/dev/disk/by-id/virtio-assbox-repair-target', admin_key='ssh-ed25519 AAAAdisposable fixture')


class Terminal(unittest.TestCase):
    def test_collection_never_restarts_stopped_installer_or_unstarted_target(self):
        with tempfile.TemporaryDirectory() as directory:
            calls = []
            class Machine:
                booted = False
                connected = False
                def __init__(self, name):
                    self.out_dir = Path(directory) / name; self.out_dir.mkdir()
                def succeed(self, *args, **kwargs): calls.append('execute'); raise RuntimeError('would auto-start')
                def copy_from_vm(self, *args, **kwargs): calls.append('copy'); raise RuntimeError('would auto-start')
            tree = ast.parse((ROOT / 'tests/fixtures/installer_cli_cases.py').read_text())
            function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'collect')
            scope = dict(installer=Machine('installer'), target=Machine('target'), postboot=[], CASE='/fixture', json=json)
            exec(compile(ast.Module(body=[function], type_ignores=[]), 'reviewed-collection', 'exec'), scope)
            scope['collect']()
            self.assertEqual(calls, [])
            self.assertEqual(json.loads((scope['target'].out_dir / 'postboot.json').read_text()), [])

    def test_fragmented_utf8_no_newline_prompts_crlf_and_complete_sequence(self):
        dialogue = terminal.Dialogue(INVENTORY)
        answers = []
        for label in dialogue.labels:
            raw = ('\r\nObserved α fixture context\r\n' + label + ' [none]: ').encode()
            for byte in raw:
                answer = dialogue.feed(bytes([byte]))
                if answer is not None: answers.append(answer)
        self.assertEqual(len(answers), 28)
        self.assertEqual(answers[0], '/dev/vdc2\n')
        self.assertEqual(answers[-1], 'INSTALL DISK /dev/disk/by-id/virtio-assbox-repair-target AS assbox-repair-vm\n')

    def test_previous_log_substring_wrong_state_and_disk_confirmation_fail_closed(self):
        dialogue = terminal.Dialogue(INVENTORY)
        self.assertIsNone(dialogue.feed(b'log mentioned Prepared empty ext4 root partition: then continued\n'))
        with self.assertRaises(ValueError): dialogue.feed(b'\nHostname [other]: ')
        dialogue = terminal.Dialogue(INVENTORY)
        with self.assertRaises(ValueError): dialogue.feed(b'\nType exactly: INSTALL DISK /dev/vda AS other: ')

    def test_real_pty_fixture_and_early_eof(self):
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory) / 'dialogue.py'
            dialogue = terminal.Dialogue(INVENTORY)
            script.write_text('import os,sys\nassert os.isatty(0)\n' +
                'labels=' + repr(dialogue.labels) + '\n' +
                'for label in labels:\n sys.stdout.write("\\n"+label+": "); sys.stdout.flush(); assert sys.stdin.readline()\n')
            terminal.run([sys.executable, str(script)], INVENTORY, Path(directory) / 'ok', prompt_seconds=2, total_seconds=10)
            result = json.loads((Path(directory) / 'ok/terminal-summary.json').read_text())
            self.assertEqual(result['status'], 'passed')
            script.write_text('import sys\nsys.exit(7)\n')
            with self.assertRaises(ValueError): terminal.run([sys.executable, str(script)], INVENTORY, Path(directory) / 'bad', prompt_seconds=1, total_seconds=2)

    def test_unknown_time_password_and_privileged_tools_are_never_stubbed(self):
        case = {'urls': {}, 'revision': 'a' * 40, 'proof': []}
        self.assertEqual(transport.dispatch('timedatectl', ['show', '--property=Timezone', '--value'], case), 'UTC')
        self.assertEqual(transport.dispatch('timedatectl', ['show', '--property=NTPSynchronized', '--value'], case), 'yes')
        for tool, args in [('nix', ['build']), ('nixos-install', []), ('timedatectl', ['set-time', 'now']), ('systemd-ask-password', ['other'])]:
            with self.assertRaises(ValueError): transport.dispatch(tool, args, case)


class Sessions(unittest.TestCase):
    def test_completion_and_timeout_drain_owned_group_after_parent_exits(self):
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory)
            script = run / 'spawn.py'
            script.write_text('import subprocess,sys\nsubprocess.Popen([sys.executable,"-c","import time; time.sleep(60)"])\n')
            cleanup = {}
            code, elapsed = repair_loop.process([sys.executable, str(script)], run, run / 'log', 2, cleanup)
            self.assertEqual(code, 0)
            self.assertLess(elapsed, 2)
            self.assertTrue(cleanup['owned_group_drained'])
            with self.assertRaises(repair_loop.Blocked):
                repair_loop.process([sys.executable, '-c', 'import os,time; os.close(1); os.close(2); time.sleep(60)'], run, run / 'closed-output', 0.2, cleanup)
            self.assertTrue(cleanup['owned_group_drained'])
            self.assertFalse(cleanup['daemon_builder_cancellation_proven'])
            with self.assertRaises(repair_loop.Blocked):
                repair_loop.process([sys.executable, '-c', 'import time; time.sleep(60)'], run, run / 'timeout', 0.2, cleanup)
            self.assertTrue(cleanup['owned_group_drained'])

    def make(self, directory):
        files = {p.relative_to(ROOT).as_posix(): ('100644', p.read_bytes()) for p in [
            ROOT / 'development/canonical-scenario.json', ROOT / 'development/candidate-snapshot-policy.json',
            ROOT / 'tests/nix/installer-cli-driver.nix', ROOT / 'tests/fixtures/installer_cli_terminal.py', ROOT / 'tests/fixtures/installer_cli_cases.py']}
        files['modules/product.nix'] = '100644', b'{ }\n'
        files['flake.nix'] = '100644', b'{ checks = {}; }\n'
        files['crates/product/tests/acceptance.rs'] = '100644', b'// original acceptance\n'
        files['flake.lock'] = '100644', b'locked\n'
        files['chainman.lock'] = '100644', b'a' * 40 + b'\n'
        files['nix/dev/flake.lock'] = '100644', b'locked-dev\n'
        source = Path(directory) / 'source'; materialize(files, source)
        session_path = repair_loop.initialise(source, Path(directory) / 'session')
        return source, session_path, json.loads((session_path / 'session.json').read_text())

    def test_freezes_transitive_oracle_allows_product_repairs_rejects_judge_and_pin_drift(self):
        with tempfile.TemporaryDirectory() as directory:
            source, path, session = self.make(directory)
            (source / 'modules/product.nix').write_text('{ changed = true; }\n')
            repair_loop.candidate_files(path, session)
            (source / 'flake.lock').write_text('changed\n')
            with self.assertRaises(repair_loop.Blocked): repair_loop.candidate_files(path, session)
            oracle = path / 'oracle/tests/fixtures/installer_cli_cases.py'
            oracle.chmod(0o644); oracle.write_text('pass\n')
            with self.assertRaises(repair_loop.Blocked): repair_loop.check_oracle(path, session)

    def test_root_gate_definitions_and_existing_crate_tests_are_protected(self):
        for name in ('flake.nix', 'crates/product/tests/acceptance.rs'):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                source, path, session = self.make(directory)
                (source / name).write_text('// weaker acceptance\n')
                with self.assertRaises(repair_loop.Blocked): repair_loop.candidate_files(path, session)
        with tempfile.TemporaryDirectory() as directory:
            source, path, session = self.make(directory)
            name = 'crates/product/tests/regression.rs'
            (source / name).write_text('// new regression\n')
            self.assertIn(name, repair_loop.candidate_files(path, session, [name]))

    def test_failed_execution_keeps_vm_marker_actual_exit_and_partial_assertions(self):
        with tempfile.TemporaryDirectory() as directory:
            source, path, session = self.make(directory)
            driver = Path(directory) / 'fake-driver'
            store_path = '/nix/store/fixture-only-driver'
            (driver / 'bin').mkdir(parents=True)
            (driver / 'bin/nixos-test-driver').write_text('fixture only\n')
            runtime = dict(issues=[], host_system='x86_64-linux', guest_system='x86_64-linux', accelerator='kvm')
            def fake_process(command, run, logfile, timeout, cleanup):
                cleanup.update(owned_group_drained=True, daemon_builder_cancellation_proven=False)
                if command[0] == 'nix':
                    self.assertEqual(command[1], 'build')
                    logfile.write_text(store_path + '\n')
                    return 0, 0.1
                self.assertEqual(command[0], str(driver / 'bin/nixos-test-driver'))
                output = run / 'driver-output'
                repair_loop.atomic(output / 'vm-started.json', {'fixture': True})
                (output / 'target').mkdir()
                repair_loop.atomic(output / 'target/postboot.json', [{'id': 'P01', 'status': 'passed'}])
                logfile.write_text('AssertionError: P02 fixture failure\n')
                return 7, 0.2
            with mock.patch.object(repair_loop, 'capabilities', return_value=runtime), \
                 mock.patch.object(repair_loop, 'process', side_effect=fake_process), \
                 mock.patch.object(repair_loop, 'Path', side_effect=lambda name: driver if name == store_path else Path(name)):
                run = repair_loop.once(path, session)
            result = json.loads((run / 'summary.json').read_bytes())
            self.assertEqual(result['status'], 'failed', result.get('failure'))
            self.assertTrue(result['vm_executed'])
            self.assertEqual(result['driver_exit_code'], 7)
            self.assertEqual(result['exit_code'], 1)
            self.assertEqual(result['postboot'], [{'id': 'P01', 'status': 'passed'}])

    def test_state_refuses_source_overlap_existing_paths_symlinks_and_shared_permissions(self):
        with tempfile.TemporaryDirectory() as directory:
            source, path, session = self.make(directory)
            with self.assertRaises(ValueError): repair_loop.private(source / 'state', source, create=True)
            with self.assertRaises(FileExistsError): repair_loop.initialise(source, path)
            alias = Path(directory) / 'alias'; alias.symlink_to(path, target_is_directory=True)
            with self.assertRaises(ValueError): repair_loop.private(alias)
            path.chmod(0o755)
            with self.assertRaises(ValueError): repair_loop.private(path)

    def test_preflight_status_and_build_inspection_cannot_launch_a_vm(self):
        with tempfile.TemporaryDirectory() as directory:
            source, path, session = self.make(directory)
            with mock.patch.object(repair_loop, 'process', side_effect=AssertionError('VM launched')):
                repair_loop.capabilities(path, session)
                result = repair_loop.inspect(path, session)
            self.assertFalse(result['vm_executed'])
            self.assertEqual(result['attempts'], [])

    def test_stale_success_incomplete_runs_and_frozen_budgets(self):
        with tempfile.TemporaryDirectory() as directory:
            source, path, session = self.make(directory)
            files, _ = capture(source)
            run = path / 'runs/000001'; run.mkdir()
            repair_loop.atomic(run / 'summary.json', dict(status='passed', candidate_content_sha256=repair_loop.file_identity(files), attempt_id='000001'))
            self.assertEqual(repair_loop.inspect(path, session)['attempts'][0]['status'], 'incomplete')
            receipt = materialize(files, run / 'source')
            repair_loop.atomic(run / 'summary.json', dict(status='passed', candidate_content_sha256=repair_loop.file_identity(files), attempt_id='000001',
                candidate_snapshot=receipt, vm_executed=True, exit_code=0, oracle_sha256=session['oracle_sha256'],
                postboot=[{'id': 'P%02d' % n, 'status': 'passed'} for n in range(1, 15)], cleanup={'owned_group_drained': True}))
            self.assertEqual(repair_loop.inspect(path, session)['attempts'][0]['status'], 'passed')
            (source / 'modules/product.nix').write_text('{ changed = true; }\n')
            self.assertEqual(repair_loop.inspect(path, session)['attempts'][0]['status'], 'stale')
            (path / 'runs/000002').mkdir()
            self.assertEqual(repair_loop.history(path)[1]['status'], 'incomplete')
            session['budgets']['max_attempts'] = 2
            with self.assertRaises(repair_loop.Blocked): repair_loop.budget(path, session)
