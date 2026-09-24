# SPDX-License-Identifier: GPL-3.0-or-later
"""Functional artifact/refusal checks; source contracts are labeled separately."""
import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from test_worker import w, configuration, ROOT

class ArtifactTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.c = configuration(); self.c['artifact'] = str(self.root)
        files = {}
        for name in ('system.qcow2', 'kernel', 'initrd', 'cmdline'):
            value = b'root=/dev/vda rw init=/nix/store/guest/init' if name == 'cmdline' else name.encode()
            (self.root / name).write_bytes(value)
            files[name] = {'bytes': len(value), 'sha256': hashlib.sha256(value).hexdigest()}
        self.m = {'schema': 1, 'buildId': self.c['buildId'], 'rootVirtualBytes': 16*w.GIB, 'files': files}
        self.write()
    def write(self):
        (self.root/'manifest.json').write_text(json.dumps(self.m))
    def test_hash_and_manifest_validation(self):
        self.assertEqual(w.artifact_manifest(self.c, verify_hashes=True), self.m)
    def test_build_identity_mismatch(self):
        self.m['buildId'] = 'b'*64; self.write()
        with self.assertRaises(w.Refusal): w.artifact_manifest(self.c)
    def test_symlink_is_not_accepted_even_with_valid_hash(self):
        source = self.root/'kernel'; moved=self.root/'moved'; source.rename(moved); source.symlink_to(moved)
        with self.assertRaises(w.Refusal): w.artifact_manifest(self.c)
    def test_same_length_corruption_is_detected_by_hash_check(self):
        (self.root/'kernel').write_bytes(b'x'*len(b'kernel'))
        with self.assertRaises(w.Refusal): w.artifact_manifest(self.c, verify_hashes=True)
    def test_truncated_blob_refuses(self):
        (self.root/'kernel').write_bytes(b'x')
        with self.assertRaises(w.Refusal): w.artifact_manifest(self.c)
    def test_invalid_sizes_and_file_sets_refuse(self):
        for size in (True, '4096', -1, w.GIB, 2049*w.GIB):
            self.m['rootVirtualBytes']=size; self.write()
            with self.assertRaises(w.Refusal): w.artifact_manifest(self.c)
        self.m['rootVirtualBytes']=16*w.GIB
        for files in (None, [], {}, {'../escape': {}}):
            self.m['files']=files; self.write()
            with self.assertRaises(w.Refusal): w.artifact_manifest(self.c)
    def test_non_object_metadata_refuses(self):
        self.m['files']['kernel']=None;self.write()
        with self.assertRaises(w.Refusal): w.artifact_manifest(self.c)
    def test_manifest_size_and_type_are_bounded(self):
        for content in ('[]', 'null', '"text"', ' '*17000):
            (self.root/'manifest.json').write_text(content)
            with self.assertRaises((w.Refusal,ValueError)): w.artifact_manifest(self.c)
    def test_checksum_syntax_refuses(self):
        self.m['files']['kernel']['sha256']='bad';self.write()
        with self.assertRaises(w.Refusal): w.artifact_manifest(self.c)
    def test_command_line_and_blob_layout_are_bounded(self):
        p=self.root/'cmdline';p.write_bytes(b'x'*17000)
        self.m['files']['cmdline']['bytes']=17000;self.write()
        with self.assertRaises(w.Refusal): w.artifact_manifest(self.c)
    def test_supported_machines_use_pci_without_extra_shutdown_channel(self):
        for machine in ('q35', 'virt,gic-version=host'):
            self.c['machine'] = machine
            args = w.qemu_args(self.c)
            self.assertIn('virtio-blk-pci,drive=root', args)
            self.assertIn('virtio-rng-pci,rng=rng0', args)
            self.assertNotIn('-chardev', args)
            self.assertIn('-no-reboot', args)
    def test_invalid_kernel_command_line_refuses(self):
        (self.root/'cmdline').write_bytes(b'\n'*len((self.root/'cmdline').read_bytes()))
        with self.assertRaises(w.Refusal): w.qemu_args(self.c)

class HealthTests(unittest.TestCase):
    def test_exact_build_reply_only(self):
        c=configuration();good='ASSBOX-WORKER-HEALTH/1\n'+c['buildId']+'\n'
        self.assertTrue(w.health_matches(c,good))
        for reply in ('',good+'x',good.strip(),good.replace('a','b'),good.replace('/1','/2')):
            self.assertFalse(w.health_matches(c,reply))
    def test_health_transport_is_not_agent_transport(self):
        c=configuration();args=w.health_ssh_args(c)
        self.assertIn(c['healthSshConfig'],args)
        self.assertNotIn(c['sshConfig'],args)
        self.assertIn('assbox-worker-health',args)
    def test_health_requires_root_and_checks_exact_response(self):
        c=configuration()
        with patch.object(w,'require_user') as user, patch.object(w,'artifact_manifest'), \
             patch.object(w,'bounded_capture',return_value='ASSBOX-WORKER-HEALTH/1\n'+c['buildId']+'\n') as capture:
            with patch.object(w.pwd, "getpwnam", return_value=SimpleNamespace(pw_uid=200, pw_gid=200)):
                w.check(c)
            user.assert_called_once_with('root')
            self.assertEqual(capture.call_args.args[0],w.health_ssh_args(c))
    def test_full_virtual_root_budget_is_checked_before_formatting(self):
        with tempfile.TemporaryDirectory() as temp:
            c=configuration();c['dataDir']=temp
            with patch.object(w,'require_user'),patch.object(w,'validate_kvm_and_memory'), \
                 patch.object(w,'artifact_manifest',return_value={'rootVirtualBytes':64*w.GIB}), \
                 patch.object(w.shutil,'disk_usage',return_value=SimpleNamespace(total=100 * w.GIB, free=32*w.GIB)), \
                 patch.object(w,'create_state_disk') as create:
                with self.assertRaises(w.Refusal): w.prepare(c)
                create.assert_not_called()

class IntegrationSourceContracts(unittest.TestCase):
    """These check source wiring, not successful Nix or Rust execution."""
    def test_host_generation_pins_artifact_not_guest_system(self):
        source=(ROOT/'modules/worker/default.nix').read_text()
        self.assertNotIn('system.build.assboxWorkerGuest',source)
        self.assertNotIn('"$out/assbox-worker-system"',source)
        self.assertNotIn('guestSystem =',source)
        self.assertIn('system.build.assboxWorkerAudit',source)
    def test_artifact_reference_boundary_is_explicit(self):
        source=(ROOT/'nix/worker-image.nix').read_text()
        for text in ('unsafeDiscardReferences.out = true','allowedReferences = [ ]','maxSize =','cp -L','auditClosure = system'):
            self.assertIn(text,source)
    def test_every_acceptance_path_checks_health(self):
        s=(ROOT/'crates/imperative-shell/assbox-engine/src/manage.rs').read_text()
        for name,end in [('fn boot_check_with_retry(', 'pub fn components_set('),
                         ('fn reboot_pending_locked()', 'pub fn recover('),
                         ('fn cleanup_locked()', 'pub fn cleanup()')]:
            block=s.split(name,1)[1].split(end,1)[0]
            gate=block.index('require_worker_health(')
            action='files::remove_regular(Path::new(PENDING))' if 'cleanup_locked' not in name else 'generations()?'
            self.assertLess(gate,block.index(action))
    def test_guest_health_account_has_no_persistent_shell_or_forwarding(self):
        s=(ROOT/'modules/worker/guest.nix').read_text()
        for text in ('users.users.assbox-health','home = "/var/empty"','shell = "${healthShell}/bin/assbox-health-shell"','DisableForwarding yes','PermitUserRC no'):
            self.assertIn(text,s)
    def test_independent_guest_audit_and_native_acceptance_gates(self):
        s=(ROOT/'scripts/release-check').read_text()
        for text in ('worker-artifact','worker-boot-gate-vm','vulnix-worker-codex.json','assboxWorkerAudit'):
            self.assertIn(text,s)


class CancellationTests(unittest.TestCase):
    def test_outer_deadline_termination_reaps_the_ssh_process_group(self):
        import os
        import signal
        import subprocess
        import sys
        import time
        with tempfile.TemporaryDirectory() as temporary:
            pidfile=Path(temporary)/'child.pid'
            # Publish readiness atomically; existence must imply a complete PID.
            child=("import os,time,pathlib;p=pathlib.Path("+repr(str(pidfile))+");"
                   "t=p.with_suffix('.tmp');t.write_text(str(os.getpid()));t.replace(p);time.sleep(30)")
            parent="import sys;sys.path.insert(0,"+repr(str(ROOT/'scripts/worker'))+");import worker;worker.bounded_capture([sys.executable,'-c',"+repr(child)+"],timeout=30)"
            process=subprocess.Popen([sys.executable,'-c',parent])
            try:
                deadline=time.monotonic()+5
                while not pidfile.exists() and time.monotonic()<deadline:
                    time.sleep(0.02)
                self.assertTrue(pidfile.exists())
                pid=int(pidfile.read_text())
                process.send_signal(signal.SIGTERM)
                self.assertEqual(process.wait(timeout=5),143)
                with self.assertRaises(ProcessLookupError):
                    os.kill(pid,0)
            finally:
                if process.poll() is None:
                    process.kill();process.wait()
