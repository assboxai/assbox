# SPDX-License-Identifier: GPL-3.0-or-later
"""Executable helper tests plus explicit source-wiring checks (not Nix proofs)."""
import importlib.util
import json
import os
from pathlib import Path
import pwd
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from test_worker import configuration, w, ROOT


class DroppedHealthIdentity(unittest.TestCase):
    def test_nonroot_identity_required(self):
        for ids in [(0, 100), (100, 0), (-1, 100), (True, 100), (100, '100')]:
            with self.assertRaises(w.Refusal):
                w.bounded_capture(['/bin/false'], credentials=ids)

    @unittest.skipUnless(os.geteuid() == 0, 'real UID drop requires root test environment')
    def test_real_child_has_only_probe_identity_and_no_inherited_secret(self):
        probe = pwd.getpwnam('nobody')
        script = 'import os,json; print(json.dumps([os.getuid(),os.getgid(),os.getgroups(),os.getenv("ASSBOX_TEST_SECRET"),os.getcwd()]))'
        with patch.dict(os.environ, {'ASSBOX_TEST_SECRET': 'do-not-inherit'}):
            result = w.bounded_capture([sys.executable, '-c', script],
                                       credentials=(probe.pw_uid, probe.pw_gid))
        self.assertEqual(json.loads(result), [probe.pw_uid, probe.pw_gid, [], None, '/'])

    def test_health_does_not_fall_back_to_root_for_missing_account(self):
        with patch.object(w, 'require_user'), patch.object(w, 'artifact_manifest'), \
             patch.object(w.pwd, 'getpwnam', side_effect=KeyError), \
             patch.object(w, 'bounded_capture') as spawn:
            with self.assertRaises(KeyError): w.check(configuration())
            spawn.assert_not_called()

    def test_probe_credentials_reach_bounded_subprocess(self):
        c=configuration()
        with patch.object(w, 'require_user'), patch.object(w, 'artifact_manifest'), \
             patch.object(w.pwd, 'getpwnam', return_value=SimpleNamespace(pw_uid=300,pw_gid=301)), \
             patch.object(w, 'bounded_capture', return_value='ASSBOX-WORKER-HEALTH/1\n'+c['buildId']+'\n') as capture:
            w.check(c)
        self.assertEqual(capture.call_args.kwargs['credentials'], (300,301))


class Admission(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.c=configuration(); self.c['dataDir']=str(Path(self.temp.name)/'state')
        self.manifest={'rootVirtualBytes': 20*w.GIB}

    def admit(self, free):
        with patch.object(w.shutil,'disk_usage', return_value=SimpleNamespace(total=100 * w.GIB, free=free)):
            return w.disk_admission(self.c,self.manifest,owner=os.geteuid())

    def test_actual_image_not_initial_16gib_estimate_controls_acceptance(self):
        with self.assertRaises(w.Refusal): self.admit(8*w.GIB+16*w.GIB)
        result=self.admit(36*w.GIB)
        self.assertEqual(result['requiredBytes'],36*w.GIB)
        self.assertFalse(Path(self.c['dataDir']).exists())

    def test_missing_space_refuses_without_creating_state(self):
        with self.assertRaises(w.Refusal): self.admit(36*w.GIB-1)
        self.assertEqual(list(Path(self.temp.name).iterdir()), [])

    def test_sparse_home_still_requires_allocation_headroom(self):
        data=Path(self.c['dataDir']);data.mkdir(mode=0o700)
        home=data/'home.raw'
        with home.open('wb') as f: f.truncate(8*w.GIB)
        home.chmod(0o600)
        with self.assertRaises(w.Refusal): self.admit(28*w.GIB)
        self.assertEqual(self.admit(36*w.GIB)['requiredBytes'],36*w.GIB)

    def test_auto_sized_state_survives_controller_growth_and_restart(self):
        # Rust's automatic_state_gib(256 GiB, 220 GiB, 20 GiB) yields 147 GiB.
        # Exercise that capacity with the real admission helper, before and
        # after creating the sparse disk that subsequent starts must preserve.
        self.c['stateGiB'] = 147
        for preserved in (False, True):
            if preserved:
                data = Path(self.c['dataDir']); data.mkdir(mode=0o700)
                home = data / 'home.raw'
                with home.open('wb') as f: f.truncate(147*w.GIB)
                home.chmod(0o600)
            for growth in (0, 2, 24, 40):
                with self.subTest(preserved=preserved, controller_growth_gib=growth), \
                     patch.object(w.shutil, 'disk_usage', return_value=SimpleNamespace(
                         total=256*w.GIB, free=(220-growth)*w.GIB)):
                    result = w.disk_admission(self.c, self.manifest, owner=os.geteuid())
                    self.assertEqual(result['requiredBytes'], 175*w.GIB)
            # Consumable growth headroom is finite: do not overcommit the
            # worker or spend the last 8 GiB once the budget is exhausted.
            with patch.object(w.shutil, 'disk_usage', return_value=SimpleNamespace(
                    total=256*w.GIB, free=175*w.GIB-1)):
                with self.assertRaises(w.Refusal):
                    w.disk_admission(self.c, self.manifest, owner=os.geteuid())

    def test_wrong_size_or_interrupted_home_is_not_repaired(self):
        data=Path(self.c['dataDir']);data.mkdir(mode=0o700)
        home=data/'home.raw';home.write_bytes(b'user data');home.chmod(0o600)
        with self.assertRaises(w.Refusal): self.admit(100*w.GIB)
        self.assertEqual(home.read_bytes(),b'user data')
        home.unlink();(data/'home.raw.new').write_bytes(b'interrupted')
        with self.assertRaises(w.Refusal): self.admit(100*w.GIB)

    def test_symlinked_directory_or_state_refuses(self):
        data=Path(self.c['dataDir']);data.symlink_to(self.temp.name)
        with self.assertRaises(w.Refusal): self.admit(100*w.GIB)
        data.unlink();data.mkdir(mode=0o700)
        (data/'home.raw').symlink_to('/etc/passwd')
        with self.assertRaises(w.Refusal): self.admit(100*w.GIB)

    def test_writable_directory_refuses(self):
        data=Path(self.c['dataDir']);data.mkdir(mode=0o700);data.chmod(0o777)
        with self.assertRaises(w.Refusal): self.admit(100*w.GIB)


class PlacementContracts(unittest.TestCase):
    def test_all_components_have_valid_explicit_placement(self):
        spec=importlib.util.spec_from_file_location('catalog',ROOT/'scripts/component_catalog.py')
        catalog=importlib.util.module_from_spec(spec);spec.loader.exec_module(catalog)
        rows=catalog.read_catalog()
        for row in rows:
            for key in ('controllerAllowed','workerAllowed','requiresWorker'):
                self.assertIs(type(row[key]),bool)
        by_id={r['id']:r for r in rows}
        for id in ('codex','claude-code','grok','antigravity-cli','cursor-agent','opencode','pi','omp'):
            self.assertTrue(by_id[id]['workerAllowed']);self.assertFalse(by_id[id]['controllerAllowed'])
        self.assertFalse(by_id['chatgpt-desktop']['requiresWorker'])
        self.assertFalse(by_id['claude-desktop']['requiresWorker'])
        self.assertTrue(by_id['claude-desktop']['controllerAllowed'])

    def test_rust_capabilities_match_catalog(self):
        source=(ROOT/'crates/functional-core/assbox-domain/src/component_ids.rs').read_text()
        for method,field in [('controller_allowed','controllerAllowed'),('worker_allowed','workerAllowed'),('requires_worker','requiresWorker')]:
            body=source.split('pub const fn '+method+'(self) -> bool {',1)[1].split('\n    }',1)[0]
            for row in json.loads((ROOT/'catalog/components.json').read_text()):
                variant=''.join(s.capitalize() for s in row['id'].split('-'))
                self.assertIn(f'Self::{variant} => {str(row[field]).lower()},',body)

    def test_controller_has_no_supported_placement_override(self):
        source=(ROOT/'modules/controller.nix').read_text()
        self.assertIn('cfg.kiosk.localExecution != "managed-worker" || cfg.worker.enable',source)
        self.assertIn('absence leaves the selected client inactive',source)
        self.assertIn('row.controllerAllowed',source)
        self.assertNotIn('enforcePlacement',source)
        source=(ROOT/'modules/worker/default.nix').read_text()
        self.assertNotIn('!cfg.enforcePlacement ||',source)
        self.assertIn('row.workerAllowed',source)

    def test_post_build_admission_precedes_all_publication(self):
        source=(ROOT/'crates/imperative-shell/assbox-engine/src/manage.rs').read_text()
        body=source.split('fn commit(',1)[1].split('fn fail_before_activation',1)[0]
        self.assertLess(body.index('admit_candidate'),body.index('journal(Phase::Published)'))
        install=(ROOT/'crates/imperative-shell/assbox-engine/src/install.rs').read_text()
        self.assertLess(install.index('admit_install'),install.index('"activating", Some(&system)'))

    def test_timer_quiesces_only_after_receipt_or_valid_receipt_reuse(self):
        source=(ROOT/'crates/imperative-shell/assbox-engine/src/manage.rs').read_text()
        body=source.split('fn boot_check_with_retry',1)[1].split('pub fn components_set',1)[0]
        self.assertEqual(body.count('quiesce_boot_retry'),2)
        self.assertGreater(body.rindex('quiesce_boot_retry'),body.index('files::atomic_write(Path::new(BOOT_ACCEPTED)'))

    def test_installation_renders_managed_worker_not_another_installer(self):
        source=(ROOT/'crates/functional-core/assbox-config/src/lib.rs').read_text()
        self.assertIn('worker::selection(&rendered, Some(spec))',source)
        wizard=(ROOT/'crates/imperative-shell/assbox-cli/src/wizard.rs').read_text()
        self.assertIn('installation_spec',wizard)
        self.assertIn('plan.root().bytes',wizard)

class QualifiedInterfaces(unittest.TestCase):
    def test_native_effective_sshd_gate_is_release_required(self):
        for path in ['flake.nix','scripts/release-check']:
            self.assertIn('worker-sshd-policy-vm',(ROOT/path).read_text())
        self.assertIn('guest.config.environment.etc."ssh/sshd_config".source',
                      (ROOT/'nix/worker-image.nix').read_text())
        self.assertIn('policy.sshdConfig',
                      (ROOT/'tests/nix/worker-sshd-policy-vm.nix').read_text())

    def test_native_policy_parser_preserves_repeated_values(self):
        spec=importlib.util.spec_from_file_location('native_sshd',ROOT/'tests/worker/native-sshd-policy.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        output='allowusers agent\nallowusers assbox-health\nforcecommand none\n'
        with patch.object(module.subprocess,'run',return_value=SimpleNamespace(stdout=output)) as command:
            fields=module.effective('/bin/sshd','/etc/example','agent')
        self.assertEqual(fields['allowusers'],'agent assbox-health')
        self.assertIn('-T',command.call_args.args[0])
        self.assertIn('-C',command.call_args.args[0])

    def test_every_exported_worker_profile_gets_separate_guest_audit(self):
        release=(ROOT/'scripts/release-check').read_text()
        loop=release.split('for system in "${systems[@]}";',1)[1].split('\ndone',1)[0]
        self.assertIn('config.assbox.worker.enable',loop)
        self.assertIn('system.build.assboxWorkerAudit',loop)
        self.assertIn('vulnix "$worker_audit"',loop)

    def test_native_policy_parser_normalizes_directives_without_changing_values(self):
        spec=importlib.util.spec_from_file_location('native_sshd',ROOT/'tests/worker/native-sshd-policy.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        output='AllowUsers agent\nallowusers assbox-health\nForceCommand /nix/store/CaseSensitive/bin/HealthShell\n'
        with patch.object(module.subprocess,'run',return_value=SimpleNamespace(stdout=output)):
            fields=module.effective('/bin/sshd','/etc/example','agent')
        self.assertEqual(fields['allowusers'],'agent assbox-health')
        self.assertEqual(fields['forcecommand'],'/nix/store/CaseSensitive/bin/HealthShell')
