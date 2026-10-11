# SPDX-License-Identifier: GPL-3.0-or-later
"""Evaluate the real family fixture without building or dispatching its VM."""
import json
import os
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[2]


class FamilySelection(unittest.TestCase):
    def test_dashboard_configuration_preserves_every_enabled_family_member(self):
        library = os.environ["ASSBOX_NIX_LIB"]
        expression = """
          let
            lib = import (builtins.toPath %s);
            catalog = builtins.fromJSON (builtins.readFile %s);
            families = lib.unique (map (row: row.family) catalog);
            observe = family:
              let
                expected = map (row: row.id)
                  (builtins.filter (row: row.family == family && row.blocked == "") catalog);
                fixture = import %s {
                  inherit family;
                  module = {};
                  pkgs = { inherit lib; stdenv.hostPlatform.isAarch64 = false;
                    testers.runNixOSTest = definition: definition; };
                };
                node = fixture.nodes.machine { inherit lib; };
                enabled = builtins.filter (id: node.assbox.components.${id}.enable or false)
                  (builtins.attrNames node.assbox.components);
              in { inherit family expected enabled; };
          in map observe families
        """ % (json.dumps(library), json.dumps(str(ROOT / "catalog/components.json")),
                json.dumps(str(ROOT / "tests/nix/component-family-vm.nix")))
        result = subprocess.run(["nix", "eval", "--impure", "--json", "--expr", expression],
                                cwd=ROOT, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        observations = json.loads(result.stdout)
        self.assertTrue(any(row["family"] == "hermes" for row in observations))
        for row in observations:
            with self.subTest(family=row["family"]):
                self.assertEqual(sorted(row["enabled"]), sorted(row["expected"]))


if __name__ == "__main__":
    unittest.main()
