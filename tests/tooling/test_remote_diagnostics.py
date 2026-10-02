# SPDX-License-Identifier: GPL-3.0-or-later
"""Execute Nix-rendered diagnostic scripts with fake user-manager/provider effects."""
import fcntl
import json
import os
from pathlib import Path
import shutil
import shlex
import signal
import subprocess
import sys
import tempfile
import time
import unittest
import test_component_catalog as catalog_tests


class RemoteScriptFixture:
    @classmethod
    def setUpClass(cls):
        catalog_tests.ComponentCatalogTests.setUpClass()
        evaluator = catalog_tests.ComponentCatalogTests()
        selection = {id: {'enable': True, 'allowMutableCode': True} for id in
                     ['claude-code', 'claude-code-remote', 'cursor-agent', 'cursor-worker',
                      'openclaw', 'openclaw-node', 'happier', 'happier-daemon', 'codex',
                      'vscode-cli', 'vscode-tunnel']}
        selection['cursor-worker']['computerUse'] = {'enable': False}
        cls.scripts = evaluator.evaluate(selection, presentation='x11')['scripts']

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='assbox-diagnostic-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.bin = self.root / 'bin'; self.bin.mkdir()
        self.home = self.root / 'home'; self.home.mkdir()
        self.runtime = self.root / 'runtime'; self.runtime.mkdir()
        self.state = self.root / 'state.json'
        self.state.write_text(json.dumps({'state': 'active', 'graphical': True}))
        self.calls = self.root / 'calls'
        stub = self.bin / 'stub'
        stub.write_text(f'#!{sys.executable}\n' + '''
import json, os, pathlib, sys, time
name = pathlib.Path(sys.argv[0]).name
with open(os.environ['CALLS'], 'a') as out: out.write(json.dumps([name] + sys.argv[1:]) + '\\n')
path = pathlib.Path(os.environ['STATE'])
state = json.loads(path.read_text())
if name == 'id':
    print('agent')
elif name == 'systemctl':
    args = sys.argv[1:]
    if 'show' in args: print(state['state'])
    elif 'is-active' in args: sys.exit(0 if state['graphical'] else 3)
    elif 'stop' in args: state['state'] = 'inactive'
    elif 'start' in args or 'restart' in args: state['state'] = 'active'
    path.write_text(json.dumps(state))
elif name == 'systemd-run':
    mode = os.environ.get('MODE', 'failure')
    if mode == 'wait':
        print('PRIVATE_PROVIDER_TOKEN', flush=True)
        time.sleep(30)
    elif mode == 'flood':
        try: sys.stdout.write('PRIVATE_PROVIDER_TOKEN' * 100000)
        except BrokenPipeError: pass
    elif mode == 'session-ended':
        state['graphical'] = False
        path.write_text(json.dumps(state))
    else: print('PRIVATE_PROVIDER_TOKEN')
    sys.exit(7)
else:
    # Provider descendants must not inherit the onboarding operation lock.
    try: os.fstat(9)
    except OSError: pass
    else: sys.exit(88)
''')
        stub.chmod(0o755)
        for name in ['id', 'systemctl', 'systemd-run', 'claude', 'cursor-agent', 'openclaw', 'happier', 'assbox-vscode']:
            (self.bin / name).symlink_to(stub)
        self.env = os.environ | {'CALLS': str(self.calls), 'STATE': str(self.state),
                                 'XDG_RUNTIME_DIR': str(self.runtime)}

    def script(self, id, kind='diagnostics'):
        text = self.scripts['assbox/' + kind + '/' + id]
        text = text.replace('/home/agent', str(self.home))
        text = text.replace('export PATH=/run/current-system/sw/bin:/run/wrappers/bin',
                            'export PATH=' + shlex.quote(os.environ['PATH']))
        for package, command in [('claude-code', 'claude'), ('cursor-agent', 'cursor-agent'),
                                 ('openclaw', 'openclaw'), ('happier', 'happier'), ('vscode-cli', 'assbox-vscode')]:
            text = text.replace(f'/nix/store/test-{package}/bin/{command}', str(self.bin / command))
        for name in ['id', 'systemctl', 'systemd-run']:
            package = 'coreutils' if name == 'id' else 'systemd'
            text = text.replace(f'/nix/store/test-{package}/bin/{name}', str(self.bin / name))
        for name in ['mkdir', 'chmod', 'mktemp', 'head', 'flock']:
            package = 'util-linux' if name == 'flock' else 'coreutils'
            executable = shutil.which(name)
            self.assertIsNotNone(executable)
            text = text.replace(f'/nix/store/test-{package}/bin/{name}', executable)
        script = self.root / (id + '.sh'); script.write_text(text)
        return script

    def recorded(self):
        return [json.loads(line) for line in self.calls.read_text().splitlines()]

    def run_capture(self, id='claude-code-remote', mode='failure'):
        return subprocess.run(['bash', str(self.script(id))], env=self.env | {'MODE': mode},
                              text=True, capture_output=True, timeout=5)


class RemoteDiagnosticsTests(RemoteScriptFixture, unittest.TestCase):
    def test_each_adapter_captures_privately_and_restores_after_failure(self):
        for id in ['claude-code-remote', 'cursor-worker', 'openclaw-node', 'happier-daemon', 'vscode-tunnel']:
            with self.subTest(id=id):
                result = self.run_capture(id)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertNotIn('PRIVATE_PROVIDER_TOKEN', result.stdout + result.stderr)
                log = next((self.home / '.local/state/assbox/diagnostics').glob('assbox-' + id + '.*.log'))
                self.assertIn('PRIVATE_PROVIDER_TOKEN', log.read_text())
                self.assertEqual(log.stat().st_mode & 0o777, 0o600)
                self.assertEqual(log.parent.stat().st_mode & 0o777, 0o700)
                self.assertEqual(json.loads(self.state.read_text())['state'], 'active')
                command = next(c for c in reversed(self.recorded()) if c[0] == 'systemd-run')
                for flag in ['--pipe', '--property=RuntimeMaxSec=300', '--property=KillMode=control-group',
                             '--property=NoNewPrivileges=true', '--property=UMask=0077']:
                    self.assertIn(flag, command)

    def test_output_cap_and_previously_stopped_service(self):
        self.state.write_text(json.dumps({'state': 'inactive', 'graphical': True}))
        result = self.run_capture(mode='flood')
        self.assertEqual(result.returncode, 0, result.stderr)
        log = next((self.home / '.local/state/assbox/diagnostics').glob('*.log'))
        self.assertEqual(log.stat().st_size, 1048576)
        self.assertFalse(any(call[0] == 'systemctl' and 'start' in call for call in self.recorded()))

    def test_physical_session_teardown_does_not_stop_a_headless_provider(self):
        result = self.run_capture('cursor-worker', 'session-ended')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(any(call[0] == 'systemctl' and 'start' in call for call in self.recorded()))

    def test_existing_operation_lock_prevents_any_service_changes(self):
        with (self.runtime / 'assbox-claude-code-remote.lock').open('w') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            result = self.run_capture()
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(any(call[0] == 'systemctl' for call in self.recorded()))

    def test_cancellation_stops_diagnostic_and_restores_managed_service(self):
        child = subprocess.Popen(['bash', str(self.script('claude-code-remote'))],
                                 env=self.env | {'MODE': 'wait'}, text=True,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
        try:
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                if self.calls.exists() and any(c[0] == 'systemd-run' for c in self.recorded()):
                    break
                time.sleep(.01)
            else:
                self.fail('capture did not start')
            os.killpg(child.pid, signal.SIGTERM)
            stdout, stderr = child.communicate(timeout=5)
            self.assertNotEqual(child.returncode, 0)
            self.assertNotIn('PRIVATE_PROVIDER_TOKEN', stdout + stderr)
            self.assertEqual(json.loads(self.state.read_text())['state'], 'active')
            self.assertIn(['systemctl', '--user', 'stop', 'assbox-claude-code-remote-diagnostic.service'], self.recorded())
        finally:
            if child.poll() is None:
                os.killpg(child.pid, signal.SIGKILL)
                child.communicate()
