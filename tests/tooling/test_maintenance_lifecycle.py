# SPDX-License-Identifier: GPL-3.0-or-later
"""Boot-check configuration; real target/activation behavior is a VM gate."""
import ast
import json
from pathlib import Path
import subprocess
import textwrap
import unittest

import test_component_catalog as catalog_tests

ROOT = Path(__file__).resolve().parents[2]


class MaintenanceLifecycleTests(unittest.TestCase):
    def test_boot_check_has_only_a_boot_timer_owner(self):
        catalog_tests.ComponentCatalogTests.setUpClass()
        lib = catalog_tests.ComponentCatalogTests.lib
        if not lib:
            self.skipTest('Nix module library unavailable; run in the development shell')
        for enabled in (True, False):
            with self.subTest(enabled=enabled):
                result = subprocess.run(['nix-instantiate', '--eval', '--strict', '--json',
                    'tests/nix/maintenance-eval.nix', '--arg', 'libPath', lib,
                    '--arg', 'bootCheckEnabled', str(enabled).lower()],
                    cwd=ROOT, text=True, capture_output=True, timeout=30)
                self.assertEqual(result.returncode, 0, result.stderr)
                units = json.loads(result.stdout)
                self.assertEqual(units['services']['assbox-boot-check'].get('wantedBy', []), [])
                timer = units['timers']['assbox-boot-check']
                self.assertEqual(timer['enable'], enabled)
                self.assertEqual(timer['timerConfig'], {'OnBootSec': '1s', 'RemainAfterElapse': True})
                self.assertEqual(timer['wantedBy'], ['timers.target'])

    def test_management_driver_and_activation_cases_parse(self):
        ast.parse((ROOT / 'tests/fixtures/activation_cases.py').read_text())
        source = (ROOT / 'tests/nix/management-vm.nix').read_text()
        script = source.split("testScript = ''", 1)[1].rsplit("'';", 1)[0]
        for name in ('foreign', 'maintenancePolicy'):
            script = script.replace('${' + name + '}', '/inert/' + name)
        ast.parse(textwrap.dedent(script))


if __name__ == '__main__':
    unittest.main()
