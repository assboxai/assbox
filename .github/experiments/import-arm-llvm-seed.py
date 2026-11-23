#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Import the independently verified LLVM package on the ephemeral ARM runner."""
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
import tempfile
from zipfile import ZipFile

SOURCE = '28bf6a68aad8860e412e5cd3d4f3788caef7edc1'
TREE = '304515456bbb2d19c47226caf38a5a2c1083544a'
LOCK = 'ea86256a5c0755b5dc022ef446202ea28b404144a7a2eb2202199a58c3ec57b7'
SEED_RUN = 45085837980
SEED_CONTROLLER = 'b8f812f0ab52b9a6c287ca6633394ead0b949d3f'
SEED_SOURCE = 'c2d872c72ee0478f19e2ca28312deeaf77b446f6'
SEED_TREE = '91c656ad4debdb00c907c8d9147e058f5d3939ea'
SIZE_LIMIT = 4 * 1024**3


def require(condition, message):
    if not condition:
        raise ValueError(message)


def extract(archive, directory, cache_tools):
    with ZipFile(archive) as package:
        members = package.infolist()
        require(3 <= len(members) <= 1028, 'Unexpected seed artifact file count')
        seen = set()
        size = 0
        for item in members:
            path = PurePosixPath(item.filename)
            parts = path.parts
            require(not path.is_absolute() and '..' not in parts, 'Invalid seed member path')
            if parts and parts[0] == 'assbox-arm-llvm-seed-evidence':
                parts = parts[1:]
            if item.is_dir():
                require(not parts or parts == ('signed-cache',), 'Unexpected seed directory')
                continue
            is_index = parts == ('index.json',)
            require(parts not in seen and (is_index or (
                len(parts) == 2 and parts[0] == 'signed-cache' and re.fullmatch(cache_tools.ASSET, parts[1])
            )), 'Unexpected or duplicate seed member')
            require(stat.S_IFMT(item.external_attr >> 16) in (0, stat.S_IFREG), 'Unexpected seed member type')
            seen.add(parts)
            size += item.file_size
            limit = 2 * 1024**2 if is_index else cache_tools.MAX_ASSET
            require(0 < item.file_size <= limit and size <= SIZE_LIMIT, 'Oversized seed member')
            with package.open(item) as stream, directory.joinpath(*parts).open('xb') as output:
                shutil.copyfileobj(stream, output)


def validate_seed(download, directory, pinned, cache_tools):
    entries = list(download.iterdir())
    require(len(entries) == 1 and entries[0].is_file(), 'Unexpected seed download inventory')
    archive, = entries
    require(0 < archive.stat().st_size == pinned['sizeInBytes'] <= SIZE_LIMIT
            and pinned['transportDigest'] == 'sha256:' + cache_tools.file_digest(archive),
            'Seed archive size or digest differs from the independently verified artifact')
    cache = directory / 'signed-cache'
    cache.mkdir(mode=0o700)
    extract(archive, directory, cache_tools)
    raw = cache_tools.bounded(directory / 'index.json', 2 * 1024**2)
    require(sha256(raw).hexdigest() == pinned['indexSha256'], 'Unexpected seed manifest digest')
    index = cache_tools.decoded(raw)
    require(cache_tools.encoded(index) == raw and index['schema'] == 1
            and index['kind'] == 'assbox-native-arm-llvm-store-seed' and index['runId'] == SEED_RUN
            and index['workflow'] == SEED_CONTROLLER and index['attempt'] == 1 and index['source'] == SEED_SOURCE
            and index['tree'] == SEED_TREE and index['lockSha256'] == LOCK and index['architecture'] == 'aarch64-linux'
            and re.search(r'\bLLVM version 21\.1\.8\b', index['nativeVersion']) and index['testedColdCorrectAndWrongKeys'] is True
            and index['publicKey'] == pinned['publicKey']
            and re.fullmatch(rf'assbox-arm-llvm-seed-{SEED_RUN}:[A-Za-z0-9+/]{{43}}=', index['publicKey']),
            'Unexpected signed ARM seed provenance')
    require({key: index[key] for key in ('derivation', 'outputs')} == pinned['package'],
            'Signed seed package and candidate inputs differ')
    cache_tools.validate_cache(cache, index)
    return index, cache


def require_hosted():
    require(platform.system() == 'Linux' and platform.machine() == 'aarch64',
            'Native ARM Linux is required')
    expected = {'RUNNER_ENVIRONMENT': 'github-hosted', 'GITHUB_REPOSITORY': 'assboxai/assbox',
                'GITHUB_REPOSITORY_ID': '1402455771', 'GITHUB_REPOSITORY_OWNER_ID': '327835666',
                'GITHUB_EVENT_NAME': 'workflow_dispatch', 'GITHUB_RUN_ATTEMPT': '1',
                'GITHUB_REF': 'refs/heads/test/arm-chromium-clang-seeded-v3'}
    require(all(os.environ.get(key) == value for key, value in expected.items()), 'Unexpected hosted authority')
    require(not any(key in os.environ for key in (
        'GH_TOKEN', 'GITHUB_TOKEN', 'ACTIONS_RUNTIME_TOKEN', 'ACTIONS_ID_TOKEN_REQUEST_TOKEN',
        'ACTIONS_ID_TOKEN_REQUEST_URL',
    )), 'Unexpected credentials in seed import environment')


def main():
    require_hosted()
    product, download, receipt = (Path(path).resolve(strict=index < 2) for index, path in enumerate(sys.argv[1:]))
    authority = Path(__file__).resolve().parent

    def git(checkout, *arguments):
        return subprocess.check_output(['git', '--no-replace-objects', '-C', checkout, *arguments], text=True)

    for checkout, refs in ((product, [SOURCE, TREE]), (authority, [os.environ['GITHUB_SHA']])):
        ref_args = ['HEAD', 'HEAD^{tree}'] if len(refs) == 2 else ['HEAD']
        require(git(checkout, 'rev-parse', *ref_args).splitlines() == refs and not git(checkout, 'status', '--porcelain'),
                'Unexpected source or controller checkout')
    sys.path.insert(0, str(product / 'scripts'))
    import kernel_cache as cache_tools

    require(cache_tools.file_digest(product / 'flake.lock') == LOCK, 'Unexpected product lock')
    pinned = json.loads((authority / 'native-arm-llvm-seed.json').read_bytes())
    require(pinned['run'] == SEED_RUN and pinned['job'] == 137404123206 and pinned['artifact'] > 0,
            'Unexpected seed artifact identity')
    with tempfile.TemporaryDirectory(prefix='verified-llvm-seed-', dir=download.parent) as temp:
        directory = Path(temp)
        index, cache = validate_seed(download, directory, pinned, cache_tools)
        env = cache_tools.environment(directory)
        selector = product.as_uri().replace('file:', 'git+file:', 1) + '?rev=' + SOURCE
        actual = cache_tools.decoded(cache_tools.run(
            env, 'nix', 'eval', '--json', '--no-update-lock-file', '--no-write-lock-file',
            selector + '#nixosConfigurations.aarch64-linux-uefi-none-headless.pkgs.rustc.llvmPackages.llvm', '--apply',
            'p: { derivation = p.drvPath; outputs = builtins.listToAttrs '
            '(map (name: { inherit name; value = p.${name}.outPath; }) p.outputs); }',
        ))
        require(actual == pinned['package'], 'Native evaluation does not select the signed ARM package')
        outputs = list(actual['outputs'].values())
        nix = shutil.which('nix', path=env['PATH'])
        require(nix and Path(nix).resolve(strict=True).is_relative_to('/nix/store'),
                'Expected the provisioned Nix executable')
        subprocess.run(
            ['/usr/bin/sudo', '-n', '--', nix, 'copy', '--offline', '--from', cache.as_uri(), '--to', 'daemon',
             '--option', 'trusted-public-keys', index['publicKey'], '--option', 'require-sigs', 'true',
             '--option', 'substituters', '', *outputs],
            env=env, stdin=subprocess.DEVNULL, check=True, timeout=900,
        )
        observed = cache_tools.decoded(cache_tools.run(
            env, 'nix', 'path-info', '--offline', '--recursive', '--json', '--json-format', '1', *outputs,
        ))
        require(set(observed) == set(index['closure']) and all(
            {key: row[key] for key in ('narHash', 'narSize', 'references')} == index['closure'][path]
            for path, row in observed.items()
        ), 'Native store differs from the signed seed')
        require(not git(product, 'status', '--porcelain'), 'Seed changed the product checkout')
    with receipt.open('x') as stream:
        json.dump({**pinned, 'candidate': SOURCE, 'tree': TREE, 'architecture': 'aarch64-linux',
                   'closurePaths': len(observed), 'importedAt': datetime.now(timezone.utc).isoformat()}, stream, indent=2)
        stream.write('\n')
    print('Verified the imported native ARM LLVM package and', len(observed), 'store paths.', flush=True)


if __name__ == '__main__':
    os.umask(0o077)
    main()
