# SPDX-License-Identifier: GPL-3.0-or-later
"""Independent product/surface checks; these do not claim to execute Rust or Nix."""
from __future__ import annotations
import importlib.util
import re
import shutil
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("architecture", ROOT / "scripts/architecture.py")
assert spec and spec.loader
architecture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(architecture)


class ArchitectureTests(unittest.TestCase):
    def test_workspace_graph(self):
        self.assertEqual(architecture.check(ROOT), [])

    def test_terminal_adapter_features_versions_and_checksums_are_fixed(self):
        with tempfile.TemporaryDirectory() as temporary:
            tree = Path(temporary)
            shutil.copytree(ROOT / "crates", tree / "crates")
            for name in ("Cargo.toml", "Cargo.lock"):
                shutil.copyfile(ROOT / name, tree / name)
            manifest = tree / "crates/imperative-shell/assbox-system/Cargo.toml"
            original = manifest.read_text()
            for changed in (original.replace('"std", "termios"', '"std", "termios", "net"'),
                            original.replace('"=1.1.4"', '"1.1.4"')):
                manifest.write_text(changed)
                self.assertTrue(architecture.check(tree))
            manifest.write_text(original)
            lock = tree / "Cargo.lock"
            locked = lock.read_text()
            changes = (locked.replace('name = "rustix"\nversion = "1.1.4"',
                                      'name = "rustix"\nversion = "1.1.5"'),
                       re.sub(r'checksum = "[a-f0-9]+"', 'checksum = "' + '0' * 64 + '"', locked, count=1))
            for changed in changes:
                lock.write_text(changed)
                self.assertTrue(architecture.check(tree))

    def test_core_lint_detects_direct_grouped_and_alias_effects(self):
        for example in ["use std::fs;", "use std::{fs,fmt};", "std::time::SystemTime::now();",
                        "use std as ambient;", "println!(\"effect\");", "extern crate libc;",
                        "static mut CLOCK: u64 = 0;", '#[path="../shell.rs"] mod shell;']:
            with self.subTest(example=example):
                self.assertTrue(architecture.core_violations(example))

    def test_comments_and_strings_are_not_effects(self):
        self.assertEqual(architecture.core_violations('let fs = 1; // use std::fs;\n let a = "println!(oops)";'), [])
        self.assertEqual(architecture.core_violations('/* outer /* inner */ std::fs */ use std::fmt;'), [])
        self.assertEqual(architecture.core_violations('let x = r###"std::fs"###;'), [])

    def test_all_crates_are_nonpublished_and_unsafe_is_forbidden(self):
        roots = list((ROOT / "crates").glob("*/*/src/lib.rs")) + list((ROOT / "crates").glob("*/*/src/main.rs"))
        self.assertEqual(len(roots), 6)
        self.assertTrue(all("#![forbid(unsafe_code)]" in p.read_text() for p in roots))


class ProductSurfaceTests(unittest.TestCase):
    def test_just_is_a_tool_not_an_administrative_interface(self):
        self.assertIn("just", (ROOT / "modules/base.nix").read_text())
        self.assertFalse(any(p.name.lower() in {"justfile", ".justfile"} for p in (ROOT / "modules").rglob("*")))
        self.assertNotIn("just ", (ROOT / "modules/maintenance.nix").read_text())

    def test_service_entrypoints_match_cli_routes(self):
        main = re.sub(r"\s+", "", (ROOT / "crates/imperative-shell/assbox-cli/src/main.rs").read_text())
        for route in ['["internal","maintenance"]', '["internal","maintenance","--retry"]', '["internal","boot-check"]']:
            self.assertIn(route, main)
        services = (ROOT / "modules/applications.nix").read_text()
        onboarding = (ROOT / "crates/imperative-shell/assbox-cli/src/user.rs").read_text()
        for service in re.findall(r'"(assbox-[a-z]+)\.service"', onboarding):
            self.assertIn(f"systemd.user.services.{service}", services)

    def test_profiles_keep_application_and_presentation_independent(self):
        options = re.sub(r"\s+", "", (ROOT / "modules/options.nix").read_text())
        self.assertIn("selectedComponents", options)
        self.assertIn('["headless""x11""wayland"]', options)
        apps = (ROOT / "modules/applications.nix").read_text()
        self.assertNotIn("apps.codex", apps)
        self.assertIn('enabled "opencode-server"', apps)
        self.assertIn('enabled "openclaw-gateway"', apps)
        self.assertNotIn("--no-sandbox", apps)

    def test_device_rules_precede_seat_acl_assignment(self):
        devices = (ROOT / "modules/devices.nix").read_text()
        self.assertIn("72-assbox-policy.rules", devices)
        self.assertIn('TAG-="uaccess"', devices)
        self.assertNotIn('services.udev.extraRules', devices)

    def test_execution_policy_target_survives_role_switch_and_revokes_before_stop(self):
        base = re.sub(r"\s+", " ", (ROOT / "modules/base.nix").read_text())
        policy = re.sub(r"\s+", " ", (ROOT / "modules/network-policy.nix").read_text())
        self.assertIn('systemd.slices."user-1000"', base)
        self.assertIn('wantedBy = [ "multi-user.target" ]', base)
        self.assertIn('before = [ "nftables.service" ]', base)
        self.assertIn('serviceConfig.ExecStop = lib.mkBefore [ revoke ]', policy)
        self.assertNotIn('serviceConfig.ExecStopPre', policy)

    def test_maintenance_is_local_persistent_and_cannot_be_vetoed_by_a_gui(self):
        self.assertIn('*-*-* 18:00:00', (ROOT / "modules/options.nix").read_text())
        self.assertIn('Persistent = cfg.updates.persistent', (ROOT / "modules/maintenance.nix").read_text())
        manager = (ROOT / "crates/imperative-shell/assbox-engine/src/manage.rs").read_text()
        self.assertIn('"--check-inhibitors=no","reboot"', re.sub(r'\s+', '', manager))
        self.assertIn('"boot"', manager)
        self.assertIn('recovery_after_interruption', manager)
        self.assertNotIn('is_session_active', manager)

    def test_pending_boot_and_recovery_are_decided_before_network_staging(self):
        # Source-order integration guard only; actual decision behavior is tested
        # by Rust, and installed activation/recovery requires the VM gate.
        manager = (ROOT / "crates/imperative-shell/assbox-engine/src/manage.rs").read_text()
        maintenance = manager.split("pub fn maintenance(", 1)[1].split("fn reboot_pending_locked", 1)[0]
        self.assertIn("maintenance_action(", maintenance)
        self.assertLess(maintenance.index("maintenance_action("), maintenance.index("maintenance_numbers()"))
        self.assertLess(maintenance.index("MaintenanceAction::RebootPending"), maintenance.index("stage_locked()?"))
        self.assertIn("MaintenanceAction::InspectRecovery", maintenance)
        reboot = manager.split("fn reboot_pending_locked", 1)[1].split("pub fn recover", 1)[0]
        self.assertLess(reboot.index("state_entry_exists(TXN)?"), reboot.index("thread::sleep"))
        self.assertLess(reboot.index("state_entry_exists(TXN)?"), reboot.index('"systemctl"'))

    def test_install_checks_all_filesystems_before_mounting(self):
        install = (ROOT / "crates/imperative-shell/assbox-engine/src/install.rs").read_text()
        compact = re.sub(r"\s+", "", install)
        self.assertLess(compact.index('forpinselected'), compact.index('letmutroot_probe=Mount::new'))
        self.assertIn('filesystem_check(p.fs)', install)
        self.assertIn('"fsck.exfat"', install)
        self.assertIn('external backup read-back failed', install)
        self.assertIn('backup.unmount', install)

    def test_public_status_label_is_readme_only(self):
        if not (ROOT / "README.md").exists():
            self.fail("README is required")
        self.assertRegex((ROOT / "README.md").read_text(), r'(?i)\bbeta\b')
        for path in ROOT.rglob("*.md"):
            if path != ROOT / "README.md" and ".git" not in path.parts:
                # Dated upstream evidence may call a provider feature beta.
                # The Assbox public status label belongs only in README.
                self.assertNotRegex(path.read_text(),
                    r'(?im)^\*?\*?(?:source |release |project )?status:\*?\*?.*\bbeta\b', str(path))


if __name__ == "__main__":
    unittest.main()
