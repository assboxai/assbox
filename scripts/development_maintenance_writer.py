#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Standalone trusted-base writer. Standard library only; never launches children."""
from __future__ import annotations
import base64
import datetime
import hashlib
import io
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
import zipfile

REPOSITORY = 'assboxai/assbox'
PATHS = ('chainman.lock', 'nix/dev/flake.lock')
SYSTEMS = ('x86_64-linux', 'aarch64-linux')
GATES = ('verify-lite', 'verify-mutations', 'verify-production-candidate', 'verify-canonical')
LIMIT = 4 * 1024 * 1024


def require(condition, message):
    if not condition:
        raise ValueError(message)


def canonical(value):
    return (json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
                       allow_nan=False) + '\n').encode()


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def oid(kind, raw):
    return hashlib.sha1(kind.encode() + b' ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()


def object_pairs(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, 'duplicate JSON key')
        result[key] = value
    return result


def load(raw):
    require(len(raw) <= LIMIT, 'JSON exceeds bound')
    return json.loads(raw.decode('utf-8'), object_pairs_hook=object_pairs,
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError('nonfinite JSON')))


def safe_path(path):
    require(isinstance(path, str) and path and not path.startswith('/') and '\\' not in path
            and all(ord(c) >= 32 and ord(c) != 127 for c in path)
            and all(p not in ('', '.', '..', '.git') for p in path.split('/')), 'unsafe path')
    return path


def fields(value, expected, label):
    require(isinstance(value, dict) and set(value) == set(expected.split()), 'invalid ' + label + ' fields')


def producer(value):
    fields(value, 'repository_id owner_id workflow_path run_id run_attempt job_id', 'producer')
    require(value['workflow_path'] == '.github/workflows/maintenance.yml', 'wrong workflow')
    require(all(type(value[k]) is int and value[k] > 0 for k in value if k != 'workflow_path'), 'invalid producer identity')


def envelope_shape(value):
    fields(value, 'schema kind base_commit candidate_content_sha256 production_lock_sha256 dev_lock_sha256 chainman_revision policy_sha256 gate_set_sha256 oracle_sha256 producer replacements candidate_snapshot', 'envelope')
    require(type(value['schema']) is int and value['schema'] == 1 and value['kind'] == 'development-maintenance-candidate', 'unsupported envelope')
    for key in ('base_commit', 'chainman_revision'):
        require(isinstance(value[key], str) and re.fullmatch('[0-9a-f]{40}', value[key]), 'invalid Git identity')
    for key in ('candidate_content_sha256', 'production_lock_sha256', 'dev_lock_sha256', 'policy_sha256', 'gate_set_sha256', 'oracle_sha256'):
        require(isinstance(value[key], str) and re.fullmatch('[0-9a-f]{64}', value[key]), 'invalid digest')
    producer(value['producer'])
    require(isinstance(value['replacements'], list), 'invalid replacements')


def identities(files, snapshot_policy):
    manifest = [{'path': path, 'mode': mode, 'sha256': digest(raw)}
                for path, (mode, raw) in sorted(files.items(), key=lambda item: item[0].encode())]
    root = {}
    for path, (mode, raw) in files.items():
        safe_path(path)
        require(mode in ('100644', '100755'), 'unsupported source mode')
        node = root
        parts = path.split('/')
        for part in parts[:-1]:
            node = node.setdefault(part, {})
            require(isinstance(node, dict), 'source prefix collision')
        require(parts[-1] not in node, 'duplicate source path')
        node[parts[-1]] = (mode, oid('blob', raw))
    def tree(node):
        records = bytearray()
        for name, entry in sorted(node.items(), key=lambda i: (i[0] + ('/' if isinstance(i[1], dict) else '')).encode()):
            mode, value = ('40000', tree(entry)) if isinstance(entry, dict) else entry
            records.extend(mode.encode() + b' ' + name.encode() + b'\0' + bytes.fromhex(value))
        return oid('tree', bytes(records))
    tree_oid = tree(root)
    commit = (f'tree {tree_oid}\nauthor Assbox Candidate <candidate@assbox.invalid> 946684800 +0000\n'
              'committer Assbox Candidate <candidate@assbox.invalid> 946684800 +0000\n\n'
              'Assbox verification snapshot v1\n').encode()
    return dict(schema=1, kind='candidate-snapshot-identity', protocol='assbox-candidate-snapshot-v1',
        policy_sha256=digest(canonical(snapshot_policy)), source_content_sha256=digest(canonical(manifest)),
        git_tree_oid=tree_oid, synthetic_commit_oid=oid('commit', commit), git_object_format='sha1',
        parents=[], publishable=False)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class API:
    def __init__(self, token):
        require(isinstance(token, str) and re.fullmatch(r'[A-Za-z0-9._~+/-]+={0,2}', token), 'API token unavailable')
        self.token = token
        self.opener = urllib.request.build_opener(NoRedirect())

    def request(self, path, body=None, method=None):
        require(path.startswith('/') and not path.startswith('//') and '\n' not in path, 'invalid API path')
        request = urllib.request.Request('https://api.github.com' + path,
            data=None if body is None else canonical(body), method=method,
            headers={'Authorization': 'Bearer ' + self.token, 'Accept': 'application/vnd.github+json',
                     'Content-Type': 'application/json', 'X-GitHub-Api-Version': '2022-11-28'})
        with self.opener.open(request, timeout=30) as response:
            raw = response.read(LIMIT + 1)
        return load(raw)

    def artifact(self, artifact, filename):
        artifact_id = artifact['id']
        require(type(artifact_id) is int and artifact_id > 0 and not artifact.get('expired'), 'invalid artifact identity')
        require(re.fullmatch(r'sha256:[0-9a-f]{64}', artifact.get('digest', '')), 'artifact digest unavailable')
        require(type(artifact['size_in_bytes']) is int and 0 < artifact['size_in_bytes'] <= LIMIT, 'artifact size bound')
        path = f'/repos/{REPOSITORY}/actions/artifacts/{artifact_id}/zip'
        request = urllib.request.Request('https://api.github.com' + path,
                                        headers={'Authorization': 'Bearer ' + self.token})
        try:
            self.opener.open(request, timeout=30)
            raise ValueError('artifact redirect required')
        except urllib.error.HTTPError as error:
            require(error.code == 302, 'artifact authorization or transport failed')
            url = error.headers.get('Location', '')
        parsed = urllib.parse.urlsplit(url)
        host = parsed.hostname or ''
        require(parsed.scheme == 'https' and not parsed.username and not parsed.password
                and parsed.port in (None, 443) and not parsed.fragment
                and (host.endswith('.blob.core.windows.net')
                     or host == 'results-receiver.actions.githubusercontent.com'), 'unapproved artifact host')
        # A separate request contains no API credentials and permits no further redirects.
        with urllib.request.build_opener(NoRedirect()).open(urllib.request.Request(url), timeout=60) as response:
            raw = response.read(LIMIT + 1)
        require(len(raw) <= LIMIT and digest(raw) == artifact['digest'][7:], 'artifact bytes differ')
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            entries = archive.infolist()
            require(len(entries) == 1 and entries[0].filename == filename, 'unexpected artifact entries')
            item = entries[0]
            require(item.file_size <= LIMIT and item.compress_size > 0
                    and item.file_size <= item.compress_size * 200
                    and (item.external_attr >> 16) & 0o170000 in (0, 0o100000), 'unsafe artifact entry')
            return load(archive.read(item))


def base_files(api, commit):
    require(re.fullmatch('[0-9a-f]{40}', commit), 'invalid base commit')
    prefix = f'/repos/{REPOSITORY}/git'
    metadata = api.request(prefix + '/commits/' + commit)
    require(metadata['sha'] == commit, 'base commit mismatch')
    tree = api.request(prefix + '/trees/' + metadata['tree']['sha'] + '?recursive=1')
    require(not tree.get('truncated') and len(tree['tree']) <= 4096, 'source tree unavailable or too large')
    files = {}
    total = 0
    for item in tree['tree']:
        safe_path(item['path'])
        if item['type'] == 'tree':
            require(item['mode'] == '040000', 'invalid directory mode')
            continue
        require(item['type'] == 'blob' and item['mode'] in ('100644', '100755'), 'unsupported base source')
        blob = api.request(prefix + '/blobs/' + item['sha'])
        require(blob['encoding'] == 'base64', 'unsupported blob encoding')
        raw = base64.b64decode(''.join(blob['content'].split()), validate=True)
        require(oid('blob', raw) == item['sha'] and len(raw) == blob['size'], 'base blob mismatch')
        total += len(raw)
        require(total <= 128 * 1024 * 1024 and len(raw) <= 16 * 1024 * 1024, 'base source size bound')
        require(item['path'] not in files, 'duplicate base path')
        files[item['path']] = item['mode'], raw
    require(identities(files, {})['git_tree_oid'] == metadata['tree']['sha'], 'base tree mismatch')
    return metadata, files


def candidate(base, envelope, policy):
    envelope_shape(envelope)
    replacements = envelope['replacements']
    require(1 <= len(replacements) <= 2, 'empty or oversized candidate')
    result = dict(base)
    seen = set()
    for replacement in replacements:
        fields(replacement, 'path mode content_base64 bytes old_sha256 new_sha256', 'replacement')
        path = replacement['path']
        require(path in PATHS and path not in seen and path in base, 'unapproved or duplicate replacement')
        seen.add(path)
        require(replacement['mode'] == base[path][0] == '100644', 'replacement mode changed')
        require(isinstance(replacement['content_base64'], str) and len(replacement['content_base64']) <= 1398104, 'replacement encoding bound')
        require(type(replacement['bytes']) is int, 'invalid replacement size')
        raw = base64.b64decode(replacement['content_base64'], validate=True)
        require(base64.b64encode(raw).decode() == replacement['content_base64'], 'noncanonical base64')
        require(0 < len(raw) <= 1048576 and len(raw) == replacement['bytes'], 'replacement size mismatch')
        require(digest(base[path][1]) == replacement['old_sha256'] and digest(raw) == replacement['new_sha256'], 'replacement hash mismatch')
        require(raw != base[path][1], 'unchanged replacement')
        result[path] = '100644', raw
    require(re.fullmatch(rb'[0-9a-f]{40}\n', result['chainman.lock'][1]), 'invalid runtime pin')
    dev = load(result['nix/dev/flake.lock'][1])
    previous = load(base['nix/dev/flake.lock'][1])
    require(type(dev['version']) is int and type(previous['version']) is int
            and dev['version'] == previous['version'] == 7 and dev['nodes']['root'] == previous['nodes']['root']
            and set(dev['nodes']) == set(previous['nodes']) == {'root', 'nixpkgs'}, 'dev input ownership changed')
    require(set(dev) == {'nodes', 'root', 'version'} and dev['root'] == previous['root'] == 'root', 'dev root changed')
    node = dev['nodes']['nixpkgs']
    require(set(node) == {'locked', 'original'} and node['original'] == previous['nodes']['nixpkgs']['original'], 'dev input declaration changed')
    require(set(node['locked']) == {'lastModified', 'narHash', 'owner', 'repo', 'rev', 'type'}
            and node['locked']['type'] == 'github' and node['locked']['owner'] == 'NixOS'
            and node['locked']['repo'] == 'nixpkgs' and type(node['locked']['lastModified']) is int
            and node['locked']['lastModified'] > 0
            and re.fullmatch('[0-9a-f]{40}', node['locked']['rev'])
            and re.fullmatch('sha256-[A-Za-z0-9+/]{43}=', node['locked']['narHash']), 'invalid locked Nixpkgs')
    snapshot_policy = load(base['development/candidate-snapshot-policy.json'][1])
    receipt = identities(result, snapshot_policy)
    require(receipt == envelope['candidate_snapshot'] and receipt['source_content_sha256'] == envelope['candidate_content_sha256'], 'candidate snapshot mismatch')
    require(digest(base['flake.lock'][1]) == envelope['production_lock_sha256'], 'production lock mismatch')
    require(digest(result['nix/dev/flake.lock'][1]) == envelope['dev_lock_sha256']
            and result['chainman.lock'][1].decode().strip() == envelope['chainman_revision'], 'dependency identity mismatch')
    require(digest(canonical(policy)) == envelope['policy_sha256']
            and digest(canonical(list(GATES))) == envelope['gate_set_sha256'], 'trusted policy/gate mismatch')
    require(identities(base, snapshot_policy)['source_content_sha256'] == envelope['oracle_sha256'], 'trusted oracle mismatch')
    return result


def native_reports(envelope, reports, run, attempt, jobs):
    require(len(reports) == 2, 'both native reports required')
    seen = set()
    for report in reports:
        fields(report, 'schema kind status system accelerator base_commit candidate_content_sha256 production_lock_sha256 dev_lock_sha256 chainman_revision policy_sha256 gate_set_sha256 oracle_sha256 candidate_snapshot producer gates canonical_summary_sha256 started_at finished_at', 'native report')
        require(type(report['schema']) is int and report['schema'] == 1
                and report['kind'] == 'development-maintenance-native-report', 'unsupported report')
        producer(report['producer'])
        system = report['system']
        require(system in SYSTEMS and system not in seen, 'wrong or duplicate native system')
        require(report['accelerator'] in ('kvm', 'tcg')
                and (system != 'x86_64-linux' or report['accelerator'] == 'kvm'), 'unsupported native accelerator')
        seen.add(system)
        require(report['status'] == 'passed' and isinstance(report['canonical_summary_sha256'], str)
                and re.fullmatch('[0-9a-f]{64}', report['canonical_summary_sha256']), 'native gate incomplete')
        require(report['gates'] == [{'name': name, 'status': 'passed'} for name in GATES], 'required gates missing')
        dates = []
        for key in ('started_at', 'finished_at'):
            require(isinstance(report[key], str) and len(report[key]) <= 40, 'invalid native timestamp')
            value = datetime.datetime.fromisoformat(report[key].replace('Z', '+00:00'))
            require(value.tzinfo is not None and value.utcoffset() == datetime.timedelta(0), 'UTC native timestamp required')
            dates.append(value)
        require(dates[0] <= dates[1], 'native time order')
        for key in ('base_commit', 'candidate_content_sha256', 'production_lock_sha256', 'dev_lock_sha256',
                    'chainman_revision', 'policy_sha256', 'gate_set_sha256', 'oracle_sha256', 'candidate_snapshot'):
            require(report[key] == envelope[key], 'mixed native candidate or oracle')
        identity = report['producer']
        require(identity['run_id'] == run and identity['run_attempt'] == attempt
                and identity['job_id'] == jobs[system]
                and identity['repository_id'] == envelope['producer']['repository_id']
                and identity['owner_id'] == envelope['producer']['owner_id'], 'stale or wrong producer job')


def apply(api, metadata, files, envelope, repository_node):
    prefix = f'/repos/{REPOSITORY}/git'
    base = envelope['base_commit']
    require(api.request(prefix + '/ref/heads/master')['object']['sha'] == base, 'base-moved')
    updates = []
    for replacement in envelope['replacements']:
        raw = files[replacement['path']][1]
        blob = api.request(prefix + '/blobs', {'content': base64.b64encode(raw).decode(), 'encoding': 'base64'})
        require(blob['sha'] == oid('blob', raw), 'created blob mismatch')
        updates.append({'path': replacement['path'], 'mode': '100644', 'type': 'blob', 'sha': blob['sha']})
    tree = api.request(prefix + '/trees', {'base_tree': metadata['tree']['sha'], 'tree': updates})
    require(tree['sha'] == envelope['candidate_snapshot']['git_tree_oid'], 'created tree mismatch')
    commit = api.request(prefix + '/commits', {'message': 'chore: verified development dependencies',
                                             'tree': tree['sha'], 'parents': [base]})
    checked = api.request(prefix + '/commits/' + commit['sha'])
    require(checked['tree']['sha'] == tree['sha'] and [p['sha'] for p in checked['parents']] == [base], 'created commit mismatch')
    print('Created bounded commit ' + commit['sha'], flush=True)
    mutation = {'query': 'mutation($repository:ID!,$updates:[RefUpdate!]!){updateRefs(input:{repositoryId:$repository,refUpdates:$updates}){clientMutationId}}',
                'variables': {'repository': repository_node, 'updates': [{'name': 'refs/heads/master',
                    'beforeOid': base, 'afterOid': commit['sha'], 'force': False}]}}
    try:
        response = api.request('/graphql', mutation)
        require(not response.get('errors'), 'ref update refused')
    except (ValueError, OSError, urllib.error.URLError):
        observed = api.request(prefix + '/ref/heads/master')['object']['sha']
        require(observed == commit['sha'], 'uncertain ref outcome; inspect created commit; no write retry')
    require(api.request(prefix + '/ref/heads/master')['object']['sha'] == commit['sha'], 'ref changed after write; inspect')
    return commit['sha']


def main():
    require(os.environ.get('MAINTENANCE_READY') == 'provisioned-v1', 'administration-required')
    require(os.environ.get('MAINTENANCE_ENABLED') == 'enabled' and os.environ.get('REPOSITORY') == REPOSITORY
            and os.environ.get('REF') == 'refs/heads/master' and os.environ.get('EVENT') in ('schedule', 'workflow_dispatch'), 'workflow admission refused')
    base = os.environ['BASE']
    run, attempt = int(os.environ['RUN_ID']), int(os.environ['RUN_ATTEMPT'])
    api = API(os.environ['GH_TOKEN'])
    repository = api.request('/repos/' + REPOSITORY)
    metadata, files = base_files(api, base)
    policy = load(files['development/maintenance-policy.json'][1])
    release = load(files['release/policy.json'][1])
    require(repository['id'] == release['repositoryId'] > 0 and repository['owner']['id'] == release['ownerId'] > 0, 'repository administration required')
    workflow = api.request(f'/repos/{REPOSITORY}/actions/runs/{run}/attempts/{attempt}')
    require(workflow['id'] == run and workflow['run_attempt'] == attempt
            and workflow['head_sha'] == base and workflow['path'] == '.github/workflows/maintenance.yml'
            and workflow['event'] == os.environ['EVENT'], 'workflow identity mismatch')
    jobs = []
    for page in range(1, 11):
        batch = api.request(f'/repos/{REPOSITORY}/actions/runs/{run}/attempts/{attempt}/jobs?per_page=100&page={page}')['jobs']
        jobs.extend(batch)
        if len(batch) < 100:
            break
    else:
        raise ValueError('job pagination bound')
    expected = {}
    for system in SYSTEMS:
        matches = [j for j in jobs if j['name'] == 'Native ' + system and j['conclusion'] == 'success']
        require(len(matches) == 1, 'native job missing or ambiguous')
        expected[system] = matches[0]['id']
    artifacts = []
    for page in range(1, 11):
        batch = api.request(f'/repos/{REPOSITORY}/actions/runs/{run}/artifacts?per_page=100&page={page}')['artifacts']
        artifacts.extend(batch)
        if len(batch) < 100:
            break
    else:
        raise ValueError('artifact pagination bound')
    def artifact(name, filename):
        matches = [a for a in artifacts if a['name'] == name and a['workflow_run']['id'] == run
                   and a['workflow_run']['head_sha'] == base]
        require(len(matches) == 1, 'artifact missing or ambiguous')
        return api.artifact(matches[0], filename)
    envelope = artifact(f'maintenance-candidate-{attempt}', 'candidate.json')
    require(envelope['base_commit'] == base, 'envelope base mismatch')
    producer = envelope['producer']
    matches = [j for j in jobs if j['name'] == 'Prepare candidate' and j['conclusion'] == 'success']
    require(len(matches) == 1 and producer['job_id'] == matches[0]['id'] and producer['run_id'] == run
            and producer['run_attempt'] == attempt and producer['repository_id'] == repository['id']
            and producer['owner_id'] == repository['owner']['id'], 'producer identity mismatch')
    candidate_files = candidate(files, envelope, policy)
    reports = [artifact(f'maintenance-native-{system}-{attempt}', 'report.json') for system in SYSTEMS]
    native_reports(envelope, reports, run, attempt, expected)
    print(json.dumps({'status': 'applied', 'commit': apply(api, metadata, candidate_files, envelope, repository['node_id'])}))


if __name__ == '__main__':
    main()
