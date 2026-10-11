# SPDX-License-Identifier: GPL-3.0-or-later
"""The generated VM trust module must work in a different, pure flake."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


class FixtureCertificateTests(unittest.TestCase):
    def test_generated_trust_survives_pure_flake_boundary(self):
        nix = shutil.which("nix")
        self.assertIsNotNone(nix, "the pinned development environment provides Nix")
        environment = {
            key: value
            for key, value in os.environ.items()
            if key in ("PATH", "HOME", "LANG", "LC_ALL", "SSL_CERT_FILE", "NIX_SSL_CERT_FILE")
        }
        environment.update(NIX_USER_CONF_FILES="/dev/null", GIT_CONFIG_NOSYSTEM="1",
                           GIT_CONFIG_GLOBAL="/dev/null", GIT_CONFIG_COUNT="0")
        certificate = ROOT / "tests/fixtures/mirror-cert.crt"
        expected = certificate.read_bytes()
        with tempfile.TemporaryDirectory(prefix="assbox-pure-certificate-") as directory:
            root = Path(directory)
            # Match the failing VM: a valid public certificate in the store but
            # outside the newly generated machine flake's declared inputs.
            added = subprocess.run(
                [nix, "store", "add-file", str(certificate)],
                env=environment, capture_output=True, check=True, timeout=30,
            )
            stored = added.stdout.decode().strip()
            self.assertTrue(stored.startswith("/nix/store/"))
            (root / "flake.nix").write_text(
                '{ outputs = _: { certificate = let trust = import ./local.nix; in '
                'if trust.security.pki ? certificates then '
                'builtins.head trust.security.pki.certificates else '
                'builtins.readFile (builtins.head trust.security.pki.certificateFiles); }; }\n'
            )
            (root / "local.nix").write_text(
                "{ security.pki.certificateFiles = [ " + stored + " ]; }\n"
            )
            command = [nix, "eval", "--raw", "--no-update-lock-file", "--no-write-lock-file",
                       "path:" + str(root) + "#certificate"]
            before = subprocess.run(command, env=environment, capture_output=True, timeout=30)
            self.assertNotEqual(before.returncode, 0)
            self.assertIn(b"forbidden in pure evaluation mode", before.stderr)
            rendered = subprocess.run(
                [nix, "eval", "--impure", "--raw", "--expr",
                 "import " + str(ROOT / "tests/nix/fixture-certificate.nix")
                 + " { certificate = " + stored + "; }"],
                env=environment, capture_output=True, check=True, timeout=30,
            ).stdout.decode()
            (root / "local.nix").write_text("{ " + rendered + " }\n")
            after = subprocess.run(command, env=environment, capture_output=True, timeout=30)
            self.assertEqual(after.returncode, 0, after.stderr.decode())
            self.assertEqual(after.stdout, expected)
            self.assertNotIn("--impure", command)
            self.assertNotIn("/nix/store/", rendered)



if __name__ == "__main__":
    unittest.main()
