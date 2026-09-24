# SPDX-License-Identifier: GPL-3.0-or-later
"""Exercise the actual seed tree under the production service's restrictive umask."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from test_worker import w


class SeedPermissions(unittest.TestCase):
    def test_service_umask_does_not_hide_authorized_keys(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d) / 'contents'
            previous = os.umask(0o077)
            try:
                w.seed_contents(root, 'public-client', 'public-health', b'private-host')
            finally:
                os.umask(previous)
            for name, expected in [('', 0o755), ('agent.pub', 0o644),
                                   ('assbox-health.pub', 0o644), ('ssh_host_ed25519_key', 0o600)]:
                self.assertEqual((root / name).stat().st_mode & 0o7777, expected)
            self.assertEqual((root / 'assbox-health.pub').read_text(), 'restrict public-health\n')
            self.assertFalse((root / 'client_ed25519').exists())
            xorriso = shutil.which('xorriso')
            if xorriso:
                iso = Path(d) / 'seed.iso'
                subprocess.run([xorriso, '-as', 'mkisofs', '-quiet', '-R', '-o', str(iso), str(root)],
                               check=True, capture_output=True)
                listing = subprocess.run([xorriso, '-indev', str(iso), '-find', '/', '-exec', 'lsdl', '--'],
                                         check=True, capture_output=True, text=True).stdout
                for mode, name in [('drwxr-xr-x', '/'), ('-rw-r--r--', '/agent.pub'),
                                   ('-rw-r--r--', '/assbox-health.pub'), ('-rw-------', '/ssh_host_ed25519_key')]:
                    self.assertTrue(any(line.startswith(mode) and line.endswith("'" + name + "'")
                                        for line in listing.splitlines()), listing)
