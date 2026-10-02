# SPDX-License-Identifier: GPL-3.0-or-later
"""Small lease protocol fixtures; no real display, VM or provider session."""
import importlib.util
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('assbox_desktop', ROOT / 'scripts/computer-use/desktop.py')
desktop = importlib.util.module_from_spec(spec)
spec.loader.exec_module(desktop)


class ComputerUseTests(unittest.TestCase):
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
