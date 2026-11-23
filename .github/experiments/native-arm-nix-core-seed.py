#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Produce and cold-check a scoped cache of the NixOS-selected ARM Nix core package."""
from datetime import datetime, timezone
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
import tempfile
from urllib.parse import urlencode

SOURCE = 'c2d872c72ee0478f19e2ca28312deeaf77b446f6'
TREE = '91c656ad4debdb00c907c8d9147e058f5d3939ea'
LOCK = 'ea86256a5c0755b5dc022ef446202ea28b404144a7a2eb2202199a58c3ec57b7'
FULL_NIX = '/nix/store/adp5igphnvrrqyks4h3hz85f3c4f2c1b-nix-2.34.8.drv'
EXPECTED = {'derivation': '/nix/store/yhmhsy4024ifc8ia2426lb1caxbargsd-nix-2.34.8.drv',
 'outputs': {'debug': '/nix/store/z0yz2rh3s3kwa6vf2x7qmhh23hrc60p1-nix-2.34.8-debug',
             'out': '/nix/store/dmm67d25x2ly94a3g9jmzfplfsp4sszj-nix-2.34.8'}}
FIELDS = ('narHash', 'narSize', 'references')
MAX_BYTES = 4 * 1024**3


def require(condition, message):
    if not condition:
        raise ValueError(message)


def closure_metadata(cache_tools, environment, paths, *, store=None):
    options = ['--store', store] if store else []
    observed = cache_tools.decoded(cache_tools.run(
        environment, 'nix', 'path-info', '--offline', '--recursive', '--json', '--json-format', '1', *options, *paths,
    ))
    require(0 < len(observed) <= 512 and set(paths) <= set(observed), 'Incomplete or excessive seed closure')
    result = {path: {key: row[key] for key in FIELDS} for path, row in observed.items()}
    require(sum(row['narSize'] for row in result.values()) <= 3 * MAX_BYTES, 'Unpacked seed exceeds its size bound')
    return result, {path: row.get('ca') for path, row in observed.items()}


def normalize_signed_metadata(cache_tools, cache, content_addresses):
    cache_tools.normalize_export(cache)
    for info in sorted(cache.glob('*.narinfo')):
        lines = cache_tools.bounded(info, 256 * 1024).decode().splitlines(keepends=True)
        paths = [line.removeprefix('StorePath: ').rstrip('\n') for line in lines if line.startswith('StorePath: ')]
        require(len(paths) == 1 and paths[0] in content_addresses, 'Unknown producer NAR store path')
        expected = content_addresses[paths[0]]
        fields = [line for line in lines if line.startswith('CA:')]
        if expected is None:
            require(not fields, 'Unexpected NAR content address')
            continue
        require(fields == [f'CA: {expected}\n'], 'NAR content address differs from the native store')
        # Require the scoped signer even on content-addressed paths. Nix signatures bind store
        # path, NAR hash and size, and references. Removing this field preserves that signature.
        info.write_text(''.join(line for line in lines if not line.startswith('CA:')))


def signed_cache(cache_tools, env, workspace, cache, paths, name):
    closure, content_addresses = closure_metadata(cache_tools, env, paths)
    cache.mkdir(mode=0o700)
    secret = workspace / 'signing-key'
    public = workspace / 'signing-key.pub'
    try:
        cache_tools.run(env, 'nix-store', '--generate-binary-cache-key', name, str(secret), str(public))
        secret.chmod(0o600)
        uri = cache.as_uri() + '?' + urlencode({
            'secret-key': str(secret), 'compression': 'xz', 'compression-level': '1', 'parallel-compression': 'true',
        })
        cache_tools.run(env, 'nix', 'copy', '--offline', '--to', uri, *paths)
    finally:
        secret.unlink(missing_ok=True)
    key = public.read_text().strip()
    normalize_signed_metadata(cache_tools, cache, content_addresses)
    inventory = {path.name: {'size': path.stat().st_size, 'sha256': cache_tools.file_digest(path)}
                 for path in sorted(cache.iterdir())}
    require(sum(asset['size'] for asset in inventory.values()) <= MAX_BYTES, 'Seed transport exceeds its size bound')
    index = {'publicKey': key, 'closure': closure, 'cacheAssets': inventory}
    cache_tools.validate_cache(cache, index)
    return index


def verify_cold(cache_tools, env, cache, workspace, paths, index):
    expected = index['publicKey']
    wrong = expected.split(':', 1)[0] + ':AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA='
    for label, key in (('wrong', wrong), ('correct', expected)):
        target = workspace / ('cold-' + label)
        target.mkdir(mode=0o700)
        store = 'local?' + urlencode({'root': str(target)})
        require(not cache_tools.registered(env, paths, store), 'Seed target was not cold')
        result = subprocess.run(
            ['nix', 'copy', '--offline', '--from', cache.as_uri(), '--to', store,
             '--option', 'trusted-public-keys', key, '--option', 'require-sigs', 'true', '--option', 'substituters', '', *paths],
            env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=900,
        )
        if label == 'wrong':
            require(result.returncode != 0 and not any(cache_tools.registered(env, [path], store) for path in paths),
                    'Seed paths registered under a wrong signing key')
        else:
            require(result.returncode == 0, 'Signed seed import failed: ' + result.stderr.decode(errors='replace')[-1500:])
            closure, _ = closure_metadata(cache_tools, env, paths, store=store)
            require(closure == index['closure'], 'Cold store closure differs from the signed content')


def main():
    source, evidence = (Path(path).resolve(strict=True) for path in sys.argv[1:])
    require(platform.machine() == 'aarch64' and platform.system() == 'Linux', 'Native ARM Linux required')
    require(os.environ.get('RUNNER_ENVIRONMENT') == 'github-hosted' and os.environ.get('GITHUB_RUN_ATTEMPT') == '1',
            'Expected the first attempt of the qualified hosted seed experiment')
    require(os.environ.get('GITHUB_REPOSITORY_ID') == '1402455771' and os.environ.get('GITHUB_REPOSITORY_OWNER_ID') == '327835666'
            and os.environ.get('GITHUB_REF') == 'refs/heads/test/arm-nix-core-seed-v2'
            and os.environ.get('GITHUB_EVENT_NAME') == 'workflow_dispatch', 'Unexpected seed authority')
    workflow = os.environ['GITHUB_SHA']
    run = os.environ['GITHUB_RUN_ID']
    require(re.fullmatch('[a-f0-9]{40}', workflow) and re.fullmatch('[1-9][0-9]*', run), 'Invalid seed workflow identity')
    require(subprocess.check_output(['git', '-C', source, 'rev-parse', 'HEAD', 'HEAD^{tree}'], text=True).splitlines() == [SOURCE, TREE]
            and not subprocess.check_output(['git', '-C', source, 'status', '--porcelain']), 'Seed source tree changed')
    sys.path.insert(0, str(source / 'scripts'))
    import kernel_cache as cache_tools
    require(cache_tools.file_digest(source / 'flake.lock') == LOCK, 'Seed source lock changed')
    with tempfile.TemporaryDirectory(prefix='assbox-arm-nix-core-seed-', dir=evidence.parent) as temporary:
        workspace = Path(temporary)
        env = cache_tools.environment(workspace)
        env['NIX_CONFIG'] += 'max-jobs = 2\ncores = 2\neval-cores = 2\n'
        selector = source.as_uri().replace('file:', 'git+file:', 1) + '?rev=' + SOURCE
        attribute = selector + '#nixosConfigurations.aarch64-linux-uefi-none-headless.pkgs.nix.drvPath'
        flags = ('--no-update-lock-file', '--no-write-lock-file')
        full = cache_tools.run(env, 'nix', 'eval', '--raw', *flags, attribute).decode().strip()
        require(full == FULL_NIX, 'The evaluated Nix package differs from the reviewed selection')
        description = cache_tools.decoded(cache_tools.run(env, 'nix', 'derivation', 'show', full))
        dependencies = description['derivations'][Path(full).name]['inputs']['drvs']
        candidates = [name for name in dependencies if name.endswith('-nix-2.34.8.drv')]
        require(len(candidates) == 1, 'The Nix core package is not a unique direct input')
        package = cache_tools.decoded(cache_tools.run(env, 'nix', 'derivation', 'show', '/nix/store/' + candidates[0]))
        selected = package['derivations'][candidates[0]]
        actual = {'derivation': '/nix/store/' + candidates[0], 'outputs': {
            name: '/nix/store/' + output['path'] for name, output in selected['outputs'].items()}}
        require(actual == EXPECTED and selected['system'] == 'aarch64-linux', 'Native evaluated Nix core does not match the independent expectation')
        (evidence / 'expected.json').write_bytes(cache_tools.encoded(actual))
        names = sorted(actual['outputs'])
        paths = [actual['outputs'][name] for name in names]
        with (evidence / 'native-build.log').open('xb') as log:
            command = ['nix', 'build', *flags, '--no-link', '--max-jobs', '2', '--cores', '2', '-L',
                       actual['derivation'] + '^' + ','.join(names)]
            subprocess.run(command, env=env, stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, check=True)
        executable = Path(actual['outputs']['out']) / 'bin/nix'
        require(executable.is_file(), 'Native Nix core executable is missing')
        version = cache_tools.run(env, str(executable), '--version').decode().strip()
        require(version == 'nix (Nix) 2.34.8', 'Unexpected native Nix core version')
        cache = evidence / 'signed-cache'
        index = signed_cache(cache_tools, env, workspace, cache, paths, 'assbox-arm-nix-core-seed-' + run)
        verify_cold(cache_tools, env, cache, workspace, paths, index)
        index.update(schema=1, kind='assbox-native-arm-nix-core-store-seed', source=SOURCE, tree=TREE, lockSha256=LOCK,
                     workflow=workflow, runId=int(run), attempt=1, architecture='aarch64-linux', nativeVersion=version,
                     testedColdCorrectAndWrongKeys=True, finishedAt=datetime.now(timezone.utc).isoformat(), **actual)
        require(not subprocess.check_output(['git', '-C', source, 'status', '--porcelain']), 'Seed modified the product checkout')
        (evidence / 'index.json').write_bytes(cache_tools.encoded(index))
        print('Verified signed ARM Nix core seed with', len(index['closure']), 'store paths', flush=True)


if __name__ == '__main__':
    os.umask(0o077)
    main()
