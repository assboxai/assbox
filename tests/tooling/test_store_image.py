# SPDX-License-Identifier: GPL-3.0-or-later
"""The fixture image adapter must refuse redirects and unsupported calls."""
import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock


SPEC = importlib.util.spec_from_file_location(
    'store_image', Path(__file__).parents[1] / 'fixtures/store_image.py')
IMAGE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(IMAGE)


class StoreImageTests(unittest.TestCase):
    def test_complete_stream_and_real_formatter_arguments(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'store.img'
            result = IMAGE.command('/pinned/mksquashfs', [*IMAGE.PREFIX, str(path)])
            self.assertEqual(result[:4], ['/pinned/mksquashfs', '-', str(path), '-tar'])
            self.assertIn('-no-strip', result)
            self.assertIn('-exit-on-error', result)
            path.touch()
            self.assertEqual(IMAGE.command('/pinned/mksquashfs', [*IMAGE.PREFIX, str(path)]), result)

    def test_redirects_devices_and_aliases_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            path = parent / 'store.img'
            target = parent / 'other'
            target.touch()
            path.symlink_to(target)
            with self.assertRaises(ValueError):
                IMAGE.command('/pinned/mksquashfs', [*IMAGE.PREFIX, str(path)])
            path.unlink()
            os.link(target, path)
            with self.assertRaises(ValueError):
                IMAGE.command('/pinned/mksquashfs', [*IMAGE.PREFIX, str(path)])
            path.unlink()
            path.mkdir()
            with self.assertRaises(ValueError):
                IMAGE.command('/pinned/mksquashfs', [*IMAGE.PREFIX, str(path)])
            with self.assertRaises(ValueError):
                IMAGE.command('/pinned/mksquashfs', [*IMAGE.PREFIX, '/dev/null'])

    def test_changed_interface_and_relative_path_refused(self):
        for arguments in (
                [*IMAGE.PREFIX, 'store.img'],
                [*IMAGE.PREFIX, '/tmp/other.img'],
                ['--unknown', *IMAGE.PREFIX, '/tmp/store.img'],
                [*IMAGE.PREFIX[:-1], '--tar=i', '/tmp/store.img']):
            with self.subTest(arguments=arguments), self.assertRaises(ValueError):
                IMAGE.command('/pinned/mksquashfs', arguments)

    def test_explicit_timestamps_override_nix_source_date_epoch(self):
        with mock.patch.dict(os.environ, {
                'SOURCE_DATE_EPOCH': '123',
                'ASSBOX_FIXTURE_SENTINEL': 'preserved',
        }, clear=True):
            environment = IMAGE.formatter_environment()
        self.assertNotIn('SOURCE_DATE_EPOCH', environment)
        self.assertEqual(environment['ASSBOX_FIXTURE_SENTINEL'], 'preserved')


if __name__ == '__main__':
    unittest.main()
