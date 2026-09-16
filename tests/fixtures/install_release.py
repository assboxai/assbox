# SPDX-License-Identifier: GPL-3.0-or-later
"""Package the actual source for a disposable integration VM; no real signatures."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import time
import tomllib


def canonical(value):
    return (json.dumps(value, sort_keys=True, separators=(',', ':')) + '\n').encode()


def digest(value):
    return hashlib.sha256(value).hexdigest()


def prepare(source, destination):
    root = Path(destination)
    root.mkdir(parents=True, exist_ok=True)
    tree = root / 'source'
    shutil.copytree(source, tree)
    # The full source is identical for both releases; only authenticated sequence
    # and lineage change. Application/OS changes are exercised through real builds.
    lock = (tree / 'flake.lock').read_bytes()
    version = tomllib.loads((tree / 'Cargo.toml').read_text())['workspace']['package']['version']
    (tree / 'release-context.json').write_bytes(canonical({
        'coreCommit': 'a' * 40, 'coreVersion': version, 'lockSha256': digest(lock)}))
    nar = subprocess.check_output(['nix', 'hash', 'path', str(tree)], text=True).strip()
    archive = root / 'payload.tar.gz'
    with tarfile.open(archive, 'w:gz') as output:
        output.add(tree, arcname='source')
    raw = archive.read_bytes()
    issued = int(time.time()) - 30
    urls, previous = {}, None
    for number in [1, 2]:
        tag = f'r-{number}'
        manifest = dict(schema=3, protocol=3, channel='stable', tag=tag,
                        coreCommit='a' * 40, coreVersion=version, issuedAt=issued + number,
                        expiresAt=issued + number + 604800, sourceSha256=digest(raw),
                        sourceNarHash=nar, lockSha256=digest(lock),
                        systems=['aarch64-linux', 'x86_64-linux'], heldInputs=[],
                        previousTag=None if previous is None else previous['tag'],
                        previousManifestSha256=None if previous is None else digest(canonical(previous)))
        for name, contents in [('release.json', canonical(manifest)), ('release.sigstore.json', b'{}'),
                               ('flake.lock', lock), ('assbox-source.tar.gz', raw)]:
            filename = f'{tag}-{name}'
            (root / filename).write_bytes(contents)
            urls[f'https://github.com/assboxai/assbox/releases/download/{tag}/{name}'] = filename
        (root / f'{tag}-tag.json').write_bytes(canonical({'object': {'type': 'commit', 'sha': 'a' * 40}}))
        urls[f'https://api.github.com/repos/assboxai/assbox/git/ref/tags/{tag}'] = f'{tag}-tag.json'
        previous = manifest
    (root / 'latest.json').write_bytes(canonical({'tag_name': 'r-2'}))
    urls['https://api.github.com/repos/assboxai/assbox/releases/latest'] = 'latest.json'
    proof = [{'verificationResult': {'signature': {'certificate': {
        'sourceRepositoryIdentifier': '123', 'sourceRepositoryOwnerIdentifier': '456',
        'sourceRepositoryDigest': 'a' * 40, 'buildTrigger': 'schedule'}}}}]
    (root / 'case.json').write_bytes(canonical({'urls': urls, 'proof': proof}))
    shutil.rmtree(tree)


if __name__ == '__main__':
    prepare(*sys.argv[1:])
