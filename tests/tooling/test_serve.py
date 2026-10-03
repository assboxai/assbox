# SPDX-License-Identifier: GPL-3.0-or-later
"""Serve contract checks without enrollment, sockets or privileged mutation."""
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('assbox_serve',ROOT/'scripts/access/serve.py')
serve=importlib.util.module_from_spec(spec)
spec.loader.exec_module(serve)

class ServeTests(unittest.TestCase):
    def test_missing_backend_refuses_before_external_mutation(self):
        with patch.object(serve.subprocess,'run',side_effect=AssertionError('must not invoke control')):
            with self.assertRaisesRegex(serve.Refusal,'before deselecting'):
                serve.command(None,'serve','status','--json')

if __name__=='__main__':unittest.main()
