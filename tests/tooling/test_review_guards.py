# SPDX-License-Identifier: GPL-3.0-or-later
"""Source contracts plus execution of the actual boot-receipt jq decoder.

These checks complement, not replace, native Rust and Nix execution.
"""
from __future__ import annotations
import copy
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))


class ReviewGuards(unittest.TestCase):
    def test_prepared_root_validation_uses_observation_before_writes(self):
        text = (ROOT / "crates/imperative-shell/assbox-engine/src/install.rs").read_text()
        boundary = text.index("// FIRST TARGET WRITE")
        self.assertEqual(text.count("validate_prepared_root(&files::prepared_root_entries"), 2)
        self.assertNotIn("validate_prepared_root", text[boundary:])
        observation = (ROOT / "crates/imperative-shell/assbox-system/src/files.rs").read_text()
        observation = observation[observation.index("pub fn prepared_root_entries"):]
        self.assertIn("symlink_metadata", observation)
        self.assertIn('name == "lost+found" && metadata.is_dir()', observation)
        self.assertRegex(observation, r"\.next\(\)\s*\.transpose\(\)")
        self.assertNotIn("remove", observation)

    def test_boot_decoder_separates_policy_from_binding_and_rejects_old_schema(self):
        source = (ROOT / "crates/imperative-shell/assbox-engine/src/boot_guard.rs").read_text()
        decoder = re.search(r'r#"(if \.schema != 2.*?end)"#', source, re.S).group(1)
        receipt = {
            "schema": 2,
            "binding": {"architecture": "aarch64", "mode": "uefi", "platform": "generic",
                        "disk": "disk-id", "rootDevice": "root-id", "espDevice": "esp-id",
                        "loader": {"systemdBoot": True, "efiCanTouch": True}},
            "policy": {"generations": 8},
        }
        def decode(value):
            return subprocess.run(["jq", "-j", decoder], input=json.dumps(value),
                                  capture_output=True, text=True, check=False)
        first = decode(receipt)
        self.assertEqual(first.returncode, 0, first.stderr)
        fields = first.stdout.rstrip("\0").split("\0")
        self.assertEqual(len(fields), 8)
        self.assertEqual(fields[-1], "8")
        changed = copy.deepcopy(receipt)
        changed["policy"]["generations"] = 16
        result = decode(changed)
        second = result.stdout.rstrip("\0").split("\0")
        self.assertEqual(second[:-1], fields[:-1])
        self.assertEqual(second[-1], "16")
        for change in ["old-schema", "missing-loader", "missing-policy", "string-limit"]:
            invalid = copy.deepcopy(receipt)
            if change == "old-schema": invalid["schema"] = 1
            elif change == "missing-loader": del invalid["binding"]["loader"]
            elif change == "missing-policy": del invalid["policy"]
            else: invalid["policy"]["generations"] = "8"
            self.assertNotEqual(decode(invalid).returncode, 0, change)

    def test_boot_receipt_producer_has_no_mutable_limit_in_binding(self):
        nix = (ROOT / "modules/generation.nix").read_text()
        self.assertIn("schema = 2", nix)
        self.assertIn("binding = {", nix)
        self.assertIn("policy.generations", nix)
        self.assertNotIn("systemdLimit", nix)
        self.assertNotIn("grubLimit", nix)
        policy = (ROOT / "crates/functional-core/assbox-policy/src/lib.rs").read_text()
        self.assertIn("current.binding != target.binding", policy)
        self.assertIn("(2..=32).contains(&target.policy.generations)", policy)

    def test_disk_summary_contains_whole_disk_identity_and_confirmation(self):
        probe = (ROOT / "crates/imperative-shell/assbox-system/src/probe.rs").read_text()
        self.assertIn("MOUNTPOINTS,MODEL", probe)
        self.assertRegex(probe, r"model:\s*f\[13\]")
        ui = (ROOT / "crates/imperative-shell/assbox-cli/src/wizard.rs").read_text()
        self.assertIn("confirmation_phrase(&plan)", ui)
        self.assertEqual(ui.count("plan_storage_summary(&plan)"), 2)
        self.assertLess(ui.index("plan.revalidate(&probe::inventory"), ui.index("confirmation_phrase(&plan)"))

    def test_browser_dependency_and_consent_are_narrow(self):
        apps = (ROOT / "modules/applications.nix").read_text()
        self.assertIn('launch "openclaw-dashboard"', apps)
        self.assertNotIn('builtins.elem cfg.application [ "opencode" "openclaw" ]', apps)
        main = (ROOT / "crates/imperative-shell/assbox-cli/src/main.rs").read_text()
        self.assertIn('["component","set",app,presentation,"--accept-unfree"]', re.sub(r"\s+", "", main))
        engine = (ROOT / "crates/imperative-shell/assbox-engine/src/manage.rs").read_text()
        selection = engine[engine.index("pub fn components_set"):engine.index("pub fn rollback")]
        self.assertLess(selection.index("validate_component_selection"), selection.index("begin()?"))
        self.assertEqual(selection.count("validate_component_selection"), 2)
        self.assertLess(selection.rindex("validate_component_selection"), selection.index("build(&Commands)"))

    def run_acceptance_presence_gate(self, names):
        # Run the delivered shell gate with explicitly fake Nix discovery and a
        # sentinel verifier. This is NOT VM execution or a passing release gate.
        with tempfile.TemporaryDirectory(prefix="assbox-gate-test-") as temporary:
            directory = Path(temporary)
            tools, candidate = directory / "tools", directory / "candidate"
            tools.mkdir(); candidate.mkdir(); (candidate / "scripts").mkdir()
            (candidate / "release-context.json").write_text("{}\n")
            for name in ['component_families.py', 'release.py', 'release_data.py']:
                (candidate / 'scripts' / name).write_bytes((ROOT / 'scripts' / name).read_bytes())
            from test_release_data import lock
            locked = lock()
            (candidate / 'flake.lock').write_text(json.dumps(locked))
            nix = tools / "nix"
            nix.write_text("#!/usr/bin/env bash\nset -eu\n"
                "if [[ \"$*\" == *builtins.currentSystem* ]]; then printf x86_64-linux; "
                "elif [[ \"$1 $2\" == 'flake metadata' ]]; then printf '%s' \"$ASSBOX_TEST_METADATA\"; "
                "else printf '%s' \"$ASSBOX_TEST_CHECK_NAMES\"; fi\n")
            nix.chmod(0o755)
            verifier = candidate / "scripts/verify"
            verifier.write_text("#!/usr/bin/env bash\nprintf reached > verification-reached\nexit 73\n")
            verifier.chmod(0o755)
            env = dict(os.environ, PATH=str(tools) + os.pathsep + os.environ["PATH"],
                       ASSBOX_TEST_CHECK_NAMES=json.dumps(names), ASSBOX_TEST_METADATA=json.dumps({'locks': locked}))
            result = subprocess.run(["bash", str(ROOT / "scripts/release-check"), "--candidate", str(candidate)],
                                    env=env, capture_output=True, text=True, check=False, timeout=10)
            return result, (candidate / "verification-reached").exists()

    @staticmethod
    def required_acceptance_names():
        required = ["worker-tools", "worker-policy", "worker-artifact", "worker-boot-gate-vm", "worker-sshd-policy-vm", "worker-network-vm", "worker-lifecycle-vm", "remote-lifecycle-vm", "editor-vm", "desktop-services-vm", "radio-policy-vm", "access-lan-vm", "access-tailscale-vm", "install-boot-vm", "activation-recovery-vm", "authenticated-release-vm",
                    "application-chatgpt-vm", "application-opencode-vm", "application-openclaw-vm"]
        required.append("computer-use-vm")
        required += ["application-" + family + "-vm" for family in __import__("component_families").FAMILIES if "application-" + family + "-vm" not in required]
        return required

    def test_every_required_acceptance_name_is_a_release_prerequisite(self):
        required = self.required_acceptance_names()
        for absent in required:
            with self.subTest(absent=absent):
                result, reached = self.run_acceptance_presence_gate([name for name in required if name != absent])
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertIn(absent, result.stderr)
                self.assertFalse(reached)

    def test_worker_lifecycle_gate_cannot_be_omitted(self):
        required = self.required_acceptance_names()
        result, reached = self.run_acceptance_presence_gate(
            [name for name in required if name != "worker-lifecycle-vm"])
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("worker-lifecycle-vm", result.stderr)
        self.assertFalse(reached)

    def test_implemented_names_proceed_to_verification_not_automatic_approval(self):
        required = self.required_acceptance_names()
        result, reached = self.run_acceptance_presence_gate(required)
        self.assertTrue(reached, result.stderr)
        self.assertEqual(result.returncode, 73, "the subsequent verification failure must propagate")


if __name__ == "__main__":
    unittest.main()
