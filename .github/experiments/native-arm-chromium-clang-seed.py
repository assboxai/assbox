#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Produce and cold-check a scoped cache of the NixOS-selected ARM Clang package required by Chromium."""
from datetime import datetime, timezone
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
import tempfile
from urllib.parse import urlencode

SOURCE = '28bf6a68aad8860e412e5cd3d4f3788caef7edc1'
TREE = '304515456bbb2d19c47226caf38a5a2c1083544a'
LOCK = 'ea86256a5c0755b5dc022ef446202ea28b404144a7a2eb2202199a58c3ec57b7'
ALL_EVALUATED = {'derivation': '/nix/store/xl9xyi4sr0mlw8qpp02zc2kp0cs7h7wx-clang-21.1.8.drv',
 'outputs': {'debug': '/nix/store/mizw12qhpbpwasp85sm6sh02wn0aq0xh-clang-21.1.8-debug',
             'dev': '/nix/store/91s9j7mls34fsri4amalhg67ky7qjqf1-clang-21.1.8-dev',
             'lib': '/nix/store/jamycm4hb42m8mwnridnazp656r233qh-clang-21.1.8-lib',
             'out': '/nix/store/c219gs6966jd09z36cc44nwi4v9mj0qr-clang-21.1.8',
             'python': '/nix/store/7p5by0iz3iwa8mjxkgxhrs8kiqy3zmwk-clang-21.1.8-python'}}
EXPECTED = {'derivation': '/nix/store/xl9xyi4sr0mlw8qpp02zc2kp0cs7h7wx-clang-21.1.8.drv',
 'outputs': {'lib': '/nix/store/jamycm4hb42m8mwnridnazp656r233qh-clang-21.1.8-lib',
             'out': '/nix/store/c219gs6966jd09z36cc44nwi4v9mj0qr-clang-21.1.8',
             'python': '/nix/store/7p5by0iz3iwa8mjxkgxhrs8kiqy3zmwk-clang-21.1.8-python'}}
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
    return result


def signed_cache(cache_tools, env, workspace, cache, paths, name):
    closure = closure_metadata(cache_tools, env, paths)
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
    cache_tools.normalize_export(cache)
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
            require(closure_metadata(cache_tools, env, paths, store=store) == index['closure'],
                    'Cold store closure differs from the signed content')


def main():
    source, evidence = (Path(path).resolve(strict=True) for path in sys.argv[1:])
    require(platform.machine() == 'aarch64' and platform.system() == 'Linux', 'Native ARM Linux required')
    require(os.environ.get('RUNNER_ENVIRONMENT') == 'github-hosted' and os.environ.get('GITHUB_RUN_ATTEMPT') == '1',
            'Expected the first attempt of the qualified hosted seed experiment')
    require(os.environ.get('GITHUB_REPOSITORY_ID') == '1402455771' and os.environ.get('GITHUB_REPOSITORY_OWNER_ID') == '327835666'
            and os.environ.get('GITHUB_REF') == 'refs/heads/test/arm-chromium-clang-seeded-v2'
            and os.environ.get('GITHUB_EVENT_NAME') == 'workflow_dispatch', 'Unexpected seed authority')
    workflow = os.environ['GITHUB_SHA']
    run = os.environ['GITHUB_RUN_ID']
    require(re.fullmatch('[a-f0-9]{40}', workflow) and re.fullmatch('[1-9][0-9]*', run), 'Invalid seed workflow identity')
    require(subprocess.check_output(['git', '-C', source, 'rev-parse', 'HEAD', 'HEAD^{tree}'], text=True).splitlines() == [SOURCE, TREE]
            and not subprocess.check_output(['git', '-C', source, 'status', '--porcelain']), 'Seed source tree changed')
    sys.path.insert(0, str(source / 'scripts'))
    import kernel_cache as cache_tools
    require(cache_tools.file_digest(source / 'flake.lock') == LOCK, 'Seed source lock changed')
    with tempfile.TemporaryDirectory(prefix='assbox-arm-chromium-clang-seed-', dir=evidence.parent) as temporary:
        workspace = Path(temporary)
        env = cache_tools.environment(workspace)
        env['NIX_CONFIG'] += 'max-jobs = 1\ncores = 4\neval-cores = 2\n'
        selector = source.as_uri().replace('file:', 'git+file:', 1) + '?rev=' + SOURCE
        attribute = selector + '#nixosConfigurations.aarch64-linux-uefi-none-headless.pkgs.llvmPackages_21.clang-unwrapped'
        flags = ('--no-update-lock-file', '--no-write-lock-file')
        actual = cache_tools.decoded(cache_tools.run(
            env, 'nix', 'eval', '--json', *flags, attribute, '--apply',
            'p: { derivation = p.drvPath; outputs = builtins.listToAttrs (map (n: { name = n; value = p.${n}.outPath; }) p.outputs); }',
        ))
        require(actual == ALL_EVALUATED, 'Native evaluated Clang package differs from the browser graph')
        actual = {'derivation': actual['derivation'], 'outputs': {n: actual['outputs'][n] for n in EXPECTED['outputs']}}
        require(actual == EXPECTED, 'Selected Clang outputs differ from approved browser inputs')
        (evidence / 'expected.json').write_bytes(cache_tools.encoded(actual))
        names = sorted(actual['outputs'])
        paths = [actual['outputs'][name] for name in names]
        with (evidence / 'native-build.log').open('xb') as log:
            command = ['nix', 'build', *flags, '--no-link', '--max-jobs', '1', '--cores', '4', '-L',
                       actual['derivation'] + '^' + ','.join(names)]
            subprocess.run(command, env=env, stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, check=True)
        executable = Path(actual['outputs']['out']) / 'bin/clang'
        require(executable.is_file(), 'Native Clang entrypoint is missing')
        version = cache_tools.run(env, str(executable), '--version').decode().strip()
        require(re.search(r'\bclang version 21[.]1[.]8\b', version), 'Unexpected native Clang version')
        cache = evidence / 'signed-cache'
        index = signed_cache(cache_tools, env, workspace, cache, paths, 'assbox-arm-chromium-clang-seed-' + run)
        verify_cold(cache_tools, env, cache, workspace, paths, index)
        index.update(schema=1, kind='assbox-native-arm-chromium-clang-store-seed', source=SOURCE, tree=TREE, lockSha256=LOCK,
                     workflow=workflow, runId=int(run), attempt=1, architecture='aarch64-linux', nativeVersion=version,
                     testedColdCorrectAndWrongKeys=True, finishedAt=datetime.now(timezone.utc).isoformat(), **actual)
        require(not subprocess.check_output(['git', '-C', source, 'status', '--porcelain']), 'Seed modified the product checkout')
        (evidence / 'index.json').write_bytes(cache_tools.encoded(index))
        print('Verified signed ARM Chromium Clang seed with', len(index['closure']), 'store paths', flush=True)


if __name__ == '__main__':
    os.umask(0o077)
    main()
