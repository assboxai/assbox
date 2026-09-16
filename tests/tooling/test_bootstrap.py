# SPDX-License-Identifier: GPL-3.0-or-later
"""Executable checks of the maintenance evidence boundary and bounded writer."""
import ast
import base64
import copy
import json
import io
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts'))
import bootstrap as b

ENV = {'GITHUB_REPOSITORY': 'assboxai/assbox', 'GITHUB_REF': 'refs/heads/master',
       'GITHUB_EVENT_NAME': 'schedule', 'GITHUB_SHA': 'a' * 40, 'GITHUB_RUN_ID': '42', 'GITHUB_RUN_ATTEMPT': '1'}


def lock(revision):
    names = b.data.INPUTS
    nodes = {'root': {'inputs': {n: n for n in names}}}
    for name in names:
        nodes[name] = {'locked': {'type': 'github', 'owner': 'fixture', 'repo': name,
            'rev': revision * 40, 'narHash': 'sha256-' + 'A' * 43 + '='},
            'original': {'type': 'github', 'owner': 'fixture', 'repo': name}}
    return b.data.json_bytes({'version': 7, 'root': 'root', 'nodes': nodes})


class BootstrapTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, ENV, clear=True); self.env.start(); self.addCleanup(self.env.stop)
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); self.assets = self.root / 'assets'; self.assets.mkdir()
        self.reports = self.root / 'reports'; self.reports.mkdir()
        self.current, self.candidate = lock('b'), lock('c')
        (self.assets / 'current.lock').write_bytes(self.current)
        (self.assets / 'candidate.lock').write_bytes(self.candidate)
        self.value = {'schema': 1, **b.identity(), 'origin': 'authenticated-release', 'releaseTag': 'r-2',
            'currentSha256': b.data.digest(self.current), 'candidateSha256': b.data.digest(self.candidate)}
        self.save_plan(); self.save_reports()

    def save_plan(self):
        (self.assets / 'plan.json').write_bytes(b.data.json_bytes(self.value))

    def save_reports(self, candidate=True, current=True):
        for variant in b.VARIANTS:
            for system in b.data.SYSTEMS:
                passed = candidate if variant == 'candidate' else current
                report = {'schema': 1, **b.identity(), 'variant': variant, 'system': system,
                    'planSha256': b.data.digest((self.assets / 'plan.json').read_bytes()),
                    'lockSha256': self.value[variant + 'Sha256'], 'passed': passed,
                    'gates': list(b.GATES) if passed else []}
                (self.reports / f'{variant}-{system}.json').write_bytes(b.data.json_bytes(report))

    def mutate_report(self, key, value):
        path = sorted(self.reports.iterdir())[0]
        report = json.loads(path.read_text()); report[key] = value
        path.write_bytes(b.data.json_bytes(report))

    def test_candidate_requires_both_native_architectures(self):
        self.assertEqual(b.select(self.assets, self.reports)[1], self.candidate)
        self.save_reports(candidate=False)
        self.assertEqual(b.select(self.assets, self.reports)[1], self.current)

    def test_each_native_result_is_independent_and_required(self):
        for variant in b.VARIANTS:
            for system in b.data.SYSTEMS:
                with self.subTest(variant=variant, system=system):
                    self.save_reports()
                    path = self.reports / f'{variant}-{system}.json'
                    report = json.loads(path.read_text())
                    report.update(passed=False, gates=[])
                    path.write_bytes(b.data.json_bytes(report))
                    selected = b.select(self.assets, self.reports)[1]
                    self.assertEqual(selected, self.current if variant == 'candidate' else self.candidate)
                    path.unlink()
                    with self.assertRaises(ValueError): b.select(self.assets, self.reports)

    def test_boolean_and_float_schema_versions_are_not_integer_versions(self):
        for schema in [True, 1.0, '1', None, 2]:
            with self.subTest(schema=schema):
                self.value['schema'] = schema; self.save_plan()
                with self.assertRaises(ValueError): b.plan(self.assets)
                self.value['schema'] = 1; self.save_plan(); self.save_reports()
                self.mutate_report('schema', schema)
                with self.assertRaises(ValueError): b.select(self.assets, self.reports)

    def test_release_namespace_matches_publisher_and_client_bounds(self):
        for tag in ['r-1', 'r-9999999999999999']:
            self.assertEqual(b.release_sequence(tag), b.data.release_sequence(tag))
        for tag in ['r-10000000000000000', 'r-0', 'r-01', 'r--1', 'r-1\n', '', None]:
            with self.assertRaises(ValueError): b.release_sequence(tag)

    def test_no_unverified_keepalive(self):
        self.save_reports(candidate=False, current=False)
        with self.assertRaises(ValueError): b.select(self.assets, self.reports)

    def test_invalid_evidence_prevents_every_writer_effect(self):
        self.mutate_report('runId', 'wrong-run')
        with patch.object(b, 'observe_repository') as observe, patch.object(b.rel, 'api') as api, \
                patch.object(b, 'compare_and_swap') as cas:
            with self.assertRaises(ValueError): b.write(self.assets, self.reports)
            observe.assert_not_called(); api.assert_not_called(); cas.assert_not_called()

    def test_missing_evidence_is_not_a_failed_optional_check(self):
        next(self.reports.iterdir()).unlink()
        with self.assertRaises(ValueError): b.select(self.assets, self.reports)

    def test_duplicate_evidence_is_rejected(self):
        (self.reports / 'duplicate.json').write_bytes(next(self.reports.iterdir()).read_bytes())
        with self.assertRaises(ValueError): b.select(self.assets, self.reports)

    def test_mismatched_identity_digest_architecture_and_gates(self):
        cases = [('baseSha', 'd' * 40), ('runId', '43'), ('runAttempt', '2'),
            ('planSha256', '0' * 64), ('lockSha256', '0' * 64), ('system', 'cross-aarch64-linux'),
            ('gates', list(b.GATES)[:-1]), ('gates', list(b.GATES) + ['claimed-extra']), ('passed', 1)]
        for key, value in cases:
            with self.subTest(key=key, value=value):
                self.save_reports(); self.mutate_report(key, value)
                with self.assertRaises(ValueError): b.select(self.assets, self.reports)

    def test_plan_cannot_be_reused_by_rerun(self):
        with patch.dict(os.environ, {'GITHUB_RUN_ATTEMPT': '2'}):
            with self.assertRaises(ValueError): b.select(self.assets, self.reports)

    def test_symlinked_locks_and_unexpected_artifacts_are_rejected(self):
        path = self.assets / 'candidate.lock'; path.unlink(); path.symlink_to(self.assets / 'current.lock')
        with self.assertRaises((ValueError, OSError)): b.plan(self.assets)
        path.unlink(); path.write_bytes(self.candidate)
        (self.assets / 'extra').write_text('unreviewed')
        with self.assertRaises(ValueError): b.plan(self.assets)

    def test_existing_lock_origin_cannot_smuggle_a_changed_lock(self):
        self.value.update(origin='existing', releaseTag=None); self.save_plan()
        with self.assertRaises(ValueError): b.plan(self.assets)

    def test_no_candidate_process_with_ambient_token(self):
        with patch.object(b.rel, 'API_TOKEN', 'ephemeral'):
            with self.assertRaises(ValueError): b.tokenless()
        with patch.object(b.rel, 'API_TOKEN', None), patch.dict(os.environ, {'ACTIONS_ID_TOKEN_REQUEST_TOKEN': 'ambient'}):
            with self.assertRaises(ValueError): b.tokenless()

    def test_writer_source_has_no_candidate_execution(self):
        tree = ast.parse(Path(b.__file__).read_text())
        writer = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'write')
        calls = [ast.unparse(n.func) for n in ast.walk(writer) if isinstance(n, ast.Call)]
        self.assertFalse(any(name.startswith('subprocess.') or name in {'rel.run', 'native', 'prepare', 'exec', 'eval'} for name in calls))

    def test_tree_shape_is_exact_not_recursive_or_truncated(self):
        for value in ({'truncated': True, 'tree': []}, {'truncated': False, 'tree': [
            {'path': 'sub/flake.lock', 'mode': '100644', 'type': 'blob', 'sha': 'b' * 40}]}):
            with self.assertRaises(ValueError): b.tree_entries(value)

    def writer_api(self, other_change=False):
        base, tree, blob, new_tree, new_commit = ('a' * 40, 'd' * 40, 'e' * 40, 'f' * 40, '1' * 40)
        before = [{'path': 'flake.lock', 'mode': '100644', 'type': 'blob', 'sha': '2' * 40},
                  {'path': 'README.md', 'mode': '100644', 'type': 'blob', 'sha': '3' * 40}]
        after = copy.deepcopy(before); after[0]['sha'] = blob
        if other_change: after[1]['sha'] = '4' * 40
        def api(path, payload=None, token=False):
            self.assertTrue(token)
            suffix = path.split('/git/', 1)[1]
            if suffix == 'commits/' + base: return {'tree': {'sha': tree}}
            if suffix == 'trees/' + tree: return {'truncated': False, 'tree': before}
            if suffix == 'blobs/' + '2' * 40:
                return {'encoding': 'base64', 'content': base64.b64encode(self.current).decode()}
            if suffix == 'blobs':
                self.assertEqual(base64.b64decode(payload['content']), self.candidate); return {'sha': blob}
            if suffix == 'trees':
                self.assertEqual(payload, {'base_tree': tree, 'tree': [{'path': 'flake.lock', 'mode': '100644', 'type': 'blob', 'sha': blob}]})
                return {'sha': new_tree}
            if suffix == 'trees/' + new_tree: return {'truncated': False, 'tree': after}
            if suffix == 'commits':
                self.assertEqual(payload['parents'], [base]); return {'sha': new_commit, 'tree': {'sha': payload['tree']}, 'parents': [{'sha': base}]}
            self.fail('unexpected Git operation ' + suffix)
        return api

    def test_writer_only_changes_lock_and_uses_exact_cas(self):
        with patch.object(b, 'observe_repository', return_value={'node_id': 'fixture-node'}) as observe, \
                patch.object(b.rel, 'api', side_effect=self.writer_api()), patch.object(b, 'compare_and_swap') as cas:
            b.write(self.assets, self.reports)
            self.assertEqual(observe.call_count, 2)
            cas.assert_called_once_with('fixture-node', 'a' * 40, '1' * 40)

    def test_writer_refuses_other_source_changes(self):
        with patch.object(b, 'observe_repository', return_value={'node_id': 'fixture-node'}), \
                patch.object(b.rel, 'api', side_effect=self.writer_api(other_change=True)), patch.object(b, 'compare_and_swap') as cas:
            with self.assertRaises(ValueError): b.write(self.assets, self.reports)
            cas.assert_not_called()

    def test_master_moving_before_ref_update_cannot_publish(self):
        with patch.object(b, 'observe_repository', side_effect=[{'node_id': 'fixture-node'}, ValueError('master moved')]), \
                patch.object(b.rel, 'api', side_effect=self.writer_api()), patch.object(b, 'compare_and_swap') as cas:
            with self.assertRaises(ValueError): b.write(self.assets, self.reports)
            cas.assert_not_called()

    def test_empty_keepalive_preserves_tree(self):
        self.candidate = self.current
        (self.assets / 'candidate.lock').write_bytes(self.current)
        self.value.update(origin='existing', releaseTag=None, candidateSha256=b.data.digest(self.current))
        self.save_plan(); self.save_reports()
        with patch.object(b, 'observe_repository', return_value={'node_id': 'fixture-node'}), \
                patch.object(b.rel, 'api', side_effect=self.writer_api()) as api, patch.object(b, 'compare_and_swap'):
            b.write(self.assets, self.reports)
            paths = [call.args[0] for call in api.call_args_list]
            self.assertFalse(any(path.endswith('/blobs') or path.endswith('/trees') for path in paths))

    def test_compare_and_swap_is_exact_nonforcing_and_does_not_retry_uncertain_results(self):
        mutation_id = 'assbox-bootstrap-42-1'
        success = {'data': {'updateRefs': {'clientMutationId': mutation_id}}}
        replies = [success, {'errors': [{'message': 'stale head'}]}, {}, None, [],
                   {'data': None}, {'data': {'updateRefs': None}},
                   {'data': {'updateRefs': {'clientMutationId': 'wrong-run'}}}]
        for reply in replies:
            with self.subTest(reply=reply), patch.object(b.rel, 'API_TOKEN', 'test-only-token'), \
                    patch.object(b.urllib.request, 'build_opener') as factory:
                opener = factory.return_value
                opener.open.return_value = io.BytesIO(b.data.json_bytes(reply))
                if reply == success:
                    b.compare_and_swap('repository-node', 'a' * 40, 'b' * 40)
                else:
                    with self.assertRaises(ValueError): b.compare_and_swap('repository-node', 'a' * 40, 'b' * 40)
                opener.open.assert_called_once()
                request = opener.open.call_args.args[0]
                self.assertEqual(request.full_url, 'https://api.github.com/graphql')
                self.assertEqual(json.loads(request.data)['variables']['input'], {
                    'repositoryId': 'repository-node', 'clientMutationId': mutation_id,
                    'refUpdates': [{'name': 'refs/heads/master', 'beforeOid': 'a' * 40,
                                    'afterOid': 'b' * 40, 'force': False}]})
                factory.assert_called_once_with(b.rel.NoRedirect)


if __name__ == '__main__': unittest.main()
