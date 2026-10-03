#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Freeze once, run the complete native gate, and retain exact external evidence."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
from candidate_snapshot import ROOT, canonical, capture, digest, git, materialize, verify_files


def production_environment(state):
    allowed = ('PATH', 'LANG', 'LC_ALL', 'TERM', 'SSL_CERT_FILE', 'NIX_SSL_CERT_FILE', 'TZ')
    env = {k: os.environ[k] for k in allowed if k in os.environ}
    for name in ('home', 'tmp', 'cache'):
        (state / name).mkdir(mode=0o700, exist_ok=True)
    env.update(HOME=str(state / 'home'), TMPDIR=str(state / 'tmp'), XDG_CACHE_HOME=str(state / 'cache'))
    return env


def production_command(nix):
    return [nix, 'develop', '.#release-check', '--no-update-lock-file', '--no-write-lock-file',
            '--command', 'scripts/release-check']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--include-new', action='append', default=[])
    parser.add_argument('--production-only', action='store_true')
    parser.add_argument('--oracle-ref')
    parser.add_argument('--oracle-source', type=Path)
    args = parser.parse_args()
    state_root = Path(os.environ.get('XDG_STATE_HOME', Path.home() / '.local/state')).resolve() / 'assbox/verification'
    state_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    state = Path(tempfile.mkdtemp(prefix='candidate-', dir=state_root))
    os.chmod(state, 0o700)
    files, records = capture(ROOT, args.include_new)
    receipt = materialize(files, state / 'source')
    (state / 'source-manifest.json').write_bytes(canonical(records))
    (state / 'candidate-snapshot.json').write_bytes(canonical(receipt))
    nix = shutil.which('nix')
    if not nix:
        raise ValueError('Nix unavailable')
    stages = []
    status = 'failed'
    code = 1
    canonical_hash = None
    print('Verification evidence: ' + str(state), flush=True)
    try:
        if not args.production_only:
            for name, command in [('configuration', ['python3', 'scripts/development_check.py', 'runtime']),
                                  ('static', ['python3', 'scripts/verify_observed.py', 'static', '--entered']), ('rust', ['python3', 'scripts/verify_observed.py', 'rust', '--entered']),
                                  ('mutations', ['python3', 'scripts/verify_observed.py', 'mutations', '--entered'])]:
                if capture(ROOT, args.include_new)[0] != files:
                    raise ValueError('caller source drift')
                subprocess.run(command, cwd=ROOT, check=True)
                if capture(ROOT, args.include_new)[0] != files:
                    raise ValueError('caller source drift')
                stages.append(dict(name=name, status='passed'))
        subprocess.run(production_command(nix), cwd=state / 'source',
                       env=production_environment(state), check=True)
        verify_files(state / 'source', files)
        if git(state / 'source', 'status', '--porcelain'):
            raise ValueError('production check changed snapshot')
        stages.append(dict(name='production', status='passed'))
        if not args.production_only:
            command = [nix, 'develop', 'path:' + str(ROOT / 'nix/dev') + '#repair',
                       '--no-update-lock-file', '--no-write-lock-file', '--command',
                       'python3', str(ROOT / 'scripts/repair_loop.py'), 'canonical', '--snapshot', str(state / 'source'),
                       '--summary-output', str(state / 'canonical-summary.json')]
            if args.oracle_source or os.environ.get('ASSBOX_ORACLE_SOURCE'):
                command += ['--oracle-source', str(args.oracle_source or os.environ['ASSBOX_ORACLE_SOURCE'])]
            else:
                # Resolve the contextual base in the caller, before entering the
                # synthetic snapshot. Never treat its parentless commit as review.
                from repair_loop import export_commit
                oracle_files, oracle_oid = export_commit(ROOT, args.oracle_ref or 'HEAD')
                materialize(oracle_files, state / 'oracle')
                command += ['--oracle-source', str(state / 'oracle')]
            canonical_env = production_environment(state)
            canonical_env['XDG_STATE_HOME'] = str(state / 'canonical-state')
            subprocess.run(command, cwd=ROOT, env=canonical_env, check=True)
            canonical_result = json.loads((state / 'canonical-summary.json').read_bytes())
            if (canonical_result['status'] != 'passed' or not canonical_result['vm_executed']
                    or canonical_result['candidate_snapshot'] != receipt):
                raise ValueError('canonical execution identity incomplete')
            canonical_hash = digest((state / 'canonical-summary.json').read_bytes())
            stages.append(dict(name='canonical', status='passed'))
        if capture(ROOT, args.include_new)[0] != files:
            raise ValueError('caller source drift')
        status, code = 'passed', 0
    except subprocess.CalledProcessError as error:
        code = error.returncode if error.returncode > 0 else 128 - error.returncode
        raise
    finally:
        (state / 'summary.json').write_bytes(canonical(dict(schema=1, status=status, exit_code=code,
            candidate_snapshot=receipt, stages=stages, canonical_summary_sha256=canonical_hash, finished_at=time.time())))


if __name__ == '__main__':
    main()
