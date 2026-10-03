# SPDX-License-Identifier: GPL-3.0-or-later
"""Keep disposable password boundaries exact and concealment mandatory."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import runpy
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]


class PasswordFixtureContract(unittest.TestCase):
    def canonical(self, args):
        spec = importlib.util.spec_from_file_location("password_transport", ROOT / "tests/fixtures/installer_cli_transport.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module.dispatch("systemd-ask-password", args, {})

    def legacy(self, args):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "case.json").write_text(json.dumps({}))
            original_path = Path
            def fixture_path(value):
                return root if value == "/var/lib/assbox-acceptance" else original_path(value)
            with mock.patch("pathlib.Path", side_effect=fixture_path), mock.patch.object(
                    sys, "argv", ["release_transport.py", "systemd-ask-password", *args]), mock.patch.dict(
                    "os.environ", {}, clear=True), contextlib.redirect_stdout(io.StringIO()) as output:
                runpy.run_path(str(ROOT / "tests/fixtures/release_transport.py"), run_name="__main__")
            calls = [json.loads(line) for line in (root / "calls.jsonl").read_text().splitlines()]
            self.assertEqual(calls, [["systemd-ask-password", *args]])
            return output.getvalue().strip()

    def test_both_administrator_requests_are_accepted_with_hidden_echo(self):
        for prompt in ("Choose an administrator password:", "Repeat the administrator password:"):
            for adapter in (self.canonical, self.legacy):
                with self.subTest(prompt=prompt, adapter=adapter.__name__):
                    self.assertGreaterEqual(len(adapter(["--echo=no", prompt])), 12)

    def test_unmasked_unknown_and_extra_requests_are_refused(self):
        prompt = "Choose an administrator password:"
        for args in ([prompt], ["--echo=yes", prompt], ["--echo=no", "other"], ["--echo=no", prompt, "extra"]):
            for adapter in (self.canonical, self.legacy):
                with self.subTest(args=args, adapter=adapter.__name__):
                    with self.assertRaises((ValueError, AssertionError)):
                        adapter(args)


if __name__ == "__main__":
    unittest.main()
