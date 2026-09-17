# SPDX-License-Identifier: GPL-3.0-or-later
"""Run the compiled release pipeline against controlled external observations."""
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import time

ROOT = Path('/var/lib/assbox-acceptance')
BASE = 'https://github.com/assboxai/assbox/releases/download/'
API = 'https://api.github.com/repos/assboxai/assbox/'


def canonical(value):
    return (json.dumps(value, sort_keys=True, separators=(',', ':')) + '\n').encode()


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def run(*args, **kwargs):
    return subprocess.check_output(args, text=True, **kwargs)


def main(binary):
    ROOT.mkdir(mode=0o700, exist_ok=True)
    payload = ROOT / 'payload.tar.gz'
    lock = canonical({'version': 7, 'root': 'root', 'nodes': {'root': {}}})
    with tarfile.open(payload, 'w:gz') as archive:
        for name, raw in [('flake.lock', lock), ('flake.nix', b'throw "candidate must not be evaluated during authentication"\n')]:
            info = tarfile.TarInfo('source/' + name)
            info.size, info.mode, info.mtime = len(raw), 0o644, 1
            archive.addfile(info, io.BytesIO(raw))
    archive_bytes = payload.read_bytes()
    prefetched = json.loads(run('nix', 'store', 'prefetch-file', '--unpack', '--json', 'file://' + str(payload)))
    issued = int(time.time()) - 30
    first = dict(schema=3, protocol=3, channel='stable', tag='r-1', coreCommit='a' * 40,
                 coreVersion='0.1.0', issuedAt=issued, expiresAt=issued + 604800,
                 sourceSha256=digest(archive_bytes), sourceNarHash=prefetched['hash'],
                 lockSha256=digest(lock), systems=['aarch64-linux', 'x86_64-linux'], heldInputs=[],
                 previousTag=None, previousManifestSha256=None)
    second = dict(first, tag='r-2', issuedAt=issued + 1, expiresAt=issued + 604801,
                  previousTag='r-1', previousManifestSha256=digest(canonical(first)))
    proof = [{'verificationResult': {'signature': {'certificate': {
        'sourceRepositoryIdentifier': '123', 'sourceRepositoryOwnerIdentifier': '456',
        'sourceRepositoryDigest': 'a' * 40, 'buildTrigger': 'schedule'}}}}]

    def floor(manifest):
        return f"ASSBOX-RELEASE-1\n{manifest['tag'][2:]}\n{digest(canonical(manifest))}\n{manifest['issuedAt']}\n"

    count = 0

    def case(name, manifest=None, error='', old=None, requested=None, mutate=None):
        nonlocal count
        manifest = copy.deepcopy(first if manifest is None else manifest)
        for path in ROOT.iterdir():
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()
        data = {'proof': copy.deepcopy(proof), 'urls': {}}
        for tag, obj in [('r-1', first), (manifest['tag'], manifest)]:
            prefix = BASE + tag + '/'
            for asset, raw in [('release.json', canonical(obj)), ('release.sigstore.json', b'{}\n'),
                               ('flake.lock', lock), ('assbox-source.tar.gz', archive_bytes)]:
                filename = tag + '-' + asset
                (ROOT / filename).write_bytes(raw)
                data['urls'][prefix + asset] = filename
            filename = tag + '-tag.json'
            (ROOT / filename).write_bytes(canonical({'object': {'type': 'commit', 'sha': 'a' * 40}}))
            data['urls'][API + 'git/ref/tags/' + tag] = filename
        (ROOT / 'hint.json').write_bytes(canonical({'tag_name': manifest['tag']}))
        data['urls'][API + 'releases/latest'] = 'hint.json'
        if old is not None:
            (ROOT / 'floor').write_text(old)
        if mutate:
            mutate(data, manifest)
        (ROOT / 'case.json').write_bytes(canonical(data))
        env = dict(os.environ, ASSBOX_TEST_TAG=requested or manifest['tag'], ASSBOX_TEST_ERROR=error)
        subprocess.run([binary, '--ignored', '--exact', 'acceptance::release_fetch', '--nocapture'], env=env, check=True)
        calls = [json.loads(line) for line in (ROOT / 'calls.jsonl').read_text().splitlines()] if (ROOT / 'calls.jsonl').exists() else []
        if calls:
            immutable = next((i for i, call in enumerate(calls) if call[:3] == ['gh', 'release', 'verify-asset']), None)
            attest = next((i for i, call in enumerate(calls) if call[:3] == ['gh', 'attestation', 'verify']), None)
            if attest is not None:
                assert immutable is not None and immutable < attest
        if old is not None:
            assert (ROOT / 'floor').read_text() == old, 'verification changed durable replay state'
        if error:
            assert not (ROOT / 'accepted-floor').exists()
            # Trust failures must not even download candidate assets.
            if name not in {'lock-tamper', 'archive-tamper', 'nar-tamper', 'embedded-lock-tamper'}:
                assert not (ROOT / 'download/assbox-source.tar.gz').exists(), name
        else:
            assert (ROOT / 'accepted-floor').read_text() == floor(manifest)
        count += 1
        print('PASS release pipeline:', name, flush=True)

    case('genesis')
    case('exact-retry', old=floor(first))
    case('lineage', second, old=floor(first))
    case('latest', second, old=floor(first), requested='latest')
    case('no-floor-discovery', requested='latest', error='explicit authenticated release tag')
    case('immutable-refusal', error='gh failed', mutate=lambda d, m: d.update(immutable_exit=1))
    case('signature-refusal', error='gh failed', mutate=lambda d, m: d.update(attestation_exit=1))
    for field, value in [('sourceRepositoryIdentifier', '999'), ('sourceRepositoryOwnerIdentifier', '999'),
                         ('sourceRepositoryDigest', 'b' * 40), ('buildTrigger', 'push')]:
        case(field, error='release provenance', mutate=lambda d, m, f=field, v=value: d['proof'][0]['verificationResult']['signature']['certificate'].update({f: v}))
    case('missing-certificate', error='jq failed', mutate=lambda d, m: d.update(proof=[{}]))
    case('unsynchronized-time', error='synchronized system time', mutate=lambda d, m: d.update(time='no'))
    case('expired', dict(first, issuedAt=issued - 604900, expiresAt=issued - 100), error='release expired')
    case('future', dict(first, issuedAt=issued + 3600, expiresAt=issued + 608400), error='release expired')
    case('replay', old=floor(second), error='release replay')
    case('equivocation', dict(first, heldInputs=['opencode-packages']), old=floor(first), error='release replay')
    case('fork', dict(second, previousManifestSha256='0' * 64), old=floor(first), error='ancestry digest mismatch')
    third = dict(second, tag='r-3')
    case('skipped-floor', third, old=floor(second), error='skips the local high-water mark')
    case('missing-parent', second, old=floor(first), error='curl failed', mutate=lambda d, m: d['urls'].pop(BASE + 'r-1/release.json'))
    case('tag-mismatch', error='immutable release tag', mutate=lambda d, m: (ROOT / 'r-1-tag.json').write_bytes(canonical({'object': {'type': 'commit', 'sha': 'b' * 40}})))
    case('noncanonical', error='canonical sorted JSON', mutate=lambda d, m: (ROOT / 'r-1-release.json').write_text(json.dumps(m, indent=2)))
    case('protocol-1', dict(first, protocol=1), error='jq failed')
    case('lock-tamper', error='dependency lock digest', mutate=lambda d, m: (ROOT / 'r-1-flake.lock').write_text('{}'))
    case('archive-tamper', error='dependency lock digest', mutate=lambda d, m: (ROOT / 'r-1-assbox-source.tar.gz').write_text('tampered'))
    case('nar-tamper', dict(first, sourceNarHash='sha256-' + 'A' * 43 + '='), error='NAR mismatch')
    print(f'Passed {count} compiled release-pipeline scenarios', flush=True)


if __name__ == '__main__':
    main(sys.argv[1])
