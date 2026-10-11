#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Read-only maintenance outcome inspection; never dispatches or writes a ref."""
import argparse
import json
import os
from pathlib import Path
import urllib.request
from development_maintenance_writer import LIMIT, NoRedirect, load, require


def outcome(enabled, run=None, summary=None):
    if not enabled:
        return dict(status='disabled', observed_switch='operator-supplied', write_authority=False)
    if summary is not None:
        status = summary.get('status')
        require(status in ('no-change', 'failed', 'blocked', 'stale', 'incomplete', 'applied'), 'unsupported outcome')
        result = dict(status=status, evidence='workflow-controller-claim', write_authority=False)
        if status == 'applied': result['commit'] = summary.get('commit')
        return result
    if run is None: return dict(status='incomplete', reason='no canonical run observed', write_authority=False)
    if run['status'] != 'completed':
        return dict(status='incomplete', run_id=run['id'], reason='run not complete', write_authority=False)
    if run.get('conclusion') != 'success':
        return dict(status='blocked' if run.get('conclusion') == 'action_required' else 'failed', run_id=run['id'], write_authority=False)
    return dict(status='incomplete', run_id=run['id'], reason='inspect attempt-specific controller outcome; workflow success alone does not establish applied or no-change', write_authority=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--enabled', action='store_true', help='Operator-observed enablement; not a live protection attestation')
    parser.add_argument('--summary', type=Path, help='Exact private controller outcome JSON')
    parser.add_argument('--observe-public-run', action='store_true')
    args = parser.parse_args()
    summary = load(args.summary.read_bytes()) if args.summary else None
    run = None
    if args.enabled and args.observe_public_run:
        # Public GET only, no credential, POST, mutation, or mutable URL input.
        url = 'https://api.github.com/repos/assboxai/assbox/actions/workflows/maintenance.yml/runs?branch=master&per_page=1'
        req = urllib.request.Request(url, headers={'Accept': 'application/vnd.github+json', 'User-Agent': 'assbox-read-only-maintenance-monitor'})
        with urllib.request.build_opener(NoRedirect()).open(req, timeout=30) as response:
            runs = load(response.read(LIMIT + 1))['workflow_runs']
        require(len(runs) <= 1, 'unexpected run inventory')
        if runs:
            run = runs[0]
            require(run['head_branch'] == 'master' and run['event'] in ('schedule', 'workflow_dispatch')
                    and run['path'] == '.github/workflows/maintenance.yml', 'unexpected public run')
    print(json.dumps(outcome(args.enabled, run, summary), sort_keys=True))


if __name__ == '__main__':
    main()
