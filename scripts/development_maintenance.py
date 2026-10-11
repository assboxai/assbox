#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Trusted-base discovery and disposable candidate/native orchestration."""
from __future__ import annotations
import argparse
import base64
import datetime
import json
import os
from pathlib import Path
import platform
import subprocess
import tempfile
import uuid
from candidate_snapshot import capture, git, materialize
from development_maintenance_writer import (API, GATES, PATHS, REPOSITORY, SYSTEMS,
    candidate, canonical, digest, identities, load, require)

ROOT = Path(__file__).resolve().parents[1]


def atomic(path, value):
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    with temporary.open('xb') as stream:
        stream.write(canonical(value))
    temporary.chmod(0o600)
    temporary.replace(path)


def changed_output(value):
    channel = os.environ.get('GITHUB_OUTPUT')
    if channel:
        with open(channel, 'a') as stream:
            stream.write('changed=' + ('true' if value else 'false') + '\n')


def discover(output, job_name):
    require(os.environ.get('GITHUB_REPOSITORY') == REPOSITORY
            and os.environ.get('GITHUB_REF') == 'refs/heads/master'
            and os.environ.get('GITHUB_EVENT_NAME') in ('schedule', 'workflow_dispatch'), 'workflow admission')
    run, attempt = int(os.environ['GITHUB_RUN_ID']), int(os.environ['GITHUB_RUN_ATTEMPT'])
    base = os.environ['GITHUB_SHA']
    require(git(ROOT, 'rev-parse', 'HEAD').decode().strip() == base
            and not git(ROOT, 'status', '--porcelain'), 'trusted base checkout must be exact and clean')
    api = API(os.environ['GH_TOKEN'])
    repository = api.request('/repos/' + REPOSITORY)
    policy = load((ROOT / 'release/policy.json').read_bytes())
    require(repository['id'] == policy['repositoryId'] > 0
            and repository['owner']['id'] == policy['ownerId'] > 0, 'administration-required: canonical IDs unprovisioned')
    workflow = api.request(f'/repos/{REPOSITORY}/actions/runs/{run}/attempts/{attempt}')
    require(workflow['head_sha'] == base and workflow['run_attempt'] == attempt
            and workflow['path'] == '.github/workflows/maintenance.yml'
            and workflow['event'] == os.environ['GITHUB_EVENT_NAME'], 'workflow identity')
    jobs = []
    for page in range(1, 11):
        batch = api.request(f'/repos/{REPOSITORY}/actions/runs/{run}/attempts/{attempt}/jobs?per_page=100&page={page}')['jobs']
        jobs.extend(batch)
        if len(batch) < 100:
            break
    else:
        raise ValueError('job pagination bound')
    matches = [job for job in jobs if job['name'] == job_name and job['status'] == 'in_progress']
    require(len(matches) == 1 and type(matches[0]['id']) is int, 'numeric producer job unavailable or ambiguous')
    identity = dict(repository_id=repository['id'], owner_id=repository['owner']['id'],
        workflow_path='.github/workflows/maintenance.yml', run_id=run, run_attempt=attempt, job_id=matches[0]['id'])
    result = dict(base_commit=base, producer=identity)
    if job_name != 'Prepare candidate':
        matches = [j for j in jobs if j['name'] == 'Prepare candidate' and j['conclusion'] == 'success']
        require(len(matches) == 1, 'candidate producer missing')
        artifacts = []
        for page in range(1, 11):
            batch = api.request(f'/repos/{REPOSITORY}/actions/runs/{run}/artifacts?per_page=100&page={page}')['artifacts']
            artifacts.extend(batch)
            if len(batch) < 100:
                break
        else:
            raise ValueError('artifact pagination bound')
        name = f'maintenance-candidate-{attempt}'
        artifacts = [a for a in artifacts if a['name'] == name and a['workflow_run']['id'] == run
                     and a['workflow_run']['head_sha'] == base]
        require(len(artifacts) == 1, 'candidate artifact unavailable or ambiguous')
        envelope = api.artifact(artifacts[0], 'candidate.json')
        require(envelope['producer'] == {**identity, 'job_id': matches[0]['id']}
                and envelope['base_commit'] == base, 'stale candidate producer')
        atomic(output.parent / 'candidate.json', envelope)
        result['artifact_id'] = artifacts[0]['id']
    atomic(output, result)


def safe_environment(state, oracle):
    env = {k: os.environ[k] for k in ('PATH', 'LANG', 'LC_ALL', 'SSL_CERT_FILE', 'NIX_SSL_CERT_FILE') if k in os.environ}
    for name in ('home', 'cache', 'tmp', 'state'):
        (state / name).mkdir(mode=0o700, exist_ok=True)
    env.update(HOME=str(state / 'home'), XDG_CACHE_HOME=str(state / 'cache'), TMPDIR=str(state / 'tmp'),
               XDG_STATE_HOME=str(state / 'state'), ASSBOX_ORACLE_SOURCE=str(oracle))
    return env


def execute(command, source, state, oracle):
    marker = uuid.uuid4().hex
    print('::stop-commands::' + marker, flush=True)
    try:
        subprocess.run(command, cwd=source, env=safe_environment(state, oracle),
                       stdin=subprocess.DEVNULL, close_fds=True, check=True)
    finally:
        print('::' + marker + '::', flush=True)


def frozen_base(state, identity):
    require(git(ROOT, 'rev-parse', 'HEAD').decode().strip() == identity['base_commit']
            and not git(ROOT, 'status', '--porcelain'), 'base drift')
    files, _ = capture(ROOT)
    materialize(files, state / 'oracle')
    return files, load(files['development/maintenance-policy.json'][1]), load(files['development/candidate-snapshot-policy.json'][1])


def prepare(discovery, output):
    identity = load(discovery.read_bytes())
    state = Path(tempfile.mkdtemp(prefix='assbox-maintenance-', dir=discovery.parent))
    base, policy, snapshot_policy = frozen_base(state, identity)
    materialize(base, state / 'candidate')
    # Documented public update interface; no private transaction-cache parser.
    execute(['nix', 'run', 'path:./nix/dev#just', '--', 'deps-update', 'commit=off'], state / 'candidate', state, state / 'oracle')
    changed, _ = capture(state / 'candidate')
    require(set(changed) == set(base), 'candidate changed source membership')
    replacements = []
    for path in sorted(base):
        if changed[path] == base[path]:
            continue
        require(path in PATHS and base[path][0] == changed[path][0] == '100644', 'unapproved candidate output')
        raw = changed[path][1]
        replacements.append(dict(path=path, mode='100644', old_sha256=digest(base[path][1]),
            new_sha256=digest(raw), bytes=len(raw), content_base64=base64.b64encode(raw).decode()))
    if not replacements:
        atomic(output.parent / 'summary.json', dict(schema=1, status='no-change', base_commit=identity['base_commit']))
        changed_output(False)
        return
    receipt = identities(changed, snapshot_policy)
    envelope = dict(schema=1, kind='development-maintenance-candidate', base_commit=identity['base_commit'],
        producer=identity['producer'], replacements=replacements, candidate_snapshot=receipt,
        candidate_content_sha256=receipt['source_content_sha256'], production_lock_sha256=digest(base['flake.lock'][1]),
        dev_lock_sha256=digest(changed['nix/dev/flake.lock'][1]), chainman_revision=changed['chainman.lock'][1].decode().strip(),
        policy_sha256=digest(canonical(policy)), gate_set_sha256=digest(canonical(list(GATES))),
        oracle_sha256=identities(base, snapshot_policy)['source_content_sha256'])
    candidate(base, envelope, policy)
    atomic(output, envelope)
    changed_output(True)


def native(discovery, envelope_path, output, system):
    require(system in SYSTEMS and platform.system() == 'Linux'
            and platform.machine() == ('x86_64' if system == 'x86_64-linux' else 'aarch64'), 'native architecture required')
    identity, envelope = load(discovery.read_bytes()), load(envelope_path.read_bytes())
    state = Path(tempfile.mkdtemp(prefix='assbox-native-', dir=discovery.parent))
    base, policy, snapshot_policy = frozen_base(state, identity)
    require(envelope['base_commit'] == identity['base_commit'], 'mixed base')
    files = candidate(base, envelope, policy)
    receipt = materialize(files, state / 'candidate', snapshot_policy)
    require(receipt == envelope['candidate_snapshot'], 'native snapshot mismatch')
    started = datetime.datetime.now(datetime.timezone.utc).isoformat()
    # The finite full coordinator dispatches these four stages and one fresh driver.
    execute(['nix', 'run', 'path:./nix/dev#just', '--', 'verify'], state / 'candidate', state, state / 'oracle')
    summaries = list((state / 'state/assbox/verification').glob('candidate-*/summary.json'))
    require(len(summaries) == 1, 'full verification receipt unavailable')
    summary = load(summaries[0].read_bytes())
    require(summary['status'] == 'passed' and summary['candidate_snapshot'] == receipt
            and summary.get('canonical_summary_sha256'), 'full gate incomplete')
    canonical_run = load((summaries[0].parent / 'canonical-summary.json').read_bytes())
    require(digest((summaries[0].parent / 'canonical-summary.json').read_bytes()) == summary['canonical_summary_sha256'], 'canonical receipt changed')
    after, _ = capture(state / 'candidate')
    require(after == files, 'native candidate drift')
    keys = ('base_commit', 'candidate_content_sha256', 'production_lock_sha256', 'dev_lock_sha256',
            'chainman_revision', 'policy_sha256', 'gate_set_sha256', 'oracle_sha256', 'candidate_snapshot')
    report = {key: envelope[key] for key in keys}
    report.update(schema=1, kind='development-maintenance-native-report', status='passed', system=system,
        accelerator=canonical_run['accelerator'],
        producer=identity['producer'], gates=[dict(name=g, status='passed') for g in GATES],
        canonical_summary_sha256=summary['canonical_summary_sha256'], started_at=started,
        finished_at=datetime.datetime.now(datetime.timezone.utc).isoformat())
    atomic(output, report)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    p = commands.add_parser('discover'); p.add_argument('output', type=Path); p.add_argument('job')
    p = commands.add_parser('prepare'); p.add_argument('discovery', type=Path); p.add_argument('output', type=Path)
    p = commands.add_parser('native'); p.add_argument('discovery', type=Path); p.add_argument('envelope', type=Path)
    p.add_argument('output', type=Path); p.add_argument('system')
    args = parser.parse_args()
    if args.command == 'discover': discover(args.output, args.job)
    elif args.command == 'prepare': prepare(args.discovery, args.output)
    else: native(args.discovery, args.envelope, args.output, args.system)


if __name__ == '__main__':
    main()
