# SPDX-License-Identifier: GPL-3.0-or-later
"""Device policy evaluation; real kernel/seat access is covered by radio-policy-vm."""
import ast
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

import test_component_catalog as catalog_tests

ROOT = Path(__file__).resolve().parents[2]


class DevicePolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        catalog_tests.ComponentCatalogTests.setUpClass()
        cls.lib = catalog_tests.ComponentCatalogTests.lib

    def evaluate(self, wifi):
        if not self.lib:
            self.skipTest('Nix module library unavailable; run in the development shell')
        result = subprocess.run([
            'nix-instantiate', '--eval', '--strict', '--json',
            'tests/nix/device-policy-eval.nix', '--arg', 'libPath', self.lib,
            '--arg', 'wifi', str(wifi).lower(),
        ], cwd=ROOT, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_radio_control_stays_administrative_with_wifi_on_or_off(self):
        for wifi in (False, True):
            with self.subTest(wifi=wifi):
                value = self.evaluate(wifi)
                policy = value['rules'][0]
                self.assertEqual(policy['path'], 'lib/udev/rules.d/72-assbox-policy.rules')
                rule = next(line for line in policy['text'].splitlines() if 'KERNEL=="rfkill"' in line)
                for part in ('SUBSYSTEM=="misc"', 'TAG-="uaccess"', 'OWNER="root"',
                             'GROUP="root"', 'MODE="0600"'):
                    self.assertIn(part, rule)
                self.assertEqual('rfkill block wlan' in policy['text'], not wifi)
                self.assertEqual(value['unmanaged'], [] if wifi else ['type:wifi'])
                self.assertIn('/bin/nmcli radio wifi ' + ('on' if wifi else 'off'), value['radioStartup'])
                self.assertEqual('/bin/rfkill block wlan' in value['radioStartup'], not wifi)
                if wifi:
                    self.assertIsNone(value['radioHotplug'])
                else:
                    hotplug = value['radioHotplug']
                    self.assertEqual(hotplug['requires'], ['NetworkManager.service'])
                    self.assertEqual(hotplug['after'], ['NetworkManager.service'])
                    self.assertEqual(hotplug['serviceConfig']['Type'], 'oneshot')
                    self.assertIn('/bin/nmcli radio wifi off', hotplug['script'])
                    self.assertIn('/bin/rfkill block wlan', hotplug['script'])
                    self.assertIn('ENV{SYSTEMD_WANTS}+="assbox-radio-hotplug.service"',
                                  policy['text'])
                self.assertEqual(value['radioInput']['tristate'], 'n')
                self.assertFalse(value['radioInput']['optional'])

    def test_radio_startup_handles_missing_node_and_propagates_failure(self):
        # Execute the actual rendered postStart with fake command effects. This
        # checks shell ordering/error handling, not NetworkManager or the kernel.
        script = self.evaluate(False)['radioStartup']
        with tempfile.TemporaryDirectory(prefix='assbox-radio-test-') as directory:
            directory = Path(directory)
            log = directory / 'events'
            for name in ('nmcli', 'rfkill'):
                tool = directory / name
                tool.write_text('#!/bin/sh\nprintf "%s\\n" "' + name + ' $*" >> "$ASSBOX_TEST_LOG"\n' +
                                ('exit "${ASSBOX_TEST_NM_EXIT:-0}"\n' if name == 'nmcli' else 'exit 0\n'))
                tool.chmod(0o755)
                prefix = 'networkmanager' if name == 'nmcli' else 'util-linux'
                script = script.replace('/inert/' + prefix + '/bin/' + name, str(tool))
            for node in (str(directory / 'absent'), '/dev/null'):
                for status in (0, 7):
                    with self.subTest(node=node, nmcli_status=status):
                        log.write_text('')
                        env = dict(os.environ, ASSBOX_TEST_LOG=str(log), ASSBOX_TEST_NM_EXIT=str(status))
                        result = subprocess.run(['bash', '-e', '-c', script.replace('/dev/rfkill', node)],
                                                env=env, capture_output=True, text=True, timeout=5)
                        self.assertEqual(result.returncode, status, result.stderr)
                        expected = ['nmcli radio wifi off']
                        if not status and node == '/dev/null':
                            expected.append('rfkill block wlan')
                        self.assertEqual(log.read_text().splitlines(), expected)

    def test_radio_gate_renders_valid_driver_and_permission_probe(self):
        if not self.lib:
            self.skipTest('Nix module library unavailable; run in the development shell')
        expression = '''let
          lib = import %s;
          spec = import %s/tests/nix/radio-policy-vm.nix {
            module = null;
            pkgs = { inherit lib; stdenv.hostPlatform.isAarch64 = true;
                     testers.runNixOSTest = spec: spec; };
          };
        in spec.testScript''' % (self.lib, ROOT)
        result = subprocess.run(['nix-instantiate', '--eval', '--strict', '--json', '--expr', expression],
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        tree = ast.parse(json.loads(result.stdout))
        probes = [node.value.value for node in ast.walk(tree) if isinstance(node, ast.Assign)
                  and any(isinstance(t, ast.Name) and t.id == 'probe' for t in node.targets)]
        self.assertEqual(len(probes), 1)
        ast.parse(probes[0])
        self.assertIn('radio-policy-vm', (ROOT / 'scripts/release-check').read_text())
        self.assertIn('radio-policy-vm = import ./tests/nix/radio-policy-vm.nix', (ROOT / 'flake.nix').read_text())


if __name__ == '__main__':
    unittest.main()
