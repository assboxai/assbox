# SPDX-License-Identifier: GPL-3.0-or-later
"""Execute history/publisher decisions. Mocked GitHub effects are not signatures."""
from __future__ import annotations
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import urllib.error

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
import release as publisher
import release_data as data
from test_release_data import lock, core


def manifest(now=1000, parent=None):
    return data.make_manifest('a' * 40, '0.1.0', now, parent, '1' * 64,
                              'sha256-' + 'A' * 43 + '=', data.digest(data.json_bytes(lock())), [])


def record(tag, number=None):
    return {'id': number or data.release_sequence(tag), 'tag_name': tag,
            'immutable': True, 'draft': False, 'prerelease': False}


def tag_record(tag):
    return {'name': tag, 'commit': {'sha': 'a' * 40}}


class ReleaseLineageTests(unittest.TestCase):
    def test_manifest_has_fixed_genesis_and_exact_canonical_parent_digest(self):
        first = manifest(); child = manifest(1100, first)
        self.assertEqual(first['tag'], 'r-1')
        self.assertIsNone(first['previousTag']); self.assertIsNone(first['previousManifestSha256'])
        self.assertEqual(child['previousTag'], 'r-1')
        self.assertEqual(child['previousManifestSha256'], data.digest(data.json_bytes(first)))
        data.require_parent(child, first, data.json_bytes(first))
        self.assertGreater(data.release_sequence(child['tag']), data.release_sequence(first['tag']))

    def test_schema_parent_pair_order_and_lifetime_fail_closed(self):
        first = manifest(); child = manifest(1100, first)
        for change in [{'schema': 1}, {'protocol': True}, {'previousTag': None},
                       {'previousManifestSha256': None}, {'previousTag': child['tag']},
                       {'previousTag': 'r-9999'}, {'previousManifestSha256': 'bad'},
                       {'expiresAt': child['issuedAt'] + 1}, {'extra': None}]:
            with self.assertRaises(ValueError, msg=change): data.validate_manifest(dict(child, **change))
        with self.assertRaises(ValueError): data.validate_manifest(dict(first, tag='r-2'))

    def test_parent_requires_original_canonical_bytes_not_parsed_claims(self):
        first = manifest(); child = manifest(1100, first)
        for raw in [None, data.json_bytes(first) + b' ', json.dumps(first).encode()]:
            with self.assertRaises(ValueError): data.require_parent(child, first, raw)
        with self.assertRaises(ValueError): data.require_parent(child, None, None)
        with self.assertRaises(ValueError): data.require_parent(dict(child, issuedAt=999, expiresAt=605799), first, data.json_bytes(first))
        wrong = dict(child, previousManifestSha256='9' * 64)
        with self.assertRaises(ValueError): data.require_parent(wrong, first, data.json_bytes(first))
        data.require_parent(first, None, None)

    def test_inventory_uses_numeric_history_not_order_or_latest(self):
        releases = [record('r-90'), record('r-1'), record('r-100')]
        tags = [tag_record('r-100'), tag_record('r-90'), tag_record('r-1')]
        self.assertEqual(data.history_head(releases, tags), (record('r-100'), 'r-90'))
        self.assertEqual(data.history_head([], []), (None, None))

    def test_orphans_deleted_genesis_and_conflicting_history_are_errors(self):
        records = [record('r-1'), record('r-100')]
        tags = [tag_record('r-1'), tag_record('r-100')]
        for releases, references in [(records[:1], tags), (records, tags[:1]),
                                     (records[1:], tags[1:]), (records + records[:1], tags),
                                     (records, tags + tags[:1]),
                                     ([{'tag_name': 'other'}], []), ([], [tag_record('other')])]:
            with self.assertRaises(ValueError): data.history_head(releases, references)
        for change in [{'immutable': False}, {'draft': True}, {'prerelease': True}, {'id': 0}]:
            with self.assertRaises(ValueError): data.history_head([records[0], dict(records[1], **change)], tags)

    def test_source_namespace_policy_matches_the_actual_monitor(self):
        # Exercise both implementations with the same API records. This comparison
        # concerns namespace selection/refusal, not cryptographic verification.
        releases = [record('r-1'), record('r-100')]
        tags = [tag_record('r-1'), tag_record('r-100')]
        source_release = {'tag_name': 'v0.1.0', 'id': 999, 'immutable': False}
        source_tag = {'name': 'v0.1.0'}
        cases = [
            (releases, tags, 'r-100'),
            (releases, tags + [source_tag], 'r-100'),
            ([source_release] + releases, tags, 'r-100'),
            ([source_release] + releases, tags + [source_tag], 'r-100'),
            ([source_release], [source_tag], None),
            (releases[1:], tags[1:] + [source_tag], None),
            (releases[:1] + [source_release], tags + [source_tag], None),
            (releases + [source_release], tags[:1] + [source_tag], None),
            (releases + [{'tag_name': 'r-invalid'}], tags, None),
            (releases, tags + [{'name': 'r-001'}], None),
            (releases + [{'tag_name': None}], tags, None),
            (releases, tags + [{'name': None}], None),
        ]
        source = f"""import {{ historyHead }} from {json.dumps((ROOT / 'infra/release-monitor/worker.mjs').as_uri())};
import {{ readFileSync }} from 'node:fs';
const cases = JSON.parse(readFileSync(0, 'utf8'));
console.log(JSON.stringify(cases.map(([releases, tags]) => {{
  try {{ return historyHead(releases, tags).tag_name; }} catch {{ return null; }}
}})));
"""
        result = subprocess.run(['node', '--input-type=module', '-e', source],
                                input=json.dumps(cases), text=True, capture_output=True, check=True, timeout=10)
        expected = [head for _, _, head in cases]
        self.assertEqual(json.loads(result.stdout), expected)
        for releases, tags, head in cases:
            with self.subTest(releases=releases, tags=tags):
                if head is None:
                    with self.assertRaises(ValueError): data.history_head(releases, tags)
                else:
                    self.assertEqual(data.history_head(releases, tags)[0]['tag_name'], head)
        # The monitor is unhealthy before any release. Only the publisher can
        # create r-1, and only from an entirely empty raw namespace.
        self.assertEqual(data.history_head([], []), (None, None))

    def test_inventory_paginates_and_refuses_incomplete_or_duplicate_pages(self):
        releases = [record(f'r-{number}') for number in range(1, 102)]
        tags = [tag_record(r['tag_name']) for r in releases]
        calls = []
        def api(path, **kwargs):
            calls.append(path)
            values = releases if '/releases?' in path else tags
            page = int(path.rsplit('page=', 1)[1])
            return values[(page - 1) * 100:page * 100]
        with patch.object(publisher, 'api', side_effect=api):
            self.assertEqual(publisher.inventory(), (record('r-101'), 'r-100'))
        self.assertEqual(len(calls), 4)
        self.assertTrue(all('/latest' not in path for path in calls))
        with patch.object(publisher, 'api', return_value={}):
            with self.assertRaises(ValueError): publisher.inventory()
        with patch.object(publisher, 'api', side_effect=[releases[:100], releases[:1], tags[:100], tags[100:]]):
            with self.assertRaises(ValueError): publisher.inventory()

    def test_discovery_and_resolution_have_separate_credential_lifetimes(self):
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp) / 'discovery.json'
            with patch.object(publisher, 'core_tree', return_value=('a' * 40, core())), \
                 patch.object(publisher, 'check_repository'), \
                 patch.object(publisher, 'inventory', return_value=(record('r-1100'), 'r-1')):
                publisher.discover(out)
            snapshot = data.decode(out.read_bytes())
            self.assertEqual(snapshot['head']['tag_name'], 'r-1100')
            with patch.object(publisher, 'API_TOKEN', 'fixture'), patch.object(publisher, 'run') as run:
                with self.assertRaises(ValueError): publisher.prepare(Path(temp) / 'plan', out)
                run.assert_not_called()

    def test_prepare_authenticates_selected_history_before_resolving_and_never_reads_latest(self):
        first = manifest(); parent = manifest(1100, first)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); discovery = root / 'discovery.json'
            discovery.write_bytes(data.json_bytes({'schema': 1, 'coreCommit': 'a' * 40,
                                                   'head': record(parent['tag']), 'previousTag': 'r-1'}))
            effects = []
            def run(*args, **kwargs):
                effects.append(args)
                if args[:2] == ('nix', 'build'): return b'/nix/store/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa-assbox\n'
                if args[0] == 'sudo' and args[1] != 'cat':
                    self.assertEqual(args[3:5], ('release-baseline', parent['tag']))
                    return b''
                if args[:2] == ('sudo', 'cat'):
                    return data.json_bytes(parent if args[2].endswith('release.json') else lock())
                if args[:3] == ('nix', 'flake', 'update'):
                    self.assertTrue(any(effect[:2] == ('sudo', 'cat') for effect in effects[:-1]))
                    return b''
                raise AssertionError(args)
            with patch.object(publisher, 'API_TOKEN', None), patch.dict(os.environ, {'GITHUB_RUN_ID': '42', 'GITHUB_RUN_ATTEMPT': '1'}), \
                 patch.object(publisher, 'core_tree', return_value=('a' * 40, core())), \
                 patch.object(publisher, 'api') as api, patch.object(publisher, 'run', side_effect=run):
                publisher.prepare(root / 'plan', discovery)
                api.assert_not_called()
            self.assertEqual(data.decode((root / 'plan/plan.json').read_bytes())['previous'], parent)

    def test_missing_head_authorization_never_falls_back_to_a_lower_release(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); discovery = root / 'discovery.json'
            discovery.write_bytes(data.json_bytes({'schema': 1, 'coreCommit': 'a' * 40,
                                                   'head': record('r-1100'), 'previousTag': 'r-1'}))
            def fail(*args, **kwargs):
                if args[:2] == ('nix', 'build'): return b'/nix/store/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa-assbox\n'
                raise subprocess.CalledProcessError(1, args)
            with patch.object(publisher, 'API_TOKEN', None), patch.dict(os.environ, {'GITHUB_RUN_ID': '42', 'GITHUB_RUN_ATTEMPT': '1'}), \
                 patch.object(publisher, 'core_tree', return_value=('a' * 40, core())), patch.object(publisher, 'run', side_effect=fail):
                with self.assertRaises(subprocess.CalledProcessError): publisher.prepare(root / 'plan', discovery)
            self.assertFalse((root / 'plan/plan.json').exists())

    def test_publication_rechecks_the_exact_predecessor_immediately_before_writes(self):
        first = manifest(); parent = manifest(1100, first); child = manifest(1200, parent)
        with patch.object(publisher, 'inventory', return_value=(record(parent['tag']), 'r-1')), \
             patch.object(publisher, 'public_manifest', return_value=data.json_bytes(parent)):
            publisher.check_parent_head(child)
        with patch.object(publisher, 'inventory', return_value=(record('r-1300'), parent['tag'])), \
             patch.object(publisher, 'public_manifest') as download:
            with self.assertRaises(ValueError): publisher.check_parent_head(child)
            download.assert_not_called()
        with patch.object(publisher, 'inventory', return_value=(None, None)):
            publisher.check_parent_head(first)
            with self.assertRaises(ValueError): publisher.check_parent_head(child)

    def test_advertising_an_old_rerun_is_refused_even_with_the_same_core_commit(self):
        calls = []
        def api(path, payload=None, **kwargs):
            calls.append((path, payload)); return record('r-1100', 12)
        with patch.object(publisher, 'core_tree'), patch.object(publisher, 'check_repository'), \
             patch.object(publisher, 'inventory', return_value=(record('r-1200', 13), 'r-1100')), \
             patch.object(publisher, 'api', side_effect=api):
            with self.assertRaises(ValueError): publisher.promote('r-1100', '12')
        self.assertFalse(any(payload is not None for _, payload in calls))

    def test_advertising_checks_backward_missing_and_forward_latest_hints(self):
        for hint, allowed in [(record('r-1'), True), (None, True), (record('r-1300'), False)]:
            calls = []
            def api(path, payload=None, **kwargs):
                calls.append((path, payload))
                if path.endswith('/latest'):
                    if hint is None: raise urllib.error.HTTPError('https://api.github.com/fixture', 404, 'missing', None, None)
                    return hint
                return record('r-1200', 12)
            with patch.object(publisher, 'core_tree'), patch.object(publisher, 'check_repository'), \
                 patch.object(publisher, 'inventory', return_value=(record('r-1200', 12), 'r-1100')), \
                 patch.object(publisher, 'api', side_effect=api):
                if allowed: publisher.promote('r-1200', '12')
                else:
                    with self.assertRaises(ValueError): publisher.promote('r-1200', '12')
            self.assertEqual(any(payload == {'make_latest': 'true'} for _, payload in calls), allowed)

    def test_child_processes_cannot_inherit_workflow_credentials(self):
        values = {key: 'fixture' for key in ['GH_TOKEN', 'GITHUB_TOKEN', 'ACTIONS_RUNTIME_TOKEN', 'ACTIONS_ID_TOKEN_REQUEST_TOKEN']}
        with patch.dict(os.environ, values), patch.object(publisher, 'API_TOKEN', 'fixture'):
            result = publisher.run(sys.executable, '-c', 'import os,json; print(json.dumps({k:os.getenv(k) for k in ' + repr(list(values)) + '}))')
            self.assertTrue(all(value is None for value in json.loads(result).values()))
            with self.assertRaises(ValueError): publisher.run('nix', 'build', github_upload=True)
        with patch.object(publisher, 'API_TOKEN', None):
            with self.assertRaises(ValueError): publisher.child_environment(github_upload=True)

    def test_api_credential_scope_and_redirect_refusal(self):
        with self.assertRaises(ValueError): publisher.api('/repos/assboxai/assbox-other')
        with patch.object(publisher, 'API_TOKEN', None):
            with self.assertRaises(ValueError): publisher.api('/repos/assboxai/assbox', token=True)
        with self.assertRaises(ValueError): publisher.NoRedirect().redirect_request(None, None, 302, '', {}, 'https://example.test')

    def test_workflow_has_exact_reviewed_triggers_and_both_live_architectures(self):
        import yaml
        w = yaml.safe_load((ROOT / '.github/workflows/release.yml').read_text())
        self.assertEqual(w['on'], {'schedule': [{'cron': '23 4 * * *'}], 'workflow_dispatch': None})
        jobs = w['jobs']
        matrix = jobs['live-verify']['strategy']['matrix']['include']
        self.assertEqual({v['system'] for v in matrix}, set(data.SYSTEMS))
        self.assertEqual({v['runner'] for v in matrix}, {'ubuntu-24.04', 'ubuntu-24.04-arm'})
        self.assertIn('live-verify', jobs['advertise']['needs'])
        steps = jobs['prepare']['steps']
        token_steps = [s for s in steps if 'GH_TOKEN' in s.get('env', {})]
        self.assertEqual(len(token_steps), 1)
        self.assertIn(' discover ', token_steps[0]['run'])
        self.assertNotIn('nix ', token_steps[0]['run'])
        resolution = next(s for s in steps if ' prepare ' in s.get('run', ''))
        self.assertNotIn('GH_TOKEN', resolution.get('env', {}))
        self.assertLess(steps.index(token_steps[0]), steps.index(resolution))

    def test_rust_routes_require_bootstrap_selection_and_check_ancestry_before_prefetch(self):
        text = (ROOT / 'crates/imperative-shell/assbox-engine/src/release.rs').read_text()
        fetch = text[text.index('pub(crate) fn fetch('):]
        self.assertLess(fetch.index('require_release_selection('), fetch.index('let policy = trust()'))
        self.assertLess(fetch.index('verify_lineage('), fetch.index('"prefetch-file"'))
        ancestor = text[text.index('fn verify_lineage('):text.index('pub(crate) fn fetch(')]
        self.assertLess(ancestor.index('parent_digest != previous.manifest_sha256'), ancestor.index('manifest_from_bytes('))
        cli = (ROOT / 'crates/imperative-shell/assbox-cli/src/wizard.rs').read_text()
        self.assertLess(cli.index('apply && release_tag.is_none()'), cli.index('files::require_root()'))


if __name__ == '__main__': unittest.main()
