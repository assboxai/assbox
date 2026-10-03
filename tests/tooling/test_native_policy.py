# SPDX-License-Identifier: GPL-3.0-or-later
"""Pure contract fixtures, never native account or Linux enforcement evidence."""
import copy, importlib.util, sys, tempfile, unittest
from unittest.mock import patch
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('native_policy',ROOT/'scripts/native/policy.py')
policy=importlib.util.module_from_spec(spec);spec.loader.exec_module(policy)
class NativePolicyTests(unittest.TestCase):
    def test_read_only_status_classifies_mixed_and_stale_observations(self):
        row,_,_=self.fixture()
        config={'apps':{'chatgpt-desktop':row},'maximumAgeSeconds':45}
        boot=Path('/proc/sys/kernel/random/boot_id').read_text().strip()
        record={'state':'verified','scope':policy.scope(row),'boot':boot,'observed':90}
        with patch.object(policy,'probe_observation',side_effect=AssertionError('status must never probe')):
            self.assertEqual(policy.status('claude-desktop',config)['state'],'unavailable')
            self.assertEqual(policy.status('chatgpt-desktop',config,'managed-worker')['state'],'stale')
            with patch.object(policy,'trusted_json',side_effect=FileNotFoundError):
                self.assertEqual(policy.status('chatgpt-desktop',config)['state'],'pending')
            with patch.object(policy,'trusted_json',return_value=record),patch.object(policy.time,'monotonic',return_value=100):
                self.assertEqual(policy.status('chatgpt-desktop',config)['state'],'verified')
                record['observed']=0
                self.assertEqual(policy.status('chatgpt-desktop',config)['state'],'stale')
                record['state']='ineffective'
                self.assertEqual(policy.status('chatgpt-desktop',config)['state'],'ineffective')
    def test_probe_output_is_bounded_before_json_parsing(self):
        row,_,_=self.fixture()
        with tempfile.TemporaryDirectory() as directory:
            probe=Path(directory)/'probe'
            probe.write_text(f'#!{sys.executable}\nimport os\nos.write(1,b"x"*100000)\n')
            probe.chmod(0o700)
            with self.assertRaisesRegex(policy.Refusal,'output bound'):policy.probe_observation(probe,row)
    def test_probe_reads_only_its_private_request(self):
        row,_,_=self.fixture()
        with tempfile.TemporaryDirectory() as directory:
            probe=Path(directory)/'probe'
            probe.write_text(f'#!{sys.executable}\nimport os\nprint(os.environ["ASSBOX_NATIVE_REQUEST"])\n')
            probe.chmod(0o700)
            self.assertEqual(policy.probe_observation(probe,row),row)
    def fixture(self):
        row={'client':'/nix/store/fixture/bin/chatgpt','platform':'x86_64-linux','mode':'none','cloud':False,'localCowork':False,'providerVmContract':None,'contract':{'id':'fixture','accountScopeDigest':'a'*64}}
        qualification={'app':'chatgpt-desktop','contract':'fixture','client':row['client'],'platform':row['platform'],'accountScopeDigest':'a'*64,'status':'passed'}
        observation=qualification|{'policyRequestDigest':policy.scope(row),'effectivePolicyDigest':'b'*64,'surfaces':dict.fromkeys(policy.SURFACES['chatgpt-desktop'],'denied')}
        return row,qualification,observation
    def test_complete_matching_none_contract(self):
        row,q,o=self.fixture();policy.validate_observation('chatgpt-desktop',row,o,q)
    def test_each_local_surface_is_independent(self):
        row,q,o=self.fixture()
        for surface in ['codex-local','work-local','work-cloud-local-access','computer-use','local-helpers','browser','codex-ssh','cloud-only']:
            bad=copy.deepcopy(o);bad['surfaces'][surface]='restricted'
            with self.subTest(surface=surface),self.assertRaises(policy.Refusal):policy.validate_observation('chatgpt-desktop',row,bad,q)
    def test_account_build_inventory_and_request_changes_revoke(self):
        row,q,o=self.fixture()
        for key in ['accountScopeDigest','client','platform','contract','policyRequestDigest','effectivePolicyDigest']:
            bad=copy.deepcopy(o);bad[key]='changed'
            with self.subTest(key=key),self.assertRaises(policy.Refusal):policy.validate_observation('chatgpt-desktop',row,bad,q)
        bad=copy.deepcopy(o);bad['surfaces']['new-local-surface']='denied'
        with self.assertRaises(policy.Refusal):policy.validate_observation('chatgpt-desktop',row,bad,q)
    def test_worker_does_not_supply_work_or_local_permission(self):
        row,q,o=self.fixture();row['mode']='managed-worker';o['policyRequestDigest']=policy.scope(row)
        with self.assertRaises(policy.Refusal):policy.validate_observation('chatgpt-desktop',row,o,q)
        o['surfaces']['codex-ssh']='remote-only';policy.validate_observation('chatgpt-desktop',row,o,q)
        o['surfaces']['work-local']='restricted'
        with self.assertRaises(policy.Refusal):policy.validate_observation('chatgpt-desktop',row,o,q)
if __name__=='__main__':unittest.main()
