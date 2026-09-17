# SPDX-License-Identifier: GPL-3.0-or-later
"""Desktop policy and VM-driver syntax; actual dialogs require the native VM gate."""
import ast
import json
import subprocess
import unittest
from pathlib import Path

import test_component_catalog as catalog_tests

ROOT = Path(__file__).resolve().parents[2]


class DesktopServicesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        catalog_tests.ComponentCatalogTests.setUpClass()
        cls.lib = catalog_tests.ComponentCatalogTests.lib

    def evaluate(self, presentation):
        if not self.lib:
            self.skipTest('Nix module library unavailable; run in the development shell')
        result = subprocess.run([
            'nix-instantiate', '--eval', '--strict', '--json',
            'tests/nix/presentation-eval.nix', '--arg', 'libPath', self.lib,
            '--argstr', 'presentation', presentation,
        ], cwd=ROOT, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_portal_selection_matches_the_actual_desktop(self):
        for mode, desktop, backends in [('x11', 'openbox', ['gtk']),
                                         ('wayland', 'labwc', ['wlr', 'gtk'])]:
            with self.subTest(mode=mode):
                config = self.evaluate(mode)
                self.assertTrue(config['xdg']['portal']['enable'])
                self.assertEqual(config['xdg']['portal']['config'][desktop]['default'], backends)
                if mode == 'x11':
                    self.assertIn('/inert/xdg-desktop-portal-gtk', config['xdg']['portal']['extraPortals'])
        self.assertEqual(self.evaluate('headless')['xdg'], {})

    def test_keyring_is_enabled_only_for_headed_sessions(self):
        for mode, desktop in [('x11', 'openbox'), ('wayland', 'labwc')]:
            with self.subTest(mode=mode):
                config = self.evaluate(mode)
                self.assertTrue(config['services']['gnome']['gnome-keyring']['enable'])
                self.assertEqual(config['xdg']['portal']['config'][desktop]
                                 ['org.freedesktop.impl.portal.Secret'], ['gnome-keyring'])
        self.assertEqual(self.evaluate('headless')['services'], {})

    def test_desktop_gate_renders_valid_driver_and_is_required(self):
        if not self.lib:
            self.skipTest('Nix module library unavailable; run in the development shell')
        expression = '''let
          lib = import %s;
          spec = import %s/tests/nix/desktop-services-vm.nix {
            module = null;
            pkgs = { inherit lib; stdenv.hostPlatform.isAarch64 = true;
                     python3.withPackages = _: "/inert/python";
                     testers.runNixOSTest = spec: spec; };
          };
        in spec.testScript''' % (self.lib, ROOT)
        result = subprocess.run(['nix-instantiate', '--eval', '--strict', '--json', '--expr', expression],
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        ast.parse(json.loads(result.stdout))
        ast.parse((ROOT / 'tests/fixtures/portal-probe.py').read_text())
        self.assertIn('desktop-services-vm', (ROOT / 'scripts/release-check').read_text())
        self.assertIn('desktop-services-vm = import ./tests/nix/desktop-services-vm.nix', (ROOT / 'flake.nix').read_text())

    def test_editor_gate_renders_language_server_probe_on_both_architectures(self):
        if not self.lib:
            self.skipTest('Nix module library unavailable; run in the development shell')
        for arm in ['true', 'false']:
            expression = '''let
              spec = import %s/tests/nix/editor-vm.nix {
                module = null;
                pkgs = { stdenv.hostPlatform.isAarch64 = %s;
                         python3 = "/inert/python"; patchelf = "/inert/patchelf";
                         rust-analyzer-unwrapped = "/inert/rust-analyzer";
                         runCommand = name: _: script: builtins.seq (builtins.stringLength script) ("/inert/" + name);
                         testers.runNixOSTest = spec: spec; };
              };
            in spec.testScript''' % (ROOT, arm)
            result = subprocess.run(['nix-instantiate', '--eval', '--strict', '--json', '--expr', expression],
                                    capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            ast.parse(json.loads(result.stdout))
        ast.parse((ROOT / 'tests/fixtures/lsp-probe.py').read_text())


if __name__ == '__main__':
    unittest.main()
