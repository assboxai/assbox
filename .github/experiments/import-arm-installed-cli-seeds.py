#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Import independently verified signed dependencies for the ARM installed CLI test."""

from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import shutil
import stat
import subprocess
import sys
from tempfile import TemporaryDirectory
from zipfile import ZipFile

SOURCE = 'd3d36054d98d1ccf3ab37853fd4c23b5621e72d5'
TREE = 'ac7bc49124a59ad59bca1afde3d755dd88ec7370'
LOCK = 'ea86256a5c0755b5dc022ef446202ea28b404144a7a2eb2202199a58c3ec57b7'
TEST = '/nix/store/3y3vjfl9hn5cyly4jpk24lgagcfch43i-nixos-system-assbox-ci-26.05.20261007.2efa67f.drv'
SIZE_LIMIT = 2 * 1024**3
HOSTED = {
    'RUNNER_ENVIRONMENT': 'github-hosted',
    'GITHUB_REPOSITORY': 'assboxai/assbox',
    'GITHUB_REPOSITORY_ID': '1402455771',
    'GITHUB_REPOSITORY_OWNER_ID': '327835666',
    'GITHUB_EVENT_NAME': 'workflow_dispatch',
    'GITHUB_RUN_ATTEMPT': '1',
    'GITHUB_REF': 'refs/heads/test/arm-headless-inventory-verified-ghc',
}
TOKEN_ENV = {
    'GH_TOKEN', 'GITHUB_TOKEN', 'ACTIONS_RUNTIME_TOKEN',
    'ACTIONS_ID_TOKEN_REQUEST_TOKEN', 'ACTIONS_ID_TOKEN_REQUEST_URL',
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def unpack(archive, work, cache_tools):
    with ZipFile(archive) as bundle:
        members = bundle.infolist()
        require(3 <= len(members) <= 1028, 'Unexpected ARM seed archive inventory')
        seen = set()
        size = 0
        for item in members:
            path = PurePosixPath(item.filename)
            parts = path.parts
            require(not path.is_absolute() and '..' not in parts, 'Invalid seed member path')
            if parts and parts[0].startswith('assbox-arm-') and parts[0].endswith('-evidence'):
                parts = parts[1:]
            if item.is_dir():
                require(parts in ((), ('signed-cache',)), 'Unexpected seed archive directory')
                continue
            index = parts == ('index.json',)
            valid_cache = len(parts) == 2 and parts[0] == 'signed-cache' and re.fullmatch(cache_tools.ASSET, parts[1])
            require((index or valid_cache) and parts not in seen, 'Unexpected or repeated seed member')
            require(stat.S_IFMT(item.external_attr >> 16) in (0, stat.S_IFREG), 'Unexpected seed member type')
            seen.add(parts)
            size += item.file_size
            limit = 2 * 1024**2 if index else cache_tools.MAX_ASSET
            require(0 < item.file_size <= limit and size <= SIZE_LIMIT, 'Oversized seed archive')
            with bundle.open(item) as stream, work.joinpath(*parts).open('xb') as output:
                shutil.copyfileobj(stream, output)


def validate(archive, work, pinned, cache_tools):
    require(0 < archive.stat().st_size == pinned['bytes'] <= SIZE_LIMIT, 'Incorrect verified seed archive size')
    require('sha256:' + cache_tools.file_digest(archive) == pinned['transportDigest'], 'Incorrect verified seed archive hash')
    cache = work / 'signed-cache'
    cache.mkdir(mode=0o700)
    unpack(archive, work, cache_tools)
    raw = cache_tools.bounded(work / 'index.json', 2 * 1024**2)
    require(sha256(raw).hexdigest() == pinned['indexSha256'], 'Incorrect ARM seed index hash')
    index = cache_tools.decoded(raw)
    require(cache_tools.encoded(index) == raw and all(index[key] == value for key, value in pinned['index'].items()),
            'ARM seed index does not match the independently verified identity')
    require(index['architecture'] == 'aarch64-linux', 'Native ARM dependency required')
    if pinned['name'] == 'current-headless-packages':
        require(pinned['verifiedCorrectAndWrongKeys'] is True and
                index['group'] == 'headless-prerequisites' and index['parentProfile'] == TEST and
                index['source'] == SOURCE and index['tree'] == TREE,
                'Expected the independently qualified exact headless package archive')
    elif 'exactRoots' in index:
        require(pinned['verifiedCorrectAndWrongKeys'] is True and index['group'] == pinned['name']
                and index['source'] == SOURCE and index['tree'] == TREE,
                'Independently qualified exact native build input required')
    else:
        require(index['testedColdCorrectAndWrongKeys'] is True, 'ARM cold-store qualification is required')
    cache_tools.validate_cache(cache, index)
    return index, cache


def apply(cache, index, packages, cache_tools, env):
    roots = []
    for package in packages:
        drv = package['derivation']
        metadata = cache_tools.decoded(cache_tools.run(env, 'nix', 'derivation', 'show', drv))
        described, = metadata['derivations'].values()
        outputs = {name: '/nix/store/' + row['path'] for name, row in described['outputs'].items()}
        selected = package['outputs']
        require(described['system'] == 'aarch64-linux' and selected and
                all(outputs.get(name) == path for name, path in selected.items()),
                'The seed output identity differs from the exact evaluated ARM package')
        roots.extend(selected.values())
    require(len(roots) == len(set(roots)), 'Native seed outputs overlap')
    nix = shutil.which('nix', path=env['PATH'])
    require(nix and Path(nix).resolve(strict=True).is_relative_to('/nix/store'), 'Expected the provisioned Nix CLI')
    subprocess.run(
        ['/usr/bin/sudo', '-n', '--', nix, 'copy', '--offline', '--from', cache.as_uri(), '--to', 'daemon',
         '--option', 'trusted-public-keys', index['publicKey'], '--option', 'require-sigs', 'true',
         '--option', 'substituters', '', *roots],
        env=env, stdin=subprocess.DEVNULL, check=True, timeout=900,
    )
    observed = cache_tools.decoded(cache_tools.run(
        env, 'nix', 'path-info', '--offline', '--recursive', '--json', '--json-format', '1', *roots,
    ))
    require(set(observed) == set(index['closure']) and all(
        {key: value[key] for key in ('narHash', 'narSize', 'references')} == index['closure'][path]
        for path, value in observed.items()
    ), 'Imported native ARM registration differs from the verified seed closure')
    return len(observed)


def main():
    product, downloads, evidence = map(Path, sys.argv[1:])
    require(platform.system() == 'Linux' and platform.machine() == 'aarch64', 'Native ARM Linux is required')
    require(all(os.environ.get(key) == value for key, value in HOSTED.items()), 'Unexpected hosted import authority')
    require(not TOKEN_ENV.intersection(os.environ), 'Unexpected credentials in the ARM import environment')
    authority = Path(__file__).resolve().parent

    def git(checkout, *arguments):
        return subprocess.check_output(['git', '--no-replace-objects', '-C', checkout, *arguments], text=True)

    require(git(product, 'rev-parse', 'HEAD', 'HEAD^{tree}').splitlines() == [SOURCE, TREE],
            'Unexpected installed CLI product identity')
    require(git(authority, 'rev-parse', 'HEAD').strip() == os.environ['GITHUB_SHA'] and not git(authority, 'status', '--porcelain'),
            'Unexpected ARM seed importer checkout')
    require(not git(product, 'status', '--porcelain'), 'Expected an unchanged product checkout')
    sys.path.insert(0, str(product.resolve() / 'scripts'))
    import kernel_cache as cache_tools

    require(cache_tools.file_digest(product / 'flake.lock') == LOCK, 'Unexpected installed product lock')
    evaluated = json.loads((evidence / 'evaluation.json').read_bytes())
    require(evaluated['test'] == TEST and evaluated['expectedProfile']['system'] == 'aarch64-linux',
            'Unexpected exact installed CLI driver')
    expected = json.loads((authority / 'arm-installed-cli-seeds.json').read_bytes())
    require({row.name for row in downloads.iterdir()} == {row['name'] for row in expected}, 'Unexpected input seed directories')
    accepted = []
    with TemporaryDirectory(prefix='assbox-installed-arm-seeds-', dir=downloads.parent) as temp:
        root = Path(temp)
        env = cache_tools.environment(root)
        graph = set(cache_tools.run(env, 'nix-store', '--query', '--requisites', TEST, timeout=300).decode().splitlines())
        for pinned in expected:
            metadata = pinned['index']
            grouped = 'exactRoots' in metadata
            packages = metadata['exactRoots'] if grouped else [metadata]
            require(packages and all(package['derivation'] in graph for package in packages),
                    'ARM seed derivation is absent from the exact headless graph')
            files = list((downloads / pinned['name']).iterdir())
            require(len(files) == 1 and files[0].is_file() and not files[0].is_symlink(), 'Expected one archived ARM seed')
            with TemporaryDirectory(prefix=pinned['name'] + '-', dir=root) as unpacking:
                index, cache = validate(files[0], Path(unpacking), pinned, cache_tools)
                size = apply(cache, index, packages, cache_tools, env)
            run = int(index['identity']['GITHUB_RUN_ID']) if grouped else index['runId']
            for package in packages:
                accepted.append({'artifact': pinned['artifact'], 'run': run, 'derivation': package['derivation'],
                                 'outputs': list(package['outputs'].values()), 'closurePaths': size,
                                 'transportDigest': pinned['transportDigest']})
            print('Imported independently verified native ARM seed', pinned['name'], size, flush=True)
    require(not git(product, 'status', '--porcelain'), 'The ARM seed changed the product checkout')
    with (evidence / 'seed-import.json').open('x') as receipt:
        json.dump({'source': SOURCE, 'tree': TREE, 'architecture': 'aarch64-linux', 'test': TEST,
                   'seeds': accepted, 'observedAt': datetime.now(timezone.utc).isoformat()}, receipt, indent=2)
        receipt.write('\n')


if __name__ == '__main__':
    os.umask(0o077)
    main()
