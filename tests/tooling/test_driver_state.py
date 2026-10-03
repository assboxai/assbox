# SPDX-License-Identifier: GPL-3.0-or-later
import json
import os
from pathlib import Path
import shutil
import socket
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts'))
import repair_loop


class DriverStateTests(unittest.TestCase):
    def test_long_evidence_paths_use_fresh_short_physical_socket_state(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary) / ('long-evidence-' * 15)
            base.mkdir()
            roots = []
            try:
                for number in range(2):
                    run = base / str(number); run.mkdir()
                    state = repair_loop.fresh_driver_state(run); roots.append(state)
                    self.assertFalse(state.is_symlink())
                    self.assertEqual(state.resolve(), state)
                    self.assertEqual(state.stat().st_uid, os.getuid())
                    self.assertEqual(state.stat().st_mode & 0o777, 0o700)
                    record = json.loads((run / 'driver-state.json').read_text())
                    self.assertEqual(record['path'], str(state))
                    self.assertTrue(record['fresh'])
                    machine = state / 'vm-state-installer'; machine.mkdir()
                    address = machine / 'monitor'
                    self.assertLess(len(os.fsencode(address)), 100)
                    with socket.socket(socket.AF_UNIX) as server:
                        server.bind(str(address)); server.listen(1)
                        with socket.socket(socket.AF_UNIX) as client:
                            client.connect(str(address))
                            accepted, unused = server.accept(); accepted.close()
                    environment = repair_loop.environment(run, state)
                    self.assertEqual(environment['XDG_RUNTIME_DIR'], str(state))
                    self.assertEqual(environment['HOME'], str(run / 'home'))
                self.assertNotEqual(roots[0], roots[1])
            finally:
                for state in roots:
                    shutil.rmtree(state)

    def test_volatile_storage_refuses_before_allocating_driver_state(self):
        with mock.patch.object(Path, 'read_text', return_value='1 0 0:1 / /var/tmp rw - tmpfs tmpfs rw\n'), \
                mock.patch.object(tempfile, 'mkdtemp') as allocate:
            with self.assertRaisesRegex(ValueError, 'persistent storage'):
                repair_loop.fresh_driver_state(Path('/unused-run'))
            allocate.assert_not_called()


if __name__ == '__main__':
    unittest.main()
