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
    def url(self):
        return "https://github.com/assboxai/assbox/releases/download/r-100/assbox-source.tar.gz"

    def hash(self):
        return "sha256-" + "A" * 43 + "="

    def path(self):
        return "/nix/store/" + "0" * 32 + "-source"

    def metadata(self):
        # Deliberately synthetic values, never a release lock or source receipt.
        return {
            "path": self.path(),
            "locked": {"type": "path", "path": self.path(), "narHash": self.hash(), "__final": True},
            "original": {"type": "path", "path": self.path()},
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
        result = subprocess.run([jq, "-e", "-S", "--arg", "url", self.url(),
                                 "--arg", "hash", self.hash(), "--arg", "path", self.path(),
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
        release = {"type": "tarball", "url": self.url(), "narHash": self.hash()}
        self.assertEqual(lock["nodes"]["upstream"]["locked"], release)
        self.assertEqual(lock["nodes"]["upstream"]["original"], release)
        self.assertEqual(lock["nodes"]["np"], metadata["locks"]["nodes"]["np"])
        self.assertEqual(lock["nodes"]["tools"]["locked"], metadata["locks"]["nodes"]["tools"]["locked"])
        self.assertEqual(lock["nodes"]["tools"]["inputs"], {"one": ["assbox", "nixpkgs"], "two": ["assbox", "tools", "nested"]})
        self.assertEqual(lock["nodes"]["_assbox_machine"]["inputs"], {"assbox": "upstream", "nixpkgs": ["assbox", "nixpkgs"]})

    def test_immutable_reference_and_invalid_graphs(self):
        lock = self.transform(self.metadata())
        original = lock["nodes"]["upstream"]["original"]
        self.assertEqual(original["narHash"], self.hash())
        self.assertNotIn("ref", original)
        for change in ["version", "metadata-path", "source-path", "hash", "original", "collision", "missing", "dependency-path", "parent"]:
            metadata = self.metadata()
            if change == "version": metadata["locks"]["version"] = 999
            elif change == "metadata-path": metadata["path"] += "-other"
            elif change == "source-path": metadata["locked"]["path"] += "-other"
            elif change == "hash": metadata["locked"]["narHash"] = "sha256-wrong"
            elif change == "original": del metadata["original"]["path"]
            elif change == "collision": metadata["locks"]["nodes"]["_assbox_machine"] = {}
            elif change == "dependency-path": metadata["locks"]["nodes"]["np"]["locked"]["type"] = "path"
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
        disk_store = after.index("crate::source::copy_evaluation_store(")
        validate = after.index("verify_install_target_in_store")
        activate = after.index('"nixos-install"')
        self.assertLess(after.index('make_dirs(&root.point, "var/tmp/assbox-build")'), disk_store)
        self.assertLess(disk_store, build)
        self.assertLess(build, validate)
        self.assertLess(validate, activate)
        self.assertLess(after.index('"release-state"'), activate)
        self.assertLess(after.index('"admin-password.hash"'), activate)
        self.assertLess(after.index('"activating"'), activate)
        self.assertLess(activate, after.index('"complete"'))
        self.assertIn('"--store"', after)
        self.assertIn("&target_evaluation_store", after)
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
        self.assertIn('format!("path:{}", files::path_text(&source_path)?)', source)
        self.assertNotIn("release.manifest.pinned_url()", source)
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
        self.assertLess("install-boot-case-", "install-boot-vm")
        install = (ROOT / "tests/nix/install-boot-vm.nix").read_text()
        self.assertIn("inherit cases", install)
        self.assertIn('matrix = pkgs.linkFarm "assbox-install-boot-matrix"', install)
        self.assertIn('"install-boot-case-${name}"', flake)

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

    def test_corruption_fixture_restores_the_read_only_store_mount(self):
        fixture = (ROOT / "tests/fixtures/activation_cases.py").read_text()
        self.assertIn("mount -o remount,rw,bind /nix/store", fixture)
        self.assertIn("'set -eu; mount -o remount,rw,bind /nix/store; trap '", fixture)
        self.assertIn("+ shlex.quote(restore_store) + ' EXIT; chmod u+w '", fixture)
        self.assertIn("mount -o remount,ro,nodev,nosuid,bind /nix/store", fixture)
        self.assertIn("case ,$opts, in *,ro,*", fixture)
        self.assertIn("case ,$opts, in *,nodev,*", fixture)
        self.assertIn("case ,$opts, in *,nosuid,*", fixture)
        self.assertLess(fixture.index("; sync -f "), fixture.index("findmnt --noheadings"))

    def test_corrupt_source_repair_uses_an_isolated_authenticated_cache(self):
        source = (ROOT / "crates/imperative-shell/assbox-engine/src/source.rs").read_text()
        repair_helper = source[source.index("fn repair_flake_source("):source.index("/// Materialize")]
        repair = source[source.index("fn prepare_flake_source("):source.index("pub(crate) fn machine_lock(")]
        binding = source[source.index("pub(crate) fn bind("):source.index("pub(crate) fn resolve(")]
        self.assertIn("files::trusted_dir(parent)?", repair_helper)
        self.assertIn("files::entry_exists(source_root)?", repair_helper)
        self.assertIn("metadata.file_type().is_symlink()", source)
        self.assertIn("fs::read_link(root))? == expected", source)
        self.assertLess(repair_helper.index("exact_source_root(source_root, expected)?"), repair_helper.index("files::random_id()?"))
        self.assertIn('"authenticated-flake-repair-{}"', repair_helper)
        self.assertIn('format!("local?root={}"', repair_helper)
        self.assertIn('format!("file://{}"', repair_helper)
        self.assertIn('"store",\n            "add-path"', repair_helper)
        self.assertIn('"copy",\n            "--to"', repair_helper)
        self.assertIn('"substituters",\n            &cache_uri', repair_helper)
        self.assertIn('"require-sigs",\n            "false"', repair_helper)
        self.assertIn('"store",\n            "repair"', repair_helper)
        self.assertLess(repair_helper.index('"store",\n            "add-path"'), repair_helper.index('"copy",\n            "--to"'))
        self.assertLess(repair_helper.index('"copy",\n            "--to"'), repair_helper.index('"store",\n            "repair"'))
        self.assertNotIn('"delete"', repair_helper)
        self.assertNotIn("/nix/var/nix/gcroots", repair_helper)
        self.assertLess(repair.index("repair_flake_source"), repair.rindex('"store", "verify", "--no-trust"'))
        self.assertLess(repair.rindex('"store", "verify", "--no-trust"'), repair.index("add_owned_source_root"))
        self.assertIn('directory.join("authenticated-flake-source")', binding)
        self.assertNotIn('directory.join("authenticated-source")', binding)
        private_store = source[source.index("fn prepare_evaluation_store("):source.index("pub(crate) fn machine_lock(")]
        self.assertIn('"authenticated-evaluation-store-{}"', private_store)
        self.assertIn('format!("local?root={}"', private_store)
        self.assertIn('"store",\n            "add-path"', private_store)
        self.assertIn('"store",\n            "verify"', private_store)
        self.assertIn('"--store",\n            &evaluation_store', binding)
        self.assertIn('"--eval-store",\n            &evaluation_store', binding)
        self.assertIn("source_path,\n        evaluation_store", binding)
        disk_store = source[source.index("pub(crate) fn copy_evaluation_store("):source.index("pub(crate) fn machine_lock(")]
        normalized = re.sub(r"\s+", "", disk_store)
        self.assertIn('["copy","--all","--from",source_store,"--to",&store_uri]', normalized)
        self.assertNotIn('"--no-check-sigs"', normalized)
        self.assertIn('["--store",&store_uri,"store","verify","--all","--no-trust",]', normalized)
        self.assertIn("files::path_text(authenticated_source)?", disk_store)
        self.assertLess(disk_store.index('"copy"'), disk_store.index('"verify"'))
        install = (ROOT / "crates/imperative-shell/assbox-engine/src/install.rs").read_text()
        management = (ROOT / "crates/imperative-shell/assbox-engine/src/manage.rs").read_text()
        for consumer in [install, management]:
            self.assertIn("fetched.evaluation_store", consumer)
            self.assertIn('"--eval-store"', consumer)
        self.assertIn("&fetched.source_path", install)

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
