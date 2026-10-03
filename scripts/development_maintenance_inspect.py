#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Validate local evidence without resolving provenance or granting write authority."""
import argparse
import json
from pathlib import Path
from candidate_snapshot import capture
from development_maintenance_writer import SYSTEMS, candidate, load, native_reports, require


def inspect(base_source, envelope_path, report_paths=()):
    base, _ = capture(base_source)
    envelope = load(envelope_path.read_bytes())
    candidate(base, envelope, load(base['development/maintenance-policy.json'][1]))
    if report_paths:
        reports = [load(path.read_bytes()) for path in report_paths]
        require(len(reports) == 2 and {r['system'] for r in reports} == set(SYSTEMS), 'both distinct native reports required')
        jobs = {r['system']: r['producer']['job_id'] for r in reports}
        native_reports(envelope, reports, envelope['producer']['run_id'], envelope['producer']['run_attempt'], jobs)
    return dict(schema=1, status='structurally-valid', provenance='unverified-local-evidence',
                candidate_snapshot=envelope['candidate_snapshot'], native_reports_checked=len(report_paths), write_authorized=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-source', type=Path, required=True)
    parser.add_argument('--envelope', type=Path, required=True)
    parser.add_argument('--report', type=Path, action='append', default=[])
    args = parser.parse_args()
    print(json.dumps(inspect(args.base_source, args.envelope, args.report), sort_keys=True))


if __name__ == '__main__':
    main()
