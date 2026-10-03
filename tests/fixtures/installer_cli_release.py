# SPDX-License-Identifier: GPL-3.0-or-later
"""Synthetic release of exact candidate bytes plus one generated context file."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
import time
import tomllib


def canonical(value):
    return (json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False) + '\n').encode()


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def content(tree):
    records = []
    for path in sorted(tree.rglob('*'), key=lambda p: p.relative_to(tree).as_posix().encode()):
        if path.is_symlink():
            raise ValueError('fixture source symlink')
        if path.is_file():
            records.append(dict(path=path.relative_to(tree).as_posix(), mode='100755' if path.stat().st_mode & 0o111 else '100644', sha256=digest(path.read_bytes())))
    return digest(canonical(records))


def prepare(source, destination, revision, expected):
    if not re.fullmatch('[0-9a-f]{40}', revision) or not re.fullmatch('[0-9a-f]{64}', expected):
        raise ValueError('candidate identity required')
    root = Path(destination); root.mkdir(mode=0o700, parents=True, exist_ok=True)
    tree = root / 'source'
    shutil.copytree(source, tree)
    if content(tree) != expected or (tree / 'release-context.json').exists():
        raise ValueError('fixture source differs from captured candidate')
    lock = (tree / 'flake.lock').read_bytes()
    version = tomllib.loads((tree / 'Cargo.toml').read_text())['workspace']['package']['version']
    context = dict(coreCommit=revision, coreVersion=version, lockSha256=digest(lock))
    (tree / 'release-context.json').write_bytes(canonical(context))
    effective = content(tree)
    nar = subprocess.check_output(['nix', 'hash', 'path', str(tree)], text=True).strip()
    archive = root / 'r-1-assbox-source.tar.gz'
    with tarfile.open(archive, 'w:gz') as output:
        output.add(tree, arcname='source')
    issued = int(time.time()) - 30
    manifest = dict(schema=3, protocol=3, channel='stable', tag='r-1', coreCommit=revision,
        coreVersion=version, issuedAt=issued, expiresAt=issued + 604800, sourceSha256=digest(archive.read_bytes()),
        sourceNarHash=nar, lockSha256=digest(lock), systems=['aarch64-linux', 'x86_64-linux'],
        heldInputs=[], previousTag=None, previousManifestSha256=None)
    urls = {}
    for name, raw in [('release.json', canonical(manifest)), ('release.sigstore.json', b'{}'), ('flake.lock', lock)]:
        (root / ('r-1-' + name)).write_bytes(raw)
    for name in ('release.json', 'release.sigstore.json', 'flake.lock', 'assbox-source.tar.gz'):
        urls['https://github.com/assboxai/assbox/releases/download/r-1/' + name] = 'r-1-' + name
    (root / 'r-1-tag.json').write_bytes(canonical({'object': {'type': 'commit', 'sha': revision}}))
    urls['https://api.github.com/repos/assboxai/assbox/git/ref/tags/r-1'] = 'r-1-tag.json'
    proof = [{'verificationResult': {'signature': {'certificate': {'sourceRepositoryIdentifier': '123',
        'sourceRepositoryOwnerIdentifier': '456', 'sourceRepositoryDigest': revision, 'buildTrigger': 'schedule'}}}}]
    (root / 'case.json').write_bytes(canonical(dict(urls=urls, proof=proof, revision=revision)))
    (root / 'fixture-release.json').write_bytes(canonical(dict(schema=1, synthetic=True,
        candidate_content_sha256=expected, effective_source_sha256=effective, source_nar_hash=nar,
        source_archive_sha256=manifest['sourceSha256'], production_lock_sha256=digest(lock),
        generated_paths=['release-context.json'], core_commit=revision)))
    shutil.rmtree(tree)


if __name__ == '__main__':
    prepare(*sys.argv[1:])
