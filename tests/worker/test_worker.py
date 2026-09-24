# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations
import copy
import importlib.util
import ipaddress
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("assbox_worker", ROOT / "scripts/worker/worker.py")
w = importlib.util.module_from_spec(spec)
spec.loader.exec_module(w)


def configuration():
    store = "/nix/store/00000000000000000000000000000000-fixture"
    return {
        "schema": 2, "controller": "agent", "vmm": "assbox-vmm",
        **w.FIXED_DIRS,
        "artifact": store, "buildId": "a" * 64,
        "healthSshConfig": "/etc/assbox/worker-health-ssh-config",
        "sshConfig": "/etc/assbox/worker-ssh-config",
        "memoryMiB": 3072, "hostReserveMiB": 2048, "vcpus": 2, "stateGiB": 8,
        "machine": "q35", "interface": "ab-worker0", "hostAddress": "10.77.0.1",
        "guestAddress": "10.77.0.2", "uplinkInterfaces": ["eth0"], "egress": "internet",
        "nameservers": ["1.1.1.1"], "additionalDeniedCidrs": [],
        "selectedComponents": ["codex"],
        "tools": {name: store + "/bin/" + name for name in
                  ("qemu", "qemuImg", "ssh", "sshKeygen", "mkfs", "xorriso", "ip", "systemctl", "nft")},
    }


class ConfigurationTests(unittest.TestCase):
    def test_valid(self):
        w.validate_config(configuration())

    def test_every_privileged_path_is_fixed(self):
        for field in w.FIXED_DIRS:
            with self.subTest(field=field):
                c = configuration(); c[field] = "/tmp/arbitrary"
                with self.assertRaises(w.Refusal): w.validate_config(c)

    def test_paths_must_be_store_bound(self):
        for field in ("artifact",):
            with self.subTest(field=field):
                c = configuration(); c[field] = "/home/agent/untrusted"
                with self.assertRaises(w.Refusal): w.validate_config(c)

    def test_no_ambient_tool_path(self):
        c = configuration(); c["tools"]["ssh"] = "ssh"
        with self.assertRaises(w.Refusal): w.validate_config(c)

    def test_no_arbitrary_ssh_config(self):
        c = configuration(); c["sshConfig"] = "/home/agent/.ssh/config"
        with self.assertRaises(w.Refusal): w.validate_config(c)

    def test_rejects_wrong_identity(self):
        for key, value in (("schema", 3), ("controller", "root"), ("vmm", "agent")):
            c = configuration(); c[key] = value
            with self.assertRaises(w.Refusal): w.validate_config(c)

    def test_rejects_interface_injection(self):
        for value in ('eth0" accept', 'eth0;id', 'eth0\n', 'long' * 8, 'a,b'):
            c = configuration(); c["interface"] = value
            with self.assertRaises(w.Refusal): w.validate_config(c)

    def test_rejects_tap_as_uplink(self):
        c = configuration(); c["uplinkInterfaces"] = [c["interface"]]
        with self.assertRaises(w.Refusal): w.validate_config(c)

    def test_no_implicit_internet_uplink(self):
        c = configuration(); c["uplinkInterfaces"] = []
        with self.assertRaises(w.Refusal): w.validate_config(c)

    def test_offline_needs_no_dns_or_uplink(self):
        c = configuration(); c.update(egress="offline", uplinkInterfaces=[], nameservers=[])
        w.validate_config(c)

    def test_normal_allows_lan_dns_but_not_controller_or_special_addresses(self):
        c = configuration(); c['egress'] = 'normal'
        for resolver in ('192.168.1.1', '10.1.2.3', '100.100.100.100', '172.16.0.1'):
            c['nameservers'] = [resolver]
            w.validate_config(c)
        for resolver in ('10.77.0.1', '10.77.0.2', '127.0.0.1', '169.254.169.254', '224.0.0.1'):
            c['nameservers'] = [resolver]
            with self.assertRaises(w.Refusal): w.validate_config(c)

    def test_offline_rejects_residual_network_settings(self):
        c = configuration(); c['egress'] = 'offline'
        with self.assertRaises(w.Refusal): w.validate_config(c)

    def test_rejects_unknown_egress(self):
        c = configuration(); c["egress"] = "anything"
        with self.assertRaises(w.Refusal): w.validate_config(c)

    def test_rejects_host_guest_address_errors(self):
        for host, guest in (("10.77.0.2", "10.77.0.1"), ("10.77.0.0", "10.77.0.2"),
                            ("10.77.0.1", "10.78.0.2"), ("192.168.1.1", "192.168.1.2"),
                            ("999.1.1.1", "10.77.0.2")):
            c = configuration(); c.update(hostAddress=host, guestAddress=guest)
            with self.assertRaises((w.Refusal, ValueError)): w.validate_config(c)

    def test_renumbered_private_subnet(self):
        c = configuration(); c.update(hostAddress="10.231.7.5", guestAddress="10.231.7.6")
        w.validate_config(c)

    def test_dns_cannot_bypass_private_destination_deny(self):
        for resolver in ("127.0.0.1", "10.77.0.1", "169.254.169.254", "100.100.100.100", "192.168.1.1"):
            c = configuration(); c["nameservers"] = [resolver]
            with self.assertRaises(w.Refusal): w.validate_config(c)

    def test_additional_denial_applies_to_dns(self):
        c = configuration(); c["additionalDeniedCidrs"] = ["1.1.1.0/24"]
        with self.assertRaises(w.Refusal): w.validate_config(c)

    def test_limits_are_positive_bounded_integers(self):
        for key in ("memoryMiB", "hostReserveMiB", "vcpus", "stateGiB"):
            for value in (-1, 0, True, 999999, "3072"):
                c = configuration(); c[key] = value
                with self.assertRaises(w.Refusal): w.validate_config(c)

    def test_experimental_or_emulated_machine_selection_refuses(self):
        for machine in ('microvm', 'pc', 'virt', 'q35,accel=tcg'):
            c = configuration()
            c['machine'] = machine
            with self.assertRaises(w.Refusal):
                w.validate_config(c)

    def test_missing_kvm_refuses(self):
        with patch.object(w.os, "open", side_effect=FileNotFoundError("/dev/kvm")):
            with self.assertRaisesRegex(w.Refusal, "not fallbacks"):
                w.validate_kvm_and_memory(configuration())

    def test_insufficient_memory_refuses(self):
        with patch.object(w.os, "open", return_value=123), patch.object(w.os, "close"), \
             patch.object(w.fcntl, "ioctl", return_value=12), \
             patch.object(w.Path, "read_text", return_value="MemTotal:       4194304 kB\n"):
            with self.assertRaisesRegex(w.Refusal, "physical RAM"):
                w.validate_kvm_and_memory(configuration())

    def test_no_tcg_machine_mode(self):
        c = configuration(); c["machine"] = "pc,accel=tcg"
        with self.assertRaises(w.Refusal): w.validate_config(c)


class QemuTests(unittest.TestCase):
    def setUp(self):
        manifest = patch.object(w, "artifact_manifest", return_value={"rootVirtualBytes": 4 * w.GIB})
        cmdline = patch.object(w.Path, "read_text", return_value="root=/dev/vda rw init=/nix/store/guest/init")
        manifest.start(); cmdline.start()
        self.addCleanup(manifest.stop); self.addCleanup(cmdline.stop)

    def test_acceleration_is_kvm_only(self):
        args = w.qemu_args(configuration())
        self.assertEqual(args[args.index("-accel") + 1], "kvm")
        self.assertNotIn("tcg", " ".join(args))

    def test_no_shared_filesystems_or_host_desktop_devices(self):
        args = " ".join(w.qemu_args(configuration()))
        for word in ("virtiofs", "9p", "-virtfs", "-fsdev", "usb-host", "vfio-pci", "spice", "vnc", "guest-agent", "vhost-vsock"):
            self.assertNotIn(word, args)
        self.assertNotIn("/home/agent", args)
        self.assertNotIn("client_ed25519", args)

    def test_disk_formats_explicit_and_seed_readonly(self):
        args = w.qemu_args(configuration())
        drives = [args[n + 1] for n, value in enumerate(args) if value == "-drive"]
        self.assertEqual(len(drives), 3)
        self.assertIn("format=qcow2", drives[0])
        self.assertIn("format=raw", drives[1])
        self.assertIn("readonly=on", drives[2])

    def test_no_network_backdoor(self):
        args = " ".join(w.qemu_args(configuration()))
        self.assertIn("script=no,downscript=no", args)
        self.assertNotIn("user,id", args)
        self.assertNotIn("hostfwd", args)
        self.assertNotIn("guestfwd", args)

    def test_qmp_is_local_private_socket(self):
        args = w.qemu_args(configuration())
        self.assertEqual(args[args.index("-qmp") + 1], "unix:/run/assbox-worker/qmp.sock,server=on,wait=off")
        self.assertNotIn("tcp:", " ".join(args))

    def test_system_path_in_kernel_commandline(self):
        c = configuration(); args = w.qemu_args(c)
        self.assertIn("init=/nix/store/guest/init", args[args.index("-append") + 1])

    def test_native_arm_uses_same_no_share_contract(self):
        c = configuration(); c["machine"] = "virt,gic-version=host"
        self.assertIn("virt,gic-version=host", w.qemu_args(c))

    def test_guest_console_is_not_logged(self):
        args = w.qemu_args(configuration())
        self.assertEqual(args[args.index("-serial") + 1], "null")

    def test_ssh_transport_has_no_user_config_authority(self):
        c = configuration(); args = w.ssh_args(c)
        self.assertEqual(args[args.index("-F") + 1], c["sshConfig"])
        self.assertIn("BatchMode=yes", args)
        self.assertEqual(args[-1], "assbox-worker")


class FileTests(unittest.TestCase):
    def test_atomic_write_mode_and_bytes(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "file"
            w.atomic_write(p, b"private")
            self.assertEqual(p.read_bytes(), b"private")
            self.assertEqual(p.stat().st_mode & 0o777, 0o600)
            w.atomic_write(p, b"updated")
            self.assertEqual(p.read_bytes(), b"updated")
            self.assertEqual(sorted(x.name for x in Path(d).iterdir()), ["file"])

    def test_atomic_write_rejects_symlink(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d); (p / "real").write_bytes(b"retain")
            (p / "link").symlink_to(p / "real")
            with self.assertRaises(w.Refusal): w.atomic_write(p / "link", b"overwrite")
            self.assertEqual((p / "real").read_bytes(), b"retain")

    def test_rejects_hardlink(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d); (p / "a").write_bytes(b"keep")
            os.link(p / "a", p / "b")
            with self.assertRaises(w.Refusal): w.require_regular(p / "a")

    def test_existing_state_is_never_formatted(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "home.raw"; p.write_bytes(b"data"); p.chmod(0o600)
            with patch.object(w, "run") as run:
                w.create_state_disk(p, 4, "/not-used")
                run.assert_not_called()
            self.assertEqual(p.read_bytes(), b"data")

    def test_size_mismatch_refuses_without_write(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "home.raw"; p.write_bytes(b"data"); p.chmod(0o600)
            with self.assertRaises(w.Refusal): w.create_state_disk(p, 5, "/not-used")
            self.assertEqual(p.read_bytes(), b"data")

    def test_state_symlink_is_not_followed(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d); (p / "target").write_bytes(b"data")
            (p / "home.raw").symlink_to(p / "target")
            with self.assertRaises(w.Refusal): w.create_state_disk(p / "home.raw", 4, "/not-used")

    def test_incomplete_allocation_is_not_silently_reused(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d); (p / "home.raw.new").write_bytes(b"partial")
            with self.assertRaises(FileExistsError): w.create_state_disk(p / "home.raw", 4096, "/not-used")
            self.assertFalse((p / "home.raw").exists())

    def test_new_state_published_only_after_mkfs(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "home.raw"
            def mkfs(args, **kwargs):
                self.assertFalse(p.exists())
                self.assertTrue(Path(args[-1]).exists())
                self.assertIn("nodiscard", args)
                return ""
            with patch.object(w, "run", side_effect=mkfs):
                w.create_state_disk(p, 1024 * 1024, "/mock-mkfs")
            self.assertEqual(p.stat().st_size, 1024 * 1024)
            self.assertFalse(p.with_name("home.raw.new").exists())


class SshConfigTests(unittest.TestCase):
    MANAGED = "Host assbox-worker\n  HostName 10.77.0.2\n  ForwardAgent no\n"

    def test_existing_content_preserved(self):
        existing = "Host work\n  HostName example.org\n"
        merged = w.merge_ssh_config(existing, self.MANAGED)
        self.assertTrue(merged.endswith(existing))
        self.assertTrue(merged.startswith("# BEGIN ASSBOX"))

    def test_idempotent(self):
        first = w.merge_ssh_config("", self.MANAGED)
        self.assertEqual(w.merge_ssh_config(first, self.MANAGED), first)

    def test_replaces_one_managed_block(self):
        first = w.merge_ssh_config("Host other\n  User me\n", self.MANAGED)
        result = w.merge_ssh_config(first, self.MANAGED.replace("10.77.0.2", "10.88.0.2"))
        self.assertIn("10.88.0.2", result)
        self.assertNotIn("10.77.0.2", result)
        self.assertIn("Host other", result)

    def test_conflicting_alias_fails(self):
        for existing in ("Host assbox-worker\n", "host other assbox-worker\n"):
            with self.assertRaises(w.Refusal): w.merge_ssh_config(existing, self.MANAGED)

    def test_corrupt_markers_fail(self):
        for existing in ("# BEGIN ASSBOX WORKER (managed)\n", "# END ASSBOX WORKER\n", "# END ASSBOX WORKER\n# BEGIN ASSBOX WORKER (managed)\n"):
            with self.assertRaises(w.Refusal): w.merge_ssh_config(existing, self.MANAGED)


class HostileResponseTests(unittest.TestCase):
    def test_normal_bounded_capture(self):
        self.assertEqual(w.bounded_capture([sys.executable, "-c", 'print("ready")']), "ready\n")

    def test_caps_stdout(self):
        with self.assertRaises(w.Refusal):
            w.bounded_capture([sys.executable, "-c", 'print("x" * 20000)'], limit=1024)

    def test_caps_stderr(self):
        with self.assertRaises(w.Refusal):
            w.bounded_capture([sys.executable, "-c", 'import sys; sys.stderr.write("x" * 20000)'], limit=1024)

    def test_timeout(self):
        with self.assertRaises(w.Refusal):
            w.bounded_capture([sys.executable, "-c", 'import time; time.sleep(10)'], timeout=1)

    def test_nonzero_is_failure_not_ready(self):
        with self.assertRaises(w.Refusal):
            w.bounded_capture([sys.executable, "-c", 'raise SystemExit(1)'])


class SourceContractTests(unittest.TestCase):
    def test_host_and_python_deny_sets_do_not_drift(self):
        source = (ROOT / "modules/worker/default.nix").read_text()
        block = source.split("privateRanges = [", 1)[1].split("];", 1)[0]
        import re
        actual = set(re.findall(r'"([0-9./]+)"', block))
        self.assertEqual(actual, {str(n) for n in w.DENIED})

    def test_host_drop_does_not_rely_on_guest_firewall(self):
        source = (ROOT / "modules/worker/default.nix").read_text()
        self.assertIn("hook input priority -10", source)
        self.assertIn("hook forward priority -10", source)
        self.assertIn("meta nfproto ipv6 counter drop", source)
        self.assertIn("ip saddr != ${cfg.guestAddress} counter drop", source)
        self.assertIn("ip daddr @denied4 counter drop", source)

    def test_service_starts_after_firewall_and_is_unprivileged(self):
        source = (ROOT / "modules/worker/default.nix").read_text()
        self.assertIn('User = "assbox-vmm"', source)
        import re
        self.assertIn('bindsTo = [ "assbox-worker-network.service" "nftables.service" ]', re.sub(r"\s+", " ", source))
        self.assertIn('IPAddressDeny = "any"', source)
        self.assertIn('ProtectHome = true', source)
        self.assertIn('restartTriggers = [ runtimeFile ]', source)

    def test_guest_excludes_host_updater_and_desktop(self):
        source = (ROOT / "modules/worker/guest.nix").read_text()
        for module in ("../base.nix", "../maintenance.nix", "../presentation.nix", "../boot.nix"):
            self.assertNotIn(module, source)
        self.assertIn('presentation = "headless"', source)
        self.assertIn('system.autoUpgrade.enable = false', source)
        self.assertNotIn('"/nix/store" =', source)

    def test_seed_authorized_keys_readable_but_private_key_restricted(self):
        source = (ROOT / "scripts/worker/worker.py").read_text()
        self.assertIn("root.mkdir(mode=0o755)", source)
        self.assertIn('(root / "agent.pub").chmod(0o644)', source)
        self.assertIn("private.chmod(0o600)", source)
        self.assertIn('"-R", "-V", "ASSBOX_SEED"', source)

    def test_password_migration_is_independent_of_worker_enable(self):
        source = (ROOT / "modules/worker/default.nix").read_text()
        self.assertNotIn("password-store", source)
        self.assertTrue((ROOT / "docs/worker/password-storage.md").is_file())

    def test_no_automatic_codex_installation(self):
        source = (ROOT / "modules/worker/default.nix").read_text()
        selection = source.split("components = lib.mkOption", 1)[1].split("};", 1)[0]
        self.assertIn("default = [ ]", selection)


if __name__ == "__main__":
    unittest.main()
