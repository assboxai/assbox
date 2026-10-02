# SPDX-License-Identifier: GPL-3.0-or-later
"""Small lease protocol fixtures; no real display, VM or provider session."""
import importlib.util
import ast
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import test_component_catalog as catalog_tests

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('assbox_desktop', ROOT / 'scripts/computer-use/desktop.py')
desktop = importlib.util.module_from_spec(spec)
spec.loader.exec_module(desktop)


class ComputerUseTests(unittest.TestCase):
    def test_substrate_vm_driver_is_syntactically_valid_and_required(self):
        catalog_tests.ComponentCatalogTests.setUpClass()
        lib=catalog_tests.ComponentCatalogTests.lib
        if not lib:self.skipTest('cached Nix module library unavailable')
        expression='''let spec = import %s/tests/nix/computer-use-vm.nix {
          module = null;
          pkgs = { lib = import %s; stdenv.hostPlatform.isAarch64 = true;
                   python3 = "/inert/python"; xdotool = "/inert/xdotool";
                   ffmpeg = "/inert/ffmpeg"; xorg.xmessage = "/inert/xmessage";
                   testers.runNixOSTest = value: value; };
        }; in spec.testScript''' % (ROOT,lib)
        result=subprocess.run(['nix-instantiate','--eval','--strict','--json','--expr',expression],
                              capture_output=True,text=True,timeout=15,check=True)
        import json
        ast.parse(json.loads(result.stdout))
        ast.parse((ROOT/'tests/fixtures/computer_resource.py').read_text())
        self.assertIn('computer-use-vm',(ROOT/'scripts/release-check').read_text())
        self.assertIn('computer-use-vm = import ./tests/nix/computer-use-vm.nix',(ROOT/'flake.nix').read_text())

    def test_chromium_profile_and_listener_cannot_be_replaced_by_caller(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            argv=desktop.chromium_command(['--remote-debugging-port=0','about:blank'],
                                         '/pinned/chromium',root/'browser',root/'cache')
            self.assertEqual(argv[0],'/pinned/chromium')
            self.assertIn('--user-data-dir='+str(root/'browser'),argv)
            self.assertIn('--remote-debugging-address=127.0.0.1',argv)
            self.assertNotIn('--no-sandbox',argv)
            for override in ['--user-data-dir=/personal','--no-sandbox','--disable-setuid-sandbox',
                             '--remote-debugging-address=0.0.0.0','--headless=false',
                             '--remote-debugging-port=-1','--remote-debugging-port=65536']:
                with self.subTest(override=override),self.assertRaises(desktop.Refusal):
                    desktop.chromium_command([override],'/pinned/chromium',root/'browser',root/'cache')

    def address_fixture(self, output):
        process = subprocess.Popen(
            [sys.executable, '-c', 'import sys,time;sys.stdout.write(sys.argv[1]);sys.stdout.flush();time.sleep(60)', output],
            start_new_session=True, stdout=subprocess.PIPE)
        try:
            return desktop.bus_address(process, lambda: False)
        finally:
            desktop.cleanup([process])
            self.assertIsNotNone(process.returncode)
            self.assertTrue(process.stdout.closed)

    def test_bus_readiness_uses_a_private_bounded_address(self):
        self.assertEqual(self.address_fixture('unix:path=/private/bus,guid=fixture\n'),
                         'unix:path=/private/bus,guid=fixture')
        for output in ('tcp:host=127.0.0.1,port=1\n', 'unix:bad\x01\n', 'x' * 4097):
            with self.subTest(output=output[:20]), self.assertRaises(desktop.Refusal):
                self.address_fixture(output)

    def test_cancelled_bus_readiness_fails_without_waiting(self):
        with self.assertRaises(desktop.Refusal):
            desktop.bus_address(None, lambda: True)

    def test_browser_selection_cannot_launch_a_desktop(self):
        with patch.object(desktop.os, 'geteuid', return_value=1000):
            with self.assertRaisesRegex(desktop.Refusal, 'not selected'):
                desktop.run('display', ['true'], {'modes': ['browser']})

    def test_physical_session_and_agent_socket_are_scrubbed(self):
        with patch.dict(desktop.os.environ, {'DISPLAY': ':0', 'DBUS_SESSION_BUS_ADDRESS': 'sensitive',
                                           'SSH_AUTH_SOCK': '/sensitive', 'KEEP': 'value'}, clear=True):
            self.assertEqual(desktop.clean_environment(), {'KEEP': 'value'})


if __name__ == '__main__':
    unittest.main()
