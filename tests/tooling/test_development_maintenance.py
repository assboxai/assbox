# SPDX-License-Identifier: GPL-3.0-or-later
import ast
import base64
import copy
import json
from pathlib import Path
import sys
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
import development_maintenance as controller
import development_maintenance_writer as writer
import development_maintenance_status as monitor
import development_maintenance_inspect as inspector
import workflow_policy


def fixture():
    base = {name: ('100644', (ROOT / name).read_bytes()) for name in (
        'flake.lock', 'nix/dev/flake.lock', 'chainman.lock', 'development/maintenance-policy.json',
        'development/candidate-snapshot-policy.json')}
    base['ordinary.txt'] = '100755', b'whole source remains core\n'
    policy = writer.load(base['development/maintenance-policy.json'][1])
    snapshot_policy = writer.load(base['development/candidate-snapshot-policy.json'][1])
    changed = dict(base)
    changed['chainman.lock'] = '100644', b'b' * 40 + b'\n'
    receipt = writer.identities(changed, snapshot_policy)
    producer = dict(repository_id=123, owner_id=456, workflow_path='.github/workflows/maintenance.yml',
        run_id=10, run_attempt=2, job_id=100)
    raw = changed['chainman.lock'][1]
    envelope = dict(schema=1, kind='development-maintenance-candidate', base_commit='a' * 40,
        candidate_content_sha256=receipt['source_content_sha256'], production_lock_sha256=writer.digest(base['flake.lock'][1]),
        dev_lock_sha256=writer.digest(base['nix/dev/flake.lock'][1]), chainman_revision='b' * 40,
        policy_sha256=writer.digest(writer.canonical(policy)), gate_set_sha256=writer.digest(writer.canonical(list(writer.GATES))),
        oracle_sha256=writer.identities(base, snapshot_policy)['source_content_sha256'], candidate_snapshot=receipt,
        producer=producer, replacements=[dict(path='chainman.lock', mode='100644', bytes=len(raw),
            old_sha256=writer.digest(base['chainman.lock'][1]), new_sha256=writer.digest(raw), content_base64=base64.b64encode(raw).decode())])
    reports = []
    for index, system in enumerate(writer.SYSTEMS):
        report = {k: envelope[k] for k in ('base_commit', 'candidate_content_sha256', 'production_lock_sha256',
            'dev_lock_sha256', 'chainman_revision', 'policy_sha256', 'gate_set_sha256', 'oracle_sha256', 'candidate_snapshot')}
        report.update(schema=1, kind='development-maintenance-native-report', status='passed', system=system,
            accelerator='kvm' if index == 0 else 'tcg', producer={**producer, 'job_id': 200 + index},
            gates=[dict(name=g, status='passed') for g in writer.GATES], canonical_summary_sha256='c' * 64,
            started_at='2026-10-02T00:00:00Z', finished_at='2026-10-02T01:00:00Z')
        reports.append(report)
    return base, changed, policy, envelope, reports


class Maintenance(unittest.TestCase):
    def test_protocol_examples_match_committed_schemas_and_local_inspection_grants_no_authority(self):
        import tempfile
        from jsonschema import Draft202012Validator
        from referencing import Registry, Resource
        from candidate_snapshot import materialize
        schemas = {p.name: json.loads(p.read_bytes()) for p in (ROOT / 'development').glob('*.schema.json')}
        registry = Registry().with_resources((name, Resource.from_contents(value)) for name, value in schemas.items())
        base, _, _, envelope, reports = fixture()
        Draft202012Validator(schemas['maintenance-envelope.schema.json'], registry=registry).validate(envelope)
        for report in reports:
            Draft202012Validator(schemas['maintenance-report.schema.json'], registry=registry).validate(report)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            materialize(base, root / 'base')
            (root / 'candidate.json').write_bytes(writer.canonical(envelope))
            paths = [root / ('report-%d.json' % index) for index in range(2)]
            for path, report in zip(paths, reports): path.write_bytes(writer.canonical(report))
            result = inspector.inspect(root / 'base', root / 'candidate.json', paths)
            self.assertEqual(result['status'], 'structurally-valid')
            self.assertFalse(result['write_authorized'])
            self.assertEqual(result['provenance'], 'unverified-local-evidence')

    def test_valid_whole_source_candidate_and_both_native_reports(self):
        base, changed, policy, envelope, reports = fixture()
        self.assertEqual(writer.candidate(base, envelope, policy), changed)
        writer.native_reports(envelope, reports, 10, 2, dict(zip(writer.SYSTEMS, (200, 201))))

    def test_envelope_rejects_outputs_modes_sizes_duplicates_and_false_identities(self):
        base, _, policy, envelope, _ = fixture()
        mutations = [
            lambda e: e.update(schema=True), lambda e: e.update(extra='ignored'),
            lambda e: e['replacements'][0].update(path='flake.lock'),
            lambda e: e['replacements'][0].update(mode='100755'),
            lambda e: e['replacements'][0].update(bytes=True),
            lambda e: e['replacements'][0].update(content_base64='../escape'),
            lambda e: e['replacements'].append(copy.deepcopy(e['replacements'][0])),
            lambda e: e.update(oracle_sha256='d' * 64), lambda e: e.update(production_lock_sha256='d' * 64),
            lambda e: e['candidate_snapshot'].update(git_tree_oid='e' * 40),
            lambda e: e['candidate_snapshot'].update(synthetic_commit_oid='e' * 40),
            lambda e: e['producer'].update(job_id=True),
            lambda e: e['producer'].update(workflow_path='.github/workflows/release.yml'),
        ]
        for mutate in mutations:
            with self.subTest(mutation=mutate):
                bad = copy.deepcopy(envelope); mutate(bad)
                with self.assertRaises((ValueError, KeyError)): writer.candidate(base, bad, policy)

    def test_reports_refuse_missing_cancelled_stale_mixed_system_and_gate_evidence(self):
        _, _, _, envelope, reports = fixture()
        jobs = dict(zip(writer.SYSTEMS, (200, 201)))
        with self.assertRaises(ValueError): writer.native_reports(envelope, reports[:1], 10, 2, jobs)
        mutations = [lambda r: r.update(status='cancelled'), lambda r: r.update(system='x86_64-linux'),
            lambda r: r['producer'].update(run_attempt=1), lambda r: r['producer'].update(job_id=200),
            lambda r: r['producer'].update(repository_id=999), lambda r: r.update(candidate_content_sha256='f' * 64),
            lambda r: r.update(oracle_sha256='f' * 64), lambda r: r.update(gates=r['gates'][:-1]),
            lambda r: r.update(canonical_summary_sha256=None), lambda r: r.update(extra='ignored'),
            lambda r: r.update(started_at=[]), lambda r: r.update(finished_at='2025-01-01T00:00:00Z')]
        for mutate in mutations:
            with self.subTest(mutation=mutate):
                bad = copy.deepcopy(reports); mutate(bad[1])
                with self.assertRaises(ValueError): writer.native_reports(envelope, bad, 10, 2, jobs)

    def test_json_duplicate_keys_nonfinite_and_oversize_refuse(self):
        for raw in (b'{"schema":1,"schema":1}', b'{"x":NaN}', b' ' * (writer.LIMIT + 1)):
            with self.assertRaises(ValueError): writer.load(raw)

    def test_readonly_monitor_never_equates_success_with_applied_or_skipped_with_pass(self):
        self.assertEqual(monitor.outcome(False)['status'], 'disabled')
        self.assertEqual(monitor.outcome(True, {'id': 1, 'status': 'completed', 'conclusion': 'success'})['status'], 'incomplete')
        self.assertEqual(monitor.outcome(True, {'id': 1, 'status': 'completed', 'conclusion': 'skipped'})['status'], 'failed')
        self.assertEqual(monitor.outcome(True, summary={'status': 'no-change'})['status'], 'no-change')

    def test_signed_artifact_download_never_forwards_authorization_and_rejects_other_hosts(self):
        import io
        import urllib.error
        import zipfile
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, 'w', zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('candidate.json', b'{"schema":1}\n')
        raw = stream.getvalue()
        metadata = dict(id=123, expired=False, size_in_bytes=len(raw), digest='sha256:' + writer.digest(raw))
        api = writer.API('disposable-token')
        requests = []
        class Redirect:
            def open(self, request, timeout):
                requests.append(request)
                raise urllib.error.HTTPError(request.full_url, 302, 'signed redirect', {'Location': 'https://fixture.blob.core.windows.net/artifact?signature=disposable'}, None)
        class Download:
            def open(self, request, timeout):
                requests.append(request)
                return io.BytesIO(raw)
        api.opener = Redirect()
        with mock.patch.object(writer.urllib.request, 'build_opener', return_value=Download()):
            self.assertEqual(api.artifact(metadata, 'candidate.json'), {'schema': 1})
        self.assertIsNotNone(requests[0].get_header('Authorization'))
        self.assertIsNone(requests[1].get_header('Authorization'))
        class Hostile:
            def open(self, request, timeout):
                raise urllib.error.HTTPError(request.full_url, 302, 'redirect', {'Location': 'https://evil.example/artifact'}, None)
        api.opener = Hostile()
        with self.assertRaises(ValueError): api.artifact(metadata, 'candidate.json')

    def test_writer_has_no_project_imports_children_or_actions(self):
        tree = ast.parse((ROOT / 'scripts/development_maintenance_writer.py').read_text())
        imports = [node.names[0].name if isinstance(node, ast.Import) else node.module
                   for node in ast.walk(tree) if isinstance(node, (ast.Import, ast.ImportFrom))]
        self.assertFalse(set(imports) & {'subprocess', 'candidate_snapshot', 'development_maintenance'})
        calls = [ast.unparse(node.func) for node in ast.walk(tree) if isinstance(node, ast.Call)]
        self.assertFalse(set(calls) & {'os.system', 'os.execve', 'eval', 'exec', 'pickle.loads'})
        job = workflow_policy.development_document()['jobs']['write']
        self.assertNotIn('uses', job)
        self.assertFalse(any('uses' in step for step in job['steps']))
        self.assertTrue(job['steps'][0]['run'].startswith('/usr/bin/python3 -I -B'))

    def test_authority_stencil_refuses_all_permission_dag_and_enablement_mutations(self):
        good = workflow_policy.development_document()
        self.assertEqual(workflow_policy.check_document('maintenance.yml', good), [])
        mutations = [lambda d: d.update(permissions={'contents': 'read'}),
            lambda d: d['jobs']['prepare']['permissions'].pop('actions'),
            lambda d: d['jobs']['native']['permissions'].pop('actions'),
            lambda d: d['jobs']['write']['permissions'].pop('actions'),
            lambda d: d['jobs']['write']['permissions'].update(actions='write'),
            lambda d: d['jobs']['prepare'].pop('if'), lambda d: d['jobs']['write'].update(if_='always()'),
            lambda d: d['jobs']['write'].update(needs='prepare'),
            lambda d: d['jobs']['write'].update(environment='release-automation'),
            lambda d: d['jobs']['write']['steps'].insert(0, {'uses': workflow_policy.CHECKOUT}),
            lambda d: d['jobs']['write']['steps'][0]['env'].pop('MAINTENANCE_READY'),
            lambda d: d['on'].update(workflow_dispatch={'inputs': {'override': {}}}),
            lambda d: d['jobs']['write'].update(container='python:latest')]
        for mutate in mutations:
            bad = copy.deepcopy(good); mutate(bad)
            self.assertTrue(workflow_policy.check_document('maintenance.yml', bad))

    def test_candidate_environment_does_not_inherit_authority_or_runner_channels(self):
        import tempfile
        dangerous = {'GH_TOKEN': 'private', 'ACTIONS_RUNTIME_TOKEN': 'private', 'SSH_AUTH_SOCK': '/secret',
                     'GITHUB_OUTPUT': '/runner/channel', 'GITHUB_ENV': '/runner/channel', 'NIX_CONFIG': 'include /secret'}
        with tempfile.TemporaryDirectory() as directory, mock.patch.dict(controller.os.environ, dangerous):
            env = controller.safe_environment(Path(directory), Path(directory) / 'oracle')
        self.assertFalse(set(dangerous) & set(env))

    def test_exact_cas_once_and_readonly_reconciliation(self):
        base, changed, policy, envelope, _ = fixture()
        metadata = {'tree': {'sha': writer.identities(base, {})['git_tree_oid']}}
        commit = '9' * 40
        class Fake:
            def __init__(self, ambiguous=False, moved=False): self.calls=[]; self.head=envelope['base_commit']; self.ambiguous=ambiguous; self.moved=moved
            def request(self, path, body=None, method=None):
                self.calls.append((path, body))
                if path.endswith('/ref/heads/master'): return {'object': {'sha': '8' * 40 if self.moved else self.head}}
                if path.endswith('/blobs'): return {'sha': writer.oid('blob', changed['chainman.lock'][1])}
                if path.endswith('/trees'): return {'sha': envelope['candidate_snapshot']['git_tree_oid']}
                if path.endswith('/commits') or path.endswith('/commits/' + commit):
                    return {'sha': commit, 'tree': {'sha': envelope['candidate_snapshot']['git_tree_oid']}, 'parents': [{'sha': envelope['base_commit']}]}
                if path == '/graphql':
                    self.head=commit
                    if self.ambiguous: raise OSError('lost response')
                    return {'data': {'updateRefs': {'clientMutationId': None}}}
                raise AssertionError(path)
        for ambiguous in (False, True):
            api = Fake(ambiguous=ambiguous)
            self.assertEqual(writer.apply(api, metadata, changed, envelope, 'canonical-node'), commit)
            writes = [body for path, body in api.calls if path == '/graphql']
            self.assertEqual(len(writes), 1)
            self.assertEqual(writes[0]['variables']['updates'], [{'name': 'refs/heads/master', 'beforeOid': envelope['base_commit'], 'afterOid': commit, 'force': False}])
        api = Fake(moved=True)
        with self.assertRaises(ValueError): writer.apply(api, metadata, changed, envelope, 'canonical-node')
        self.assertFalse(any(body for _, body in api.calls))
