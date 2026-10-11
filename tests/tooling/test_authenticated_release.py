# SPDX-License-Identifier: GPL-3.0-or-later
"""Actual jq and publisher-policy tests; NOT cryptographic or native execution."""
from __future__ import annotations
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
import release as publisher
import release_data as data
from test_kernel_cache import publication_fixture


class AuthenticatedReleaseTests(unittest.TestCase):
    def setUp(self):
        self.source = (ROOT/'crates/imperative-shell/assbox-engine/src/release.rs').read_text()
        self.manifest = data.make_manifest('a'*40, '0.1.0', 1000, None, '1'*64, 'sha256-'+'A'*43+'=', '2'*64, [])

    def decode(self, name, value):
        decoder = re.search(r'const '+name+r': &str = r#"(.*?)"#;', self.source, re.S).group(1)
        decoder = decoder.replace('@HELD_CHECK@', ' and '.join(f'. != \"{f}-packages\"' for f in data.APPLICATIONS))
        return subprocess.run(['jq', '-j', decoder], input=json.dumps(value), capture_output=True, text=True, check=False)

    def test_manifest_decoder_accepts_canonical_and_rejects_bad_schema_types(self):
        result = self.decode('MANIFEST_FIELDS', self.manifest)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(result.stdout[:-1].split('\0')), 14)
        for key, value in [('schema', '1'), ('protocol', True), ('issuedAt', '1000'), ('expiresAt', 1.5),
                           ('heldInputs', ['nixpkgs']), ('systems', ['x86_64-linux']), ('coreCommit', 123), ('extra', None)]:
            malformed = dict(self.manifest, **{key: value})
            self.assertNotEqual(self.decode('MANIFEST_FIELDS', malformed).returncode, 0, key)

    def test_provenance_decoder_requires_verified_certificate_extensions(self):
        cert = {'sourceRepositoryIdentifier':'10','sourceRepositoryOwnerIdentifier':'20',
                'sourceRepositoryDigest':'a'*40, 'buildTrigger':'workflow_dispatch'}
        good = [{'verificationResult': {'signature': {'certificate': cert}}}]
        self.assertEqual(self.decode('PROVENANCE_FIELDS', good).returncode, 0)
        for wrong in [[], good+good, [{'statement': {'predicate': cert}}],
                      [{'verificationResult': {'signature': {'certificate':dict(cert, sourceRepositoryIdentifier=None)}}}]]:
            self.assertNotEqual(self.decode('PROVENANCE_FIELDS', wrong).returncode, 0)

    def test_crypto_precedes_prefetch_and_policy_precedes_source_evaluation(self):
        self.assertLess(self.source.index('"verify-asset"'), self.source.index('let (manifest, manifest_bytes)'))
        self.assertLess(re.search(r'"attestation",\s*"verify"', self.source).start(), self.source.index('validate_release('))
        self.assertLess(self.source.index('validate_release('), self.source.index('"prefetch-file"'))
        for flag in ['--cert-identity','--source-ref','--source-digest','--signer-digest','--deny-self-hosted-runners']:
            self.assertIn(flag, self.source)
        self.assertIn('refs/heads/master', self.source)
        self.assertNotIn('"eval"', self.source)
        self.assertNotIn('"metadata"', self.source)
        management=(ROOT/'crates/imperative-shell/assbox-engine/src/manage.rs').read_text()
        self.assertLess(management.index('record_floor('), management.index('source::bind('))
        self.assertNotIn('"flake","update"', management)
        self.assertNotIn('"flake", "update"', management)

    def test_journal_records_all_release_files_before_writes_and_not_floor(self):
        source=(ROOT/'crates/imperative-shell/assbox-engine/src/manage.rs').read_text()
        commit=source[source.index('fn commit('):source.index('fn fail_before_activation')]
        self.assertLess(commit.index('"changed-files"'), commit.index('journal(Phase::Published)'))
        self.assertLess(commit.index('journal(Phase::Published)'), commit.index('for name in changed_files'))
        restore=source[source.index('fn restore_source'):source.index('pub fn status')]
        self.assertLess(restore.index('live != old && live != candidate'), restore.index('for (path, bytes)'))
        self.assertNotIn('record_floor', restore)

    def test_workflow_write_jobs_never_evaluate_candidate_nix(self):
        import yaml
        workflow=yaml.safe_load((ROOT/'.github/workflows/release.yml').read_text())
        for name in ['publish','advertise']:
            job=workflow['jobs'][name]
            self.assertEqual(job['environment'], 'release-automation')
            steps=json.dumps(job['steps'])
            self.assertNotIn('nix develop', steps); self.assertNotIn('install-nix', steps)
            self.assertNotIn('nix build', steps); self.assertNotIn('git push', steps)
        self.assertEqual(workflow['permissions'], {'contents':'read'})
        self.assertIn('live-verify', workflow['jobs']['advertise']['needs'])
        self.assertNotIn('environment', workflow['jobs']['live-verify'])
        self.assertEqual(workflow.get('on', workflow.get(True)), {'schedule': [{'cron': '23 4 * * *'}], 'workflow_dispatch': None})

    def test_publication_checks_immutability_and_never_sets_latest(self):
        with tempfile.TemporaryDirectory() as temp:
            assets=Path(temp); (assets/'release.sigstore.json').write_text('{}')
            # Extend the inputs for mandatory kernel publication; keep all
            # existing immutability/latest assertions below intact.
            manifest_bytes = data.json_bytes(self.manifest)
            (assets/'release.json').write_bytes(manifest_bytes)
            (assets/'flake.lock').write_bytes(b'contract-only lock')
            (assets/'assbox-source.tar.gz').write_bytes(b'contract-only source')
            for system in data.SYSTEMS:
                publication_fixture(assets, manifest_bytes, system)
            calls=[]
            def api(path, payload=None, **kwargs):
                calls.append((path,payload))
                if path.endswith('/releases'): return {'id':12}
                if path.endswith('/releases/12'): return {'immutable':True}
                return {}
            with patch.object(publisher,'ready',return_value=self.manifest), patch.object(publisher,'check_repository'), \
                 patch.object(publisher,'check_parent_head'), patch.object(publisher,'api',side_effect=api), patch.object(publisher,'run') as command, patch.object(publisher,'output'):
                publisher.publish(assets,Path(temp))
            self.assertEqual(command.call_args.args[:3],('gh','release','upload'))
            self.assertEqual(calls[0][1]['sha'], self.manifest['coreCommit'])
            self.assertTrue(calls[1][1]['draft']); self.assertFalse(calls[2][1]['draft'])
            for _,payload in calls:
                if 'make_latest' in payload: self.assertEqual(payload['make_latest'],'false')
            with patch.object(publisher,'ready',return_value=self.manifest), patch.object(publisher,'check_repository'), \
                 patch.object(publisher,'check_parent_head'), patch.object(publisher,'api',side_effect=[{}, {'id':12}, {'immutable':False}]), \
                 patch.object(publisher,'run'), patch.object(publisher,'output') as output:
                with self.assertRaises(ValueError): publisher.publish(assets,Path(temp))
                output.assert_not_called()

    def test_changed_kernel_asset_blocks_every_publication_write(self):
        with tempfile.TemporaryDirectory() as temp:
            assets=Path(temp)
            manifest_bytes=data.json_bytes(self.manifest)
            for name, content in [('release.json', manifest_bytes), ('release.sigstore.json', b'{}'),
                                  ('flake.lock', b'fixture'), ('assbox-source.tar.gz', b'fixture')]:
                (assets/name).write_bytes(content)
            for system in data.SYSTEMS:
                publication_fixture(assets, manifest_bytes, system)
            nar=next(assets.glob('kernel-x86_64-linux-*.nar.xz'))
            nar.write_bytes(nar.read_bytes()[:-1]+b'!')
            with patch.object(publisher, 'ready', return_value=self.manifest), \
                 patch.object(publisher, 'check_repository'), patch.object(publisher, 'write_api') as write, \
                 patch.object(publisher, 'run') as command:
                with self.assertRaisesRegex(ValueError, 'changed after attestation'):
                    publisher.publish(assets, assets)
                write.assert_not_called()
                command.assert_not_called()

    def test_promotion_requires_same_immutable_tag(self):
        for candidate in [{'immutable':False, 'tag_name':'r-1000','draft':False,'prerelease':False},
                          {'immutable':True,'tag_name':'other','draft':False,'prerelease':False}]:
            with patch.object(publisher,'core_tree'), patch.object(publisher,'check_repository'), patch.object(publisher,'api',return_value=candidate) as api:
                with self.assertRaises(ValueError): publisher.promote('r-1000','12')
                self.assertEqual(api.call_count,1)

    def test_ids_unprovisioned_fail_closed_not_fabricated(self):
        policy=json.loads((ROOT/'release/policy.json').read_text())
        self.assertEqual(policy['sourceRef'],'refs/heads/master')
        # Zero is an explicit bootstrap refusal, not a valid test identity.
        if policy['repositoryId']==0 or policy['ownerId']==0:
            with self.assertRaises(ValueError): publisher.policy()
        self.assertIn('policy.repository_id == 0 || policy.owner_id == 0',self.source)

    def test_tokenless_patch_changes_frontdoor_not_verification(self):
        nix=(ROOT/'nix/anonymous-gh.nix').read_text()
        self.assertIn('cmdutil.DisableAuthCheck(cmd)',nix)
        self.assertIn('--replace-fail',nix)
        self.assertIn('pkg/cmd/release/verify-asset/verify_asset.go',nix)
        self.assertNotIn('skipVerification',nix)
        commands=(ROOT/'crates/imperative-shell/assbox-system/src/commands.rs').read_text()
        self.assertIn('env_clear()',commands)
        self.assertIn('GH_CONFIG_DIR',commands)
        self.assertNotIn('env("GH_TOKEN"',commands)

if __name__=='__main__': unittest.main()
