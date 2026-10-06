# SPDX-License-Identifier: GPL-3.0-or-later
"""Evaluate launcher selection; actual terminal/application behavior is a VM gate."""
import ast
import json
import shlex
import subprocess
import unittest
from pathlib import Path

import test_component_catalog as catalog_tests

ROOT = Path(__file__).resolve().parents[2]


class ApplicationLauncherTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        catalog_tests.ComponentCatalogTests.setUpClass()
        cls.lib = catalog_tests.ComponentCatalogTests.lib

    def evaluate(self, presentation, autostart, scale=1):
        if not self.lib:
            self.skipTest('Nix module library unavailable; run in the development shell')
        result = subprocess.run([
            'nix-instantiate', '--eval', '--strict', '--json',
            'tests/nix/application-eval.nix', '--arg', 'libPath', self.lib,
            '--argstr', 'presentation', presentation,
            '--arg', 'autostart', 'builtins.fromJSON ' + json.dumps(json.dumps(autostart)),
            '--arg', 'scale', str(scale),
        ], cwd=ROOT, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_x11_uses_child_failure_aware_terminal_with_terminfo_and_scale(self):
        for scale in (1, 2, 3):
            with self.subTest(scale=scale):
                result = self.evaluate('x11', ['opencode-attach'], scale)
                service = result['services']['assbox-opencode-ui']['serviceConfig']
                self.assertEqual(service['ExecStart'],
                    '/inert/st/bin/st -c AssboxOpenCode -f monospace:pixelsize=' + str(12 * scale) +
                    ' -e /inert/assbox/bin/assbox internal opencode attach')
                self.assertIn('/inert/st', result['packages'])
                self.assertEqual(service['Restart'], 'on-failure')
                self.assertEqual(service['ExitType'], 'main')
                self.assertEqual(service['KillMode'], 'control-group')
                self.assertEqual(service['RestartMaxDelaySec'], 60)

    def test_wayland_keeps_foot_and_other_selections_do_not_add_st(self):
        result = self.evaluate('wayland', ['opencode-attach'])
        service = result['services']['assbox-opencode-ui']['serviceConfig']
        self.assertTrue(service['ExecStart'].startswith('/inert/foot/bin/foot '))
        self.assertEqual(service['SuccessExitStatus'], [230])
        self.assertEqual(service['RestartForceExitStatus'], [230])
        self.assertNotIn('/inert/st', result['packages'])
        x11_service = self.evaluate('x11', ['opencode-attach'])['services'][
            'assbox-opencode-ui']['serviceConfig']
        self.assertEqual(x11_service['SuccessExitStatus'], [])
        self.assertEqual(x11_service['RestartForceExitStatus'], [])
        for mode in ('headless', 'x11', 'wayland'):
            with self.subTest(mode=mode):
                result = self.evaluate(mode, [])
                self.assertNotIn('assbox-opencode-ui', result['services'])
                self.assertNotIn('/inert/st', result['packages'])
                self.assertIn('assbox-opencode', result['services'])

    def test_dashboard_owns_a_private_persistent_browser_profile(self):
        for mode in ('x11', 'wayland'):
            with self.subTest(mode=mode):
                result = self.evaluate(mode, ['openclaw-dashboard', 'opencode-attach'])
                service = result['services']['assbox-openclaw-ui']['serviceConfig']
                args = shlex.split(service['ExecStart'])
                self.assertEqual(args, ['/inert/chromium/bin/chromium',
                    '--user-data-dir=%h/.local/share/assbox/openclaw-browser',
                    '--app=http://127.0.0.1:18789/'])
                self.assertEqual(service['UMask'], '0077')
                self.assertEqual(service['Environment'], [
                    'PATH=/run/current-system/sw/bin:/run/wrappers/bin',
                    'FLATPAK_SANDBOX_DIR=/run/assbox-managed-chromium'])
                self.assertEqual(service['Restart'], 'on-failure')
                self.assertEqual(service['ExitType'], 'main')
                self.assertEqual(service['KillMode'], 'control-group')
                self.assertIn('/inert/chromium', result['packages'])
        for mode in ('headless', 'x11', 'wayland'):
            with self.subTest(unselected=mode):
                result = self.evaluate(mode, [])
                self.assertNotIn('assbox-openclaw-ui', result['services'])
                self.assertNotIn('/inert/chromium', result['packages'])

    def test_openclaw_gateway_recovers_successful_supervisor_handoffs(self):
        for mode in ('headless', 'x11', 'wayland'):
            with self.subTest(mode=mode):
                result = self.evaluate(mode, [] if mode == 'headless' else ['openclaw-dashboard'])
                services = result['services']
                gateway = services['assbox-openclaw']['serviceConfig']
                self.assertEqual(gateway['Restart'], 'always')
                self.assertEqual(gateway['RestartSec'], 5)
                self.assertEqual(gateway['RestartSteps'], 5)
                self.assertEqual(gateway['RestartMaxDelaySec'], 60)
                self.assertEqual(gateway['KillMode'], 'control-group')
                self.assertEqual(services['assbox-opencode']['serviceConfig']['Restart'], 'on-failure')
                if mode != 'headless':
                    self.assertEqual(services['assbox-openclaw-ui']['serviceConfig']['Restart'], 'on-failure')

    def test_opencode_server_and_frontend_share_the_credential_loader(self):
        for mode in ('headless', 'x11', 'wayland'):
            with self.subTest(mode=mode):
                result = self.evaluate(mode, [] if mode == 'headless' else ['opencode-attach'])
                services = result['services']
                backend = services['assbox-opencode']['serviceConfig']
                self.assertEqual(backend['ExecStart'], '/inert/assbox/bin/assbox internal opencode serve')
                self.assertNotIn('EnvironmentFile', backend)
                if mode != 'headless':
                    frontend = services['assbox-opencode-ui']['serviceConfig']
                    self.assertTrue(frontend['ExecStart'].endswith('/inert/assbox/bin/assbox internal opencode attach'))
                    self.assertNotIn('EnvironmentFile', frontend)

    def test_real_application_driver_renders_for_both_architectures(self):
        if not self.lib:
            self.skipTest('Nix module library unavailable; run in the development shell')
        for arm in ('true', 'false'):
            for application in ('chatgpt', 'opencode', 'openclaw'):
                expression = '''let
                  spec = import %s/tests/nix/application-vm.nix {
                    module = null;
                    application = "%s";
                    pkgs = { lib = import %s; stdenv.hostPlatform.isAarch64 = %s;
                             testers.runNixOSTest = spec: spec; };
                  };
                in spec.testScript''' % (ROOT, application, self.lib, arm)
                result = subprocess.run(['nix-instantiate', '--eval', '--strict', '--json', '--expr', expression],
                                        capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode, 0, result.stderr)
                ast.parse(json.loads(result.stdout))

    def test_application_driver_queues_every_reboot_with_pid_one(self):
        for relative in [
                'tests/nix/application-vm.nix',
                'tests/nix/desktop-services-vm.nix']:
            with self.subTest(source=relative):
                source = (ROOT / relative).read_text()
                self.assertGreater(source.count('machine.reboot()'), 0)
                self.assertEqual(
                    source.count('machine.reboot()'),
                    source.count(
                        'machine.succeed("systemctl reboot --no-block")'))


if __name__ == '__main__':
    unittest.main()
