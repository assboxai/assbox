# SPDX-License-Identifier: GPL-3.0-or-later
import errno
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from test_worker import w, configuration


class SparseStorage(unittest.TestCase):
    def test_new_disk_is_sparse_and_never_reformatted_on_reuse(self):
        with tempfile.TemporaryDirectory() as d:
            disk = Path(d) / 'home.raw'
            with patch.object(w, 'run') as mkfs:
                w.create_state_disk(disk, 8*w.GIB, '/unused-mkfs')
                self.assertEqual(disk.stat().st_size, 8*w.GIB)
                self.assertLess(disk.stat().st_blocks * 512, w.GIB)
                self.assertEqual(disk.stat().st_mode & 0o7777, 0o600)
                with disk.open('r+b') as f: f.write(b'preserve')
                mkfs.reset_mock()
                w.create_state_disk(disk, 8*w.GIB, '/unused-mkfs')
                mkfs.assert_not_called()
                with disk.open('rb') as f: self.assertEqual(f.read(8), b'preserve')

    def test_disk_full_during_creation_leaves_refusal_state(self):
        with tempfile.TemporaryDirectory() as d:
            disk = Path(d) / 'home.raw'
            with patch.object(w.os, 'ftruncate', side_effect=OSError(errno.ENOSPC, 'full')):
                with self.assertRaises(OSError): w.create_state_disk(disk, 8*w.GIB, '/unused')
            self.assertFalse(disk.exists())
            self.assertTrue(disk.with_name('home.raw.new').exists())
            with patch.object(w, 'run') as mkfs:
                with self.assertRaises(FileExistsError): w.create_state_disk(disk, 8*w.GIB, '/unused')
                mkfs.assert_not_called()

    def test_qemu_pauses_on_io_failure_instead_of_restarting_and_reformatting(self):
        with tempfile.TemporaryDirectory() as d:
            c = configuration(); c['artifact'] = d
            (Path(d) / 'cmdline').write_text('root=/dev/vda')
            with patch.object(w, 'artifact_manifest'):
                args = w.qemu_args(c)
            writable = [a for a in args if a.startswith('file=') and 'readonly=on' not in a]
            self.assertEqual(len(writable), 2)
            self.assertTrue(all('werror=stop,rerror=stop' in a for a in writable))
