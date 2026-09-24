# SPDX-License-Identifier: GPL-3.0-or-later
"""Preserved-state admission/refusal and explicitly labeled source wiring checks."""
import contextlib
import io
import json
import os
from pathlib import Path
import pwd
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from test_worker import ROOT, configuration, w


class PreservedState(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.parent = Path(self.temp.name)
        self.data = self.parent / "state"
        self.c = configuration()
        self.c["dataDir"] = str(self.data)
        self.owner = pwd.getpwnam("nobody") if os.geteuid() == 0 else pwd.getpwuid(os.geteuid())
        self.manifest = {"rootVirtualBytes": 16 * w.GIB}

    def make_state(self):
        self.data.mkdir(mode=0o700)
        disk = self.data / "home.raw"
        with disk.open("wb") as stream:
            stream.write(b"persistent synthetic state\n")
            stream.truncate(self.c["stateGiB"] * w.GIB)
        disk.chmod(0o600)
        if os.geteuid() == 0:
            for path in (self.data, disk):
                os.chown(path, self.owner.pw_uid, self.owner.pw_gid)
        return disk

    def snapshot(self):
        paths = [self.data, *sorted(self.data.iterdir())]
        metadata = [(str(p), p.lstat().st_ino, p.lstat().st_uid, p.lstat().st_gid,
                     p.lstat().st_mode, p.lstat().st_size, p.lstat().st_mtime_ns)
                    for p in paths]
        with (self.data / "home.raw").open("rb") as stream:
            return metadata, stream.read(64)

    def candidate_admission(self, *, missing=False, owner=None):
        kwargs = {"side_effect": KeyError("assbox-vmm")} if missing else {
            "return_value": owner or self.owner}
        with patch.object(w, "require_user"), patch.object(w, "artifact_manifest", return_value=self.manifest), \
             patch.object(w.pwd, "getpwnam", **kwargs), \
             patch.object(w.shutil, "disk_usage", return_value=SimpleNamespace(total=100 * w.GIB, free=100 * w.GIB)), \
             patch.object(w, "transport_preflight"), \
             contextlib.redirect_stdout(io.StringIO()) as output:
            w.admit(self.c)
        return json.loads(output.getvalue())

    def test_retained_identity_allows_read_only_reenable_admission(self):
        self.make_state()
        before = self.snapshot()
        self.assertEqual(self.candidate_admission()["admission"], "accepted")
        self.assertEqual(self.snapshot(), before)

    def test_missing_identity_with_preserved_state_refuses_without_mutation(self):
        self.make_state()
        before = self.snapshot()
        with self.assertRaisesRegex(w.Refusal, "restore the declared infrastructure identities"):
            self.candidate_admission(missing=True)
        self.assertEqual(self.snapshot(), before)

    def test_first_enable_without_identity_or_state_is_read_only(self):
        self.assertEqual(self.candidate_admission(missing=True)["admission"], "accepted")
        self.assertEqual(list(self.parent.iterdir()), [])

    def test_unknown_owner_cannot_adopt_a_symlink_even_with_missing_target(self):
        self.data.symlink_to(self.parent / "missing")
        with self.assertRaises(w.Refusal):
            self.candidate_admission(missing=True)
        self.assertTrue(self.data.is_symlink())

    def test_root_identity_is_not_admitted(self):
        with self.assertRaisesRegex(w.Refusal, "unprivileged"):
            self.candidate_admission(owner=SimpleNamespace(pw_uid=0))
        self.assertFalse(self.data.exists())

    def test_wrong_owner_does_not_get_silently_reassigned(self):
        self.make_state()
        before = self.snapshot()
        with self.assertRaises(w.Refusal):
            self.candidate_admission(owner=SimpleNamespace(pw_uid=self.owner.pw_uid + 1))
        self.assertEqual(self.snapshot(), before)

    def test_changed_size_refuses_without_reformatting(self):
        self.make_state()
        before = self.snapshot()
        self.c["stateGiB"] += 1
        with self.assertRaises(w.Refusal):
            self.candidate_admission()
        self.assertEqual(self.snapshot(), before)

    def test_partial_creation_remains_a_refusal_on_reenable(self):
        self.make_state()
        partial = self.data / "home.raw.new"
        partial.write_bytes(b"interrupted")
        before = self.snapshot()
        with self.assertRaises(w.Refusal):
            self.candidate_admission()
        self.assertEqual(self.snapshot(), before)

    def test_new_data_directory_gets_explicit_nonroot_ownership(self):
        w.ensure_data_dir(self.data, self.owner.pw_uid, self.owner.pw_gid)
        info = self.data.stat()
        self.assertEqual((info.st_uid, info.st_gid, info.st_mode & 0o777),
                         (self.owner.pw_uid, self.owner.pw_gid, 0o700))
        self.assertEqual(list(self.data.iterdir()), [])

    def test_existing_data_directory_is_never_chmod_or_chowned(self):
        self.make_state()
        before = self.snapshot()
        with patch.object(w.os, "fchown") as chown, patch.object(w.os, "fchmod") as chmod:
            w.ensure_data_dir(self.data, self.owner.pw_uid, self.owner.pw_gid)
            chown.assert_not_called()
            chmod.assert_not_called()
        self.assertEqual(self.snapshot(), before)

    def test_unexpected_permissions_refuse_without_normalization(self):
        self.make_state()
        for mode in (0o755, 0o777, 0o500, 0o1700):
            with self.subTest(mode=oct(mode)):
                self.data.chmod(mode)
                with self.assertRaises(w.Refusal):
                    w.ensure_data_dir(self.data, self.owner.pw_uid, self.owner.pw_gid)
                self.assertEqual(self.data.stat().st_mode & 0o7777, mode)
        self.data.chmod(0o700)

    def test_data_provisioning_does_not_follow_symlinks(self):
        target = self.parent / "other"
        target.mkdir(mode=0o700)
        self.data.symlink_to(target)
        with self.assertRaises(w.Refusal):
            w.ensure_data_dir(self.data, self.owner.pw_uid, self.owner.pw_gid)
        self.assertTrue(self.data.is_symlink())
        self.assertEqual(list(target.iterdir()), [])

    def test_new_directory_must_not_use_root_uid_or_gid(self):
        for uid, gid in ((0, self.owner.pw_gid), (self.owner.pw_uid, 0)):
            with self.assertRaises(w.Refusal):
                w.ensure_data_dir(self.data, uid, gid)
            self.assertFalse(self.data.exists())

    def test_prepare_does_not_repair_data_permissions_before_admission(self):
        self.make_state()
        self.data.chmod(0o755)
        with patch.object(w, "require_user"), patch.object(w, "validate_kvm_and_memory"), \
             patch.object(w.os, "geteuid", return_value=self.owner.pw_uid), \
             patch.object(w, "create_state_disk") as create, patch.object(w, "run") as run:
            with self.assertRaises(w.Refusal):
                w.prepare(self.c)
            create.assert_not_called()
            run.assert_not_called()
        self.assertEqual(self.data.stat().st_mode & 0o777, 0o755)


class IdentitySourceContracts(unittest.TestCase):
    """Source wiring only. The NixOS lifecycle gate executes actual activation."""
    def test_account_lifetime_is_assbox_not_worker(self):
        source = (ROOT / "modules/worker/identities.nix").read_text()
        self.assertIn("config = lib.mkIf config.assbox.enable", source)
        self.assertNotIn("&&", source)
        self.assertIn('extraGroups = lib.optional config.assbox.worker.enable "kvm"', source)
        for name in ("assbox-vmm", "assbox-health-probe"):
            self.assertIn("users.users." + name, source)
            self.assertIn("users.groups." + name, source)
        for field in ('createHome = false', 'hashedPassword = "!"', '/bin/nologin'):
            self.assertEqual(source.count(field), 2)

    def test_disabled_identities_do_not_pull_in_worker_runtime(self):
        identities = (ROOT / "modules/worker/identities.nix").read_text()
        for field in ("systemd.", "tmpfiles", "qemu", "environment.", "networking."):
            self.assertNotIn(field, identities)
        main = (ROOT / "modules/worker/default.nix").read_text()
        self.assertIn("./identities.nix", main)
        self.assertNotIn("users.users.assbox-vmm", main)
        self.assertIn("config = lib.mkIf (config.assbox.enable && cfg.enable)", main)

    def test_data_directory_is_not_auto_normalized_by_tmpfiles(self):
        main = (ROOT / "modules/worker/default.nix").read_text()
        self.assertNotIn('"d /var/lib/assbox-worker-data', main)
        source = (ROOT / "scripts/worker/worker.py").read_text()
        self.assertIn('ensure_data_dir(Path(c["dataDir"]), vmm.pw_uid, vmm.pw_gid)', source)
        self.assertNotIn("private_dir(data,", source)

    def test_native_lifecycle_is_a_release_prerequisite(self):
        for path in ("flake.nix", "scripts/release-check"):
            self.assertIn("worker-lifecycle-vm", (ROOT / path).read_text())
        native = (ROOT / "tests/nix/worker-lifecycle-vm.nix").read_text()
        self.assertIn("switch-to-configuration", native)
        self.assertIn("--configuration", native)
        self.assertIn("admit", native)

    def test_acceptance_ssh_is_not_root(self):
        source = (ROOT / "tests/worker/kvm-acceptance.py").read_text()
        self.assertIn("credentials=(controller.pw_uid, controller.pw_gid)", source)
        self.assertIn("controller.pw_uid <= 0", source)


if __name__ == "__main__":
    unittest.main()
