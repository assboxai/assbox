# SPDX-License-Identifier: GPL-3.0-or-later
"""Onboarding/state-contract regressions; actual systemd execution is the VM gate."""
import ast
import json
from pathlib import Path
import subprocess
import textwrap
import unittest
import test_component_catalog as catalog_tests
from test_remote_diagnostics import RemoteScriptFixture

ROOT = Path(__file__).resolve().parents[2]


class RemoteOnboardingTests(RemoteScriptFixture, unittest.TestCase):
    def test_each_adapter_requires_explicit_permission_after_interactive_setup(self):
        for id in ['claude-code-remote', 'cursor-worker', 'openclaw-node', 'happier-daemon', 'vscode-tunnel']:
            with self.subTest(id=id):
                script = self.script(id, 'onboarding')
                result = subprocess.run(['bash', str(script)], input='no\n', text=True,
                                        env=self.env, capture_output=True, timeout=5)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(json.loads(self.state.read_text())['state'], 'inactive')
                markers = self.home / '.config/assbox/onboarded'
                self.assertEqual(list(markers.glob(id + '-*')), [])
                result = subprocess.run(['bash', str(script)], input='yes\n', text=True,
                                        env=self.env, capture_output=True, timeout=5)
                self.assertEqual(result.returncode, 0, result.stderr)
                marker = next(markers.glob(id + '-*'))
                self.assertEqual(marker.stat().st_mode & 0o777, 0o600)
                self.assertEqual(markers.stat().st_mode & 0o777, 0o700)
                self.assertEqual(json.loads(self.state.read_text())['state'], 'active')


class RemoteLifecycleContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        catalog_tests.ComponentCatalogTests.setUpClass()
        cls.evaluator = catalog_tests.ComponentCatalogTests()

    def test_permission_changes_with_settings_and_runtime_contract(self):
        selection = {'claude-code': {'enable': True}, 'claude-code-remote': {'enable': True}}
        first = self.evaluator.evaluate(selection)
        updated = self.evaluator.evaluate(selection, package_revision='updated')
        name = 'assbox-claude-code-remote'
        first_unit = first['services']['user']['services'][name]
        updated_unit = updated['services']['user']['services'][name]
        self.assertNotEqual(first_unit['serviceConfig']['ExecStart'], updated_unit['serviceConfig']['ExecStart'])
        self.assertNotEqual(first_unit['unitConfig']['ConditionPathExists'], updated_unit['unitConfig']['ConditionPathExists'])
        selection['claude-code-remote']['workingDirectory'] = '/home/agent/another-project'
        changed = self.evaluator.evaluate(selection)['services']['user']['services'][name]
        self.assertNotEqual(first_unit['unitConfig']['ConditionPathExists'], changed['unitConfig']['ConditionPathExists'])
        selection['claude-code-remote']['enable'] = False
        disabled = self.evaluator.evaluate(selection)
        self.assertNotIn(name, disabled['services']['user']['services'])
        self.assertNotIn('assbox/onboarding/claude-code-remote', disabled['scripts'])
        self.assertNotIn('assbox/diagnostics/claude-code-remote', disabled['scripts'])

    def test_gui_close_and_remote_exit_have_distinct_restart_contracts(self):
        selection = {id: {'enable': True, 'allowMutableCode': True} for id in
                     ['vscode', 'zed', 'emacs', 'cursor-agent', 'cursor-worker']}
        selection['emacs']['variant'] = 'gui'
        selection['cursor-worker']['computerUse'] = {'enable': False}
        result = self.evaluator.evaluate(selection, presentation='x11', autostart=['vscode', 'zed', 'emacs'])
        for id in ['vscode', 'zed', 'emacs', 'cursor-worker']:
            with self.subTest(id=id):
                unit = result['services']['user']['services']['assbox-' + id]
                self.assertEqual(unit['partOf'], [] if id=='cursor-worker' else ['graphical-session.target'])
                self.assertEqual(unit['unitConfig']['StartLimitIntervalSec'], 0)
                self.assertEqual(unit['serviceConfig']['Restart'], 'on-failure')
                self.assertEqual(unit['serviceConfig']['RestartSec'], 20)
                self.assertEqual(unit['serviceConfig']['RestartMaxDelaySec'], 300)
                self.assertEqual(unit['serviceConfig']['KillMode'], 'control-group')
                if id != 'cursor-worker':
                    self.assertEqual(unit['serviceConfig']['ExitType'], 'main')
        services = result['services']['user']['services']
        self.assertTrue(services['assbox-zed']['serviceConfig']['ExecStart'].endswith('/libexec/zed-editor'))
        self.assertTrue(services['assbox-vscode']['serviceConfig']['ExecStart'].endswith('/bin/assbox-vscode-gui'))

    def test_native_gate_is_required_and_driver_is_valid_python(self):
        self.assertIn('remote-lifecycle-vm = import ./tests/nix/remote-lifecycle-vm.nix', (ROOT / 'flake.nix').read_text())
        self.assertIn('remote-lifecycle-vm', (ROOT / 'scripts/release-check').read_text())
        source = (ROOT / 'tests/nix/remote-lifecycle-vm.nix').read_text()
        script = source.split("testScript = ''", 1)[1].rsplit("'';", 1)[0]
        for variable in ['remoteIds', 'guiIds']:
            script = script.replace('${builtins.toJSON ' + variable + '}', '[]')
        ast.parse(textwrap.dedent(script))
        ast.parse((ROOT / 'tests/fixtures/remote_provider.py').read_text())
        self.assertIn('editor-vm = import ./tests/nix/editor-vm.nix', (ROOT / 'flake.nix').read_text())
        source = (ROOT / 'tests/nix/editor-vm.nix').read_text()
        ast.parse(textwrap.dedent(source.split("testScript = ''", 1)[1].rsplit("'';", 1)[0]))
