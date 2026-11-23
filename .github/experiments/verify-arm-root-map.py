#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Compare the native ARM collector's realized roots with offline evaluation."""
from datetime import datetime
from hashlib import sha256
import json
from pathlib import Path
import re
import sys

SYSTEM = 'aarch64-linux'
SOURCE = '28bf6a68aad8860e412e5cd3d4f3788caef7edc1'
EXPECTED_DIGEST = '2d98dfdbbd7e6ea3045cdd7e1addbaf7c093aec708c3a8b30cdd34e913e5881b'


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read_pairs(path):
    rows = [line.split('\t') for line in path.read_text().splitlines()]
    require(all(len(row) == 2 for row in rows) and len(rows) == len({row[0] for row in rows}),
            'Malformed ' + path.name)
    return dict(rows)


def verify(expected_path, evidence):
    expected_bytes = expected_path.read_bytes()
    require(sha256(expected_bytes).hexdigest() == EXPECTED_DIGEST, 'Unexpected expected-root input bytes')
    expected = json.loads(expected_bytes)
    require(expected['revision'] == SOURCE and expected['architecture'] == SYSTEM
            and len(expected['systems']) == 49, 'Unexpected ARM root evaluation')
    wanted = {(system, kind, root) for system, roots in expected['systems'].items()
              for kind, root in roots.items()}
    wanted.add((SYSTEM, 'offline-worker', expected['offlineWorker']))
    log = (evidence / 'collection.log').read_text(errors='replace').splitlines()
    rows = [tuple(line.split('\t')) for line in log if line.startswith(SYSTEM + '\t')
            or re.match(SYSTEM + r'-[^\t]+\t', line)]
    require(len(rows) == len(wanted) and set(rows) == wanted, 'Exact native ARM per-system inventory differs')
    roots = sorted({root for _, _, root in wanted})
    require(len(roots) == 50
            and (evidence / 'vulnerability-closure-roots.txt').read_text().splitlines() == roots,
            'Exact native ARM scanner union differs')
    require(read_pairs(evidence / 'source-paths.tsv') == expected['sourcePaths'], 'ARM source paths differ')
    scanner = read_pairs(evidence / 'scanner-provenance.tsv')
    require(set(scanner) == {'architecture', 'scanner', 'version', 'scanStarted', 'scanEnded'}
            and scanner['architecture'] == SYSTEM and bool(scanner['version'])
            and re.fullmatch(r'/nix/store/[0-9abcdfghijklmnpqrsvwxyz]{32}-vulnix-[^/]+/bin/vulnix', scanner['scanner']),
            'Unexpected native ARM scanner provenance')
    start, end = [datetime.fromisoformat(scanner[key]) for key in ('scanStarted', 'scanEnded')]
    require(start.tzinfo is not None and end.tzinfo is not None and start <= end,
            'Invalid native ARM scan timestamps')
    feed = re.fullmatch(rb'([a-f0-9]{64})  [^\n]+/cache/Data\.fs\n',
                        (evidence / 'vulnix-data-sha256.txt').read_bytes())
    require(feed, 'Missing native ARM scanner feed digest')
    return {'source': SOURCE, 'architecture': SYSTEM, 'systems': len(expected['systems']),
            'closureMapRows': len(rows), 'scannerRoots': len(roots), 'scanner': scanner,
            'expectedDigest': EXPECTED_DIGEST, 'feedSha256': feed[1].decode()}


def main():
    expected, evidence = map(Path, sys.argv[1:])
    report = verify(expected, evidence)
    (evidence / 'root-map-verified.json').write_text(json.dumps(report, indent=2) + '\n')
    print('Verified exact native ARM system, worker and scanner root inventory.')


if __name__ == '__main__':
    main()
