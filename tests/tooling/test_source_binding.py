# SPDX-License-Identifier: GPL-3.0-or-later
"""Run the actual jq lock adapter; source-order checks are not Rust execution."""
from __future__ import annotations
import copy
import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class SourceBindingTests(unittest.TestCase):
    def metadata(self):
        # Deliberately synthetic values, never a release lock or source receipt.
        return {
            "locked": {"type": "tarball", "url": "https://github.com/assboxai/assbox/releases/download/r-100/assbox-source.tar.gz", "narHash": "sha256-" + "A" * 43 + "="},
            "original": {"type": "tarball", "url": "https://github.com/assboxai/assbox/releases/download/r-100/assbox-source.tar.gz", "narHash": "sha256-" + "A" * 43 + "="},
            "locks": {"version": 7, "root": "upstream", "nodes": {
                "upstream": {"inputs": {"nixpkgs": "np", "tools": "tools"}},
                "np": {"locked": {"type": "github", "rev": "b" * 40}},
                "tools": {"inputs": {"one": ["nixpkgs"], "two": ["tools", "nested"]},
                          "locked": {"rev": "c" * 40}},
            }},
        }

    def transform(self, data, success=True):
        jq = shutil.which("jq")
        self.assertIsNotNone(jq, "jq is required; this adapter test must not be silently skipped")
        result = subprocess.run([jq, "-e", "-S", "--arg", "url", self.metadata()["locked"]["url"],
                                 "--arg", "hash", "sha256-" + "A" * 43 + "=",
                                 "-f", str(ROOT / "nix/machine-lock.jq")],
                                input=json.dumps(data), capture_output=True, text=True, check=False)
        if success:
            self.assertEqual(result.returncode, 0, result.stderr)
            return json.loads(result.stdout)
        self.assertNotEqual(result.returncode, 0)
        return None

    def test_real_lock_adapter_preserves_every_pin_and_rebases_follows(self):
        metadata = self.metadata()
        before = copy.deepcopy(metadata)
        lock = self.transform(metadata)
        self.assertEqual(metadata, before)
        self.assertEqual(lock["root"], "_assbox_machine")
        self.assertEqual(lock["nodes"]["upstream"]["locked"], metadata["locked"])
        self.assertEqual(lock["nodes"]["upstream"]["original"], metadata["original"])
        self.assertEqual(lock["nodes"]["np"], metadata["locks"]["nodes"]["np"])
        self.assertEqual(lock["nodes"]["tools"]["locked"], metadata["locks"]["nodes"]["tools"]["locked"])
        self.assertEqual(lock["nodes"]["tools"]["inputs"], {"one": ["assbox", "nixpkgs"], "two": ["assbox", "tools", "nested"]})
        self.assertEqual(lock["nodes"]["_assbox_machine"]["inputs"], {"assbox": "upstream", "nixpkgs": ["assbox", "nixpkgs"]})

    def test_immutable_reference_and_invalid_graphs(self):
        lock = self.transform(self.metadata())
        original = lock["nodes"]["upstream"]["original"]
        self.assertEqual(original["narHash"], self.metadata()["locked"]["narHash"])
        self.assertNotIn("ref", original)
        for change in ["version", "url", "hash", "original", "collision", "missing", "path", "parent"]:
            metadata = self.metadata()
            if change == "version": metadata["locks"]["version"] = 999
            elif change == "url": metadata["locked"]["url"] += "other"
            elif change == "hash": metadata["locked"]["narHash"] = "sha256-wrong"
            elif change == "original": del metadata["original"]["narHash"]
            elif change == "collision": metadata["locks"]["nodes"]["_assbox_machine"] = {}
            elif change == "path": metadata["locks"]["nodes"]["np"]["locked"]["type"] = "path"
            elif change == "parent": metadata["locks"]["nodes"]["np"]["parent"] = []
            else: del metadata["locks"]["nodes"]["upstream"]["inputs"]["nixpkgs"]
            self.transform(metadata, success=False)

    def test_authenticated_preflight_precedes_target_build_and_boot_activation(self):
        install = (ROOT / "crates/imperative-shell/assbox-engine/src/install.rs").read_text()
        boundary = install.index("// FIRST TARGET WRITE")
        self.assertLess(install.index("    validate_ssh_keys("), install.index("let _lock = Lock::acquire"))
        for step in ["crate::source::resolve", "crate::check_evaluation", "external backup read-back failed", "installation write intent read-back failed"]:
            self.assertLess(install.index(step), boundary)
        after = install[boundary:install.index("\nfn build_with_retry(")]
        build = after.index('"build"')
        validate = after.index("verify_install_target_in_store")
        activate = after.index('"nixos-install"')
        self.assertLess(build, validate)
        self.assertLess(validate, activate)
        self.assertLess(after.index('"release-state"'), activate)
        self.assertLess(after.index('"admin-password.hash"'), activate)
        self.assertLess(after.index('"activating"'), activate)
        self.assertLess(activate, after.index('"complete"'))
        self.assertIn('"--store"', after)
        self.assertIn('"build-dir"', after)
        self.assertRegex(after, r'"--system",\s*&system')
        self.assertNotIn('"--flake"', after)
        self.assertIn("configuration_snapshot(&installed_config)? != configuration", after)
        self.assertIn("cancellation::retry_build,", after)
        self.assertIn("build_system(&image_link, &configuration)?", after)
        self.assertIn("build_system(&output_link, &configuration)?", after)
        self.assertEqual(after.count('"build"'), 1)
        source = (ROOT / "crates/imperative-shell/assbox-engine/src/source.rs").read_text()
        self.assertEqual(source.count('"metadata"'), 1)
        self.assertIn('"--no-update-lock-file"', source)
        self.assertIn("revision != release.manifest.core_commit.as_str()", source)
        self.assertIn("release::fetch(c, requested, directory, None, false)", source)

    def test_boot_target_is_checked_before_profile_publication(self):
        text = (ROOT / "crates/imperative-shell/assbox-engine/src/manage.rs").read_text()
        commit = re.sub(r"\s+", "", text[text.index("fn commit("):text.index("fn fail_before_activation")])
        self.assertIn("BootGuard::capture(c,&marker(\"boot-before\"),new_system)", commit)
        self.assertLess(commit.index("BootGuard::capture"), commit.index('"--set"'))
        self.assertIn("publish_directory(&prepared", text)
        self.assertIn("retire_directory(Path::new(TXN))", text)

    def test_architecture_closure_is_native_and_not_a_path_fallback(self):
        flake = (ROOT / "flake.nix").read_text()
        self.assertRegex(flake, r'\[\s*"x86_64-linux"\s*"aarch64-linux"\s*\]')
        self.assertIn("pkgs.stdenv.hostPlatform.system", flake)
        self.assertIn("tools;", flake)
        self.assertIn("ASSBOX_TOOL_PATH = tools.path", (ROOT / "nix/release-environments.nix").read_text())
        commands = (ROOT / "crates/imperative-shell/assbox-system/src/commands.rs").read_text()
        self.assertRegex(commands, r'env!\(\s*"ASSBOX_TOOL_PATH"')
        self.assertNotIn("/run/current-system/sw/bin", commands)
        for workflow in ["verify.yml", "release.yml"]:
            text = (ROOT / ".github/workflows" / workflow).read_text()
            self.assertIn("runner: ubuntu-24.04-arm", text)
            self.assertIn("runner: ubuntu-24.04", text)
        self.assertIn('select(startswith($prefix))', (ROOT / "scripts/release-check").read_text())

    def test_release_refuses_to_substitute_plan_only_for_end_to_end_acceptance(self):
        script = (ROOT / "scripts/release-check").read_text()
        self.assertIn("install-boot-vm activation-recovery-vm", script)
        self.assertIn("Release promotion blocked", script)
        self.assertLess(script.index("Release promotion blocked"), script.index("scripts/verify"))
        flake = (ROOT / "flake.nix").read_text()
        self.assertIn("management-vm", flake)
        verify = (ROOT / "scripts/verify").read_text()
        self.assertIn('".#checks.$system" --apply builtins.attrNames', verify)
        self.assertIn('nix build --no-link --no-update-lock-file --no-write-lock-file --keep-going ".#checks.$system.$check"', verify)
        self.assertIn('((status == 0)) || exit "$status"', verify)

    def test_mount_and_runtime_policy_ownership_are_explicit(self):
        mounts = (ROOT / "crates/imperative-shell/assbox-system/src/mounts.rs").read_text()
        acquire = mounts[mounts.index("fn acquire("):mounts.index("fn owned_identity(")]
        self.assertLess(acquire.index("backend.mount("), acquire.index("let mut lease"))
        self.assertLess(acquire.index("let mut lease"), acquire.index("lease.owned_identity()"))
        self.assertIn("impl<B: Backend> Drop for Lease<B>", mounts)
        probe = (ROOT / "crates/imperative-shell/assbox-system/src/probe.rs").read_text()
        runtime = probe[probe.index("pub fn runtime_json"):]
        self.assertIn("canonicalize", runtime)
        self.assertIn('starts_with("/nix/store")', runtime)
        self.assertIn("maximumStageRetries", (ROOT / "modules/options.nix").read_text())
        self.assertIn("keepGenerations", (ROOT / "modules/options.nix").read_text())

    def test_mutation_anchors_are_unique_in_actual_source(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("mutations", ROOT / "scripts/mutations.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        text = (ROOT / module.POLICY).read_text()
        for name, before, _ in module.MUTATIONS:
            pattern = r"\s*".join(re.escape(token) for token in re.findall(r"\w+|[^\w\s]", before))
            self.assertEqual(len(re.findall(pattern, text)), 1, name)


if __name__ == "__main__":
    unittest.main()
