#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Produce and consume a release-bound, signed cache of the default kernel.

The consumer never builds a derivation. It accepts an index only after the fixed
release workflow's Sigstore proof and immutable asset signature have verified.
Its Nix signing key is scoped to one copy command, never installed globally.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import stat
import subprocess
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

SYSTEMS = ('aarch64-linux', 'x86_64-linux')
OUTPUTS = ('out', 'modules', 'dev')
REPOSITORY = 'assboxai/assbox'
IDENTITY = 'https://github.com/assboxai/assbox/.github/workflows/release.yml@refs/heads/master'
STORE = r'/nix/store/[0-9abcdfghijklmnpqrsvwxyz]{32}-[A-Za-z0-9.+_-]+'
ASSET = r'(?:nix-cache-info|[0-9abcdfghijklmnpqrsvwxyz]{32}\.narinfo|nar-[0-9abcdfghijklmnpqrsvwxyz]{52}\.nar\.xz)'
MAX_INDEX = 1024 * 1024
MAX_ASSET = 2 * 1024**3
MAX_CACHE = 8 * 1024**3
MAX_NAR_BYTES = 16 * 1024**3
MAX_PATHS = 240
NIX_BASE32 = '0123456789abcdfghijklmnpqrsvwxyz'


def encoded(value):
    return (json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True) + '\n').encode()


def decoded(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('Duplicate cache metadata key')
            result[key] = value
        return result
    return json.loads(raw, object_pairs_hook=unique,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError('Nonfinite metadata')))


def bounded(path, limit, *, store_file=False):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, 'rb') as stream:
        metadata = os.fstat(stream.fileno())
        if not stat.S_ISREG(metadata.st_mode) or (metadata.st_nlink != 1 and not store_file) or metadata.st_size > limit:
            raise ValueError('Cache input is not a bounded regular file')
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise ValueError('Cache input grew beyond its bound')
    return raw


def file_digest(path, *, store_file=False):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, 'rb') as stream:
        metadata = os.fstat(stream.fileno())
        if not stat.S_ISREG(metadata.st_mode) or (metadata.st_nlink != 1 and not store_file):
            raise ValueError('Cache asset is not a regular file')
        digest = hashlib.sha256()
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def nix_digest(text):
    """Decode canonical Nix base32 SHA-256, including its reversed digit order."""
    if not isinstance(text, str) or not re.fullmatch('sha256:[0-9abcdfghijklmnpqrsvwxyz]{52}', text):
        raise ValueError('Unsupported NAR digest')
    value = 0
    for position, digit in enumerate(reversed(text[7:])):
        value |= NIX_BASE32.index(digit) << (position * 5)
    if value >= 1 << 256:
        raise ValueError('Noncanonical Nix SHA-256')
    return value.to_bytes(32, 'little')


def sri_digest(text):
    if not isinstance(text, str) or not re.fullmatch(r'sha256-[A-Za-z0-9+/]{43}=', text):
        raise ValueError('Unsupported closure digest')
    result = base64.b64decode(text[7:], validate=True)
    if len(result) != 32 or 'sha256-' + base64.b64encode(result).decode() != text:
        raise ValueError('Noncanonical closure digest')
    return result


def integer(value, low, high):
    return type(value) is int and low <= value <= high


def require_system(system):
    if system not in SYSTEMS or platform.system() != 'Linux' or platform.machine() != system.removesuffix('-linux'):
        raise ValueError('Kernel cache requires the native Linux architecture')


def prefix(system):
    if system not in SYSTEMS:
        raise ValueError('Unknown kernel architecture')
    return 'kernel-' + system + '-'


def index_name(system):
    if system not in SYSTEMS:
        raise ValueError('Unknown kernel architecture')
    return 'kernel-' + system + '.json'


def validate_index(raw, *, release_sha, core, lock_sha, system, expected=None):
    value = decoded(raw)
    fields = {'schema', 'kind', 'releaseManifestSha256', 'coreCommit', 'lockSha256', 'system',
              'derivation', 'kernelVersion', 'outputs', 'publicKey', 'configSha256', 'closure', 'cacheAssets'}
    if (not isinstance(value, dict) or set(value) != fields or encoded(value) != raw
            or type(value['schema']) is not int or value['schema'] != 1
            or value['kind'] != 'assbox-release-kernel-cache'
            or value['releaseManifestSha256'] != release_sha or value['coreCommit'] != core
            or value['lockSha256'] != lock_sha or value['system'] != system or system not in SYSTEMS):
        raise ValueError('Kernel cache does not bind the authenticated release')
    for digest in (release_sha, lock_sha, value['configSha256']):
        if not isinstance(digest, str) or not re.fullmatch('[0-9a-f]{64}', digest):
            raise ValueError('Invalid kernel cache digest')
    if (not isinstance(core, str) or not re.fullmatch('[0-9a-f]{40}', core)
            or not isinstance(value['derivation'], str) or not re.fullmatch(STORE + r'\.drv', value['derivation'])
            or not isinstance(value['kernelVersion'], str) or not re.fullmatch('[0-9][A-Za-z0-9.+_-]{0,79}', value['kernelVersion'])
            or not isinstance(value['outputs'], dict) or set(value['outputs']) != set(OUTPUTS)
            or any(not isinstance(path, str) or not re.fullmatch(STORE, path) for path in value['outputs'].values())
            or len(set(value['outputs'].values())) != 3):
        raise ValueError('Invalid kernel derivation or outputs')
    if expected is not None and any(value[name] != expected[name] for name in ('derivation', 'kernelVersion', 'outputs')):
        raise ValueError('Cached kernel differs from the independently evaluated kernel')
    key = value['publicKey']
    if not isinstance(key, str) or not re.fullmatch(r'assbox-kernel-[A-Za-z0-9_-]{1,100}:[A-Za-z0-9+/]{43}=', key):
        raise ValueError('Invalid scoped Nix signing key')
    if len(base64.b64decode(key.split(':')[1], validate=True)) != 32:
        raise ValueError('Invalid Nix public key length')
    closure = value['closure']
    if not isinstance(closure, dict) or not 3 <= len(closure) <= MAX_PATHS or not set(value['outputs'].values()) <= set(closure):
        raise ValueError('Incomplete or excessive kernel closure')
    for path, proof in closure.items():
        if (not isinstance(path, str) or not re.fullmatch(STORE, path) or not isinstance(proof, dict)
                or set(proof) != {'narHash', 'narSize', 'references'} or not integer(proof['narSize'], 0, MAX_CACHE)
                or not isinstance(proof['references'], list) or len(proof['references']) > MAX_PATHS
                or any(not isinstance(reference, str) for reference in proof['references'])
                or len(set(proof['references'])) != len(proof['references'])
                or not set(proof['references']) <= set(closure)):
            raise ValueError('Invalid or incomplete kernel closure metadata')
        sri_digest(proof['narHash'])
    if sum(proof['narSize'] for proof in closure.values()) > MAX_NAR_BYTES:
        raise ValueError('Kernel closure exceeds its unpacked size bound')
    reachable, pending = set(), list(value['outputs'].values())
    while pending:
        path = pending.pop()
        if path not in reachable:
            reachable.add(path)
            pending.extend(closure[path]['references'])
    if reachable != set(closure):
        raise ValueError('Kernel index includes paths outside its output closure')
    assets = value['cacheAssets']
    if not isinstance(assets, dict) or not 7 <= len(assets) <= 2 * MAX_PATHS + 1:
        raise ValueError('Invalid cache asset set')
    if 'nix-cache-info' not in assets:
        raise ValueError('Missing cache descriptor')
    for name, proof in assets.items():
        if (not isinstance(name, str) or not re.fullmatch(ASSET, name) or not isinstance(proof, dict)
                or set(proof) != {'size', 'sha256'} or not integer(proof['size'], 1, MAX_ASSET)
                or not isinstance(proof['sha256'], str) or not re.fullmatch('[0-9a-f]{64}', proof['sha256'])):
            raise ValueError('Invalid kernel cache asset')
    if sum(proof['size'] for proof in assets.values()) > MAX_CACHE:
        raise ValueError('Kernel cache exceeds its download bound')
    infos = {path.split('/')[3].split('-')[0] + '.narinfo' for path in closure}
    if {name for name in assets if name.endswith('.narinfo')} != infos:
        raise ValueError('NAR metadata does not match the exact kernel closure')
    return value


def validate_cache(directory, index, *, asset_prefix='', metadata_files=()):
    expected_files = {asset_prefix + name for name in index['cacheAssets']} | set(metadata_files)
    if {path.name for path in directory.iterdir()} != expected_files:
        raise ValueError('Unexpected or missing kernel cache file')
    for name, proof in index['cacheAssets'].items():
        path = directory / (asset_prefix + name)
        if path.is_symlink() or path.stat().st_size != proof['size'] or file_digest(path) != proof['sha256']:
            raise ValueError('Kernel cache asset digest or size mismatch')
    cache_info = bounded(directory / (asset_prefix + 'nix-cache-info'), 4096).decode()
    if 'StoreDir: /nix/store\n' not in cache_info:
        raise ValueError('Kernel cache store directory mismatch')
    used_nars = set()
    key_name = index['publicKey'].split(':')[0]
    for store_path, proof in index['closure'].items():
        path = directory / (asset_prefix + store_path.split('/')[3].split('-')[0] + '.narinfo')
        fields, signatures = {}, []
        for line in bounded(path, 256 * 1024).decode().splitlines():
            if ': ' in line:
                name, value = line.split(': ', 1)
            elif line.endswith(':'):
                name, value = line[:-1], ''
            else:
                raise ValueError('Invalid NAR metadata line')
            if name == 'Sig':
                signatures.append(value)
            elif name in fields:
                raise ValueError('Duplicate NAR metadata field')
            else:
                fields[name] = value
        required = {'StorePath', 'URL', 'Compression', 'FileHash', 'FileSize', 'NarHash', 'NarSize', 'References'}
        if not required <= set(fields) or not set(fields) <= required | {'Deriver'}:
            raise ValueError('Unknown or missing NAR metadata field')
        url = fields['URL']
        if (fields['StorePath'] != store_path or not re.fullmatch(r'nar-[0-9abcdfghijklmnpqrsvwxyz]{52}\.nar\.xz', url)
                or url not in index['cacheAssets'] or fields['Compression'] != 'xz'
                or fields['FileSize'] != str(index['cacheAssets'][url]['size'])
                or nix_digest(fields['FileHash']).hex() != index['cacheAssets'][url]['sha256']
                or nix_digest(fields['NarHash']) != sri_digest(proof['narHash'])
                or fields['NarSize'] != str(proof['narSize'])
                or sorted('/nix/store/' + name for name in fields['References'].split()) != sorted(proof['references'])):
            raise ValueError('NAR metadata differs from the attested closure')
        matching = [signature for signature in signatures if signature.startswith(key_name + ':')]
        if len(matching) != 1 or len(base64.b64decode(matching[0].split(':')[1], validate=True)) != 64:
            raise ValueError('NAR lacks the attested scoped signing key')
        used_nars.add(url)
    if used_nars != {name for name in index['cacheAssets'] if name.startswith('nar-')}:
        raise ValueError('Unreferenced NAR asset')


def validate_export(directory, release_bytes, system):
    """Publisher-side static validation. Never evaluate or execute candidate code."""
    release = decoded(release_bytes)
    name = index_name(system)
    raw = bounded(directory / name, MAX_INDEX)
    index = validate_index(raw, release_sha=hashlib.sha256(release_bytes).hexdigest(), core=release['coreCommit'],
                           lock_sha=release['lockSha256'], system=system)
    validate_cache(directory, index, asset_prefix=prefix(system), metadata_files=(name,))
    return [name, *(prefix(system) + name for name in sorted(index['cacheAssets']))]


def environment(directory):
    result = {name: os.environ[name] for name in ('PATH', 'SSL_CERT_FILE', 'NIX_SSL_CERT_FILE') if name in os.environ}
    for name in ('home', 'tmp', 'cache'):
        (directory / name).mkdir(mode=0o700)
    result.update(HOME=str(directory / 'home'), TMPDIR=str(directory / 'tmp'), XDG_CACHE_HOME=str(directory / 'cache'),
                  LC_ALL='C.UTF-8', NIX_USER_CONF_FILES='/dev/null',
                  NIX_CONFIG='accept-flake-config = false\naccess-tokens =\n',
                  GH_CONFIG_DIR='/var/empty', GH_HOST='github.com', GH_PROMPT_DISABLED='1', GH_PAGER='cat',
                  GH_NO_UPDATE_NOTIFIER='1', GH_NO_EXTENSION_UPDATE_NOTIFIER='1',
                  GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL='/dev/null', GIT_CONFIG_COUNT='0', GIT_TERMINAL_PROMPT='0')
    return result


def run(env, *arguments, timeout=21600):
    return subprocess.run(arguments, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                          check=True, timeout=timeout).stdout


def kernel_identity(env, source, system):
    require_system(system)
    selector = 'path:' + str(source) + '#nixosConfigurations.' + system + '-uefi-none-headless.config.boot.kernelPackages.kernel'
    flags = ('--no-update-lock-file', '--no-write-lock-file')
    def evaluate(attribute):
        return run(env, 'nix', 'eval', '--raw', *flags, selector + '.' + attribute).decode().strip()
    return dict(derivation=evaluate('drvPath'), kernelVersion=evaluate('version'),
                outputs={name: evaluate(name + '.outPath') for name in OUTPUTS})


def registered(env, paths, store=None):
    flags = [] if store is None else ['--store', store]
    result = subprocess.run(['nix', 'path-info', *flags, '--json', '--json-format', '1', *paths], env=env,
                            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=60)
    if result.returncode:
        return False
    info = decoded(result.stdout)
    return isinstance(info, dict) and set(info) == set(paths) and all(isinstance(proof, dict) for proof in info.values())


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def download(tag, asset, destination, limit):
    if not re.fullmatch(r'r-[1-9][0-9]{0,15}', tag) or not re.fullmatch(r'[A-Za-z0-9._-]+', asset):
        raise ValueError('Invalid fixed release asset selection')
    initial = 'https://github.com/' + REPOSITORY + '/releases/download/' + tag + '/' + asset
    opener = urllib.request.build_opener(NoRedirect())
    for attempt in range(3):
        url = initial
        try:
            for redirect in range(3):
                try:
                    with opener.open(urllib.request.Request(url, headers={'User-Agent': 'assbox-kernel-cache'}), timeout=60) as response:
                        with destination.open('xb') as stream:
                            total = 0
                            deadline = time.monotonic() + 600
                            while block := response.read(1024 * 1024):
                                total += len(block)
                                if total > limit or time.monotonic() > deadline:
                                    raise ValueError('Kernel asset exceeds its size or time bound')
                                stream.write(block)
                        return
                except urllib.error.HTTPError as error:
                    if error.code not in (301, 302, 303, 307, 308):
                        raise
                    location = error.headers.get('Location')
                    error.close()
                    if redirect == 2:
                        raise ValueError('Too many kernel asset redirects') from error
                    if not location:
                        raise ValueError('Kernel asset redirect omitted its location')
                    url = urllib.parse.urljoin(url, location)
                    parsed = urllib.parse.urlsplit(url)
                    if (parsed.scheme != 'https' or parsed.hostname != 'release-assets.githubusercontent.com'
                            or parsed.username or parsed.password or parsed.port not in (None, 443) or parsed.fragment):
                        raise ValueError('Kernel asset redirect escaped GitHub release storage')
        except urllib.error.HTTPError as error:
            error.close()
            if error.code not in (408, 429, 500, 502, 503, 504) or attempt == 2:
                raise
            time.sleep((1, 3)[attempt])
    raise ValueError('Kernel download did not complete')


def verify_provenance(env, index_path, bundle, *, tag, core, repository_id, owner_id):
    if not integer(repository_id, 1, 2**63 - 1) or not integer(owner_id, 1, 2**63 - 1):
        raise ValueError('Kernel release trust is unprovisioned')
    run(env, 'gh', 'release', 'verify-asset', tag, str(index_path), '--repo', REPOSITORY, timeout=300)
    proof = decoded(run(env, 'gh', 'attestation', 'verify', str(index_path), '--bundle', str(bundle),
                        '--repo', REPOSITORY, '--cert-identity', IDENTITY, '--source-ref', 'refs/heads/master',
                        '--source-digest', core, '--signer-digest', core, '--cert-oidc-issuer',
                        'https://token.actions.githubusercontent.com', '--deny-self-hosted-runners',
                        '--predicate-type', 'https://slsa.dev/provenance/v1', '--format', 'json', timeout=300))
    if not isinstance(proof, list) or len(proof) != 1:
        raise ValueError('One verified kernel provenance proof is required')
    certificate = proof[0]['verificationResult']['signature']['certificate']
    if (certificate['sourceRepositoryIdentifier'] != str(repository_id)
            or certificate['sourceRepositoryOwnerIdentifier'] != str(owner_id)
            or certificate['sourceRepositoryDigest'] != core
            or certificate['buildTrigger'] not in ('schedule', 'workflow_dispatch')):
        raise ValueError('Verified kernel certificate identity mismatch')


def consume(source, release_path, directory, system, repository_id, owner_id, store=None, *, force_download=False):
    require_system(system)
    release_bytes = bounded(release_path, 65536)
    release = decoded(release_bytes)
    directory.mkdir(mode=0o700)
    env = environment(directory)
    expected = kernel_identity(env, source, system)
    paths = list(expected['outputs'].values())
    if not force_download and registered(env, paths, store):
        return {'status': 'already-registered', 'kernelBuildInvoked': False, **expected}
    if not force_download and store is not None and registered(env, paths):
        # Reuse complete, already trusted installer-store outputs when Nix can
        # import them with signature verification enabled. Unsigned local paths
        # do not authorize disabling verification or compiling a replacement.
        try:
            run(env, 'nix', 'copy', '--to', store, '--option', 'require-sigs', 'true', *paths)
        except subprocess.CalledProcessError:
            pass
        else:
            if not registered(env, paths, store):
                raise ValueError('Local kernel copy did not register all exact target outputs')
            return {'status': 'copied-local-kernel', 'kernelBuildInvoked': False, **expected}
    index_path = directory / index_name(system)
    bundle = directory / (index_name(system).removesuffix('.json') + '.sigstore.json')
    download(release['tag'], index_path.name, index_path, MAX_INDEX)
    download(release['tag'], bundle.name, bundle, 4 * MAX_INDEX)
    # Authenticate exact index bytes before they select any additional download.
    verify_provenance(env, index_path, bundle, tag=release['tag'], core=release['coreCommit'],
                      repository_id=repository_id, owner_id=owner_id)
    index = validate_index(bounded(index_path, MAX_INDEX), release_sha=hashlib.sha256(release_bytes).hexdigest(),
                           core=release['coreCommit'], lock_sha=release['lockSha256'], system=system, expected=expected)
    cache = directory / 'signed-cache'
    cache.mkdir(mode=0o700)
    for name, proof in index['cacheAssets'].items():
        download(release['tag'], prefix(system) + name, cache / name, proof['size'])
    validate_cache(cache, index)
    # Replace the trusted key set for this one invocation. No persistent trust,
    # signature bypass, impure evaluation or build fallback is permitted.
    destination = () if store is None else ('--to', store)
    run(env, 'nix', 'copy', '--from', cache.as_uri(), *destination, '--option', 'trusted-public-keys', index['publicKey'],
        '--option', 'require-sigs', 'true', *paths)
    if not registered(env, paths, store):
        raise ValueError('Kernel copy did not register all three exact outputs')
    store_flags = () if store is None else ('--store', store)
    actual = decoded(run(env, 'nix', 'path-info', *store_flags, '--recursive', '--json', '--json-format', '1', *paths))
    if set(actual) != set(index['closure']) or any(
            {field: actual[path][field] for field in ('narHash', 'narSize', 'references')} != proof
            for path, proof in index['closure'].items()):
        raise ValueError('Imported kernel closure differs from the attested index')
    # A chroot store exposes the same logical /nix/store paths below its root.
    store_root = urllib.parse.parse_qs(urllib.parse.urlsplit(store).query).get('root', [None])[0] if store else None
    config = Path(expected['outputs']['dev']) / 'lib/modules' / expected['kernelVersion'] / 'build/.config'
    if store_root:
        config = Path(store_root) / config.relative_to('/')
    config_bytes = bounded(config, 4 * MAX_INDEX, store_file=True)
    if (hashlib.sha256(config_bytes).hexdigest() != index['configSha256']
            or b'# CONFIG_RFKILL_INPUT is not set\n' not in config_bytes
            or b'CONFIG_RFKILL_INPUT=y\n' in config_bytes):
        raise ValueError('Imported kernel configuration differs from Assbox radio policy')
    return {'status': 'copied-authenticated-cache', 'kernelBuildInvoked': False, **expected}


def produce(source, release_path, directory, system):
    require_system(system)
    release_bytes = bounded(release_path, 65536)
    release = decoded(release_bytes)
    if file_digest(source / 'flake.lock', store_file=str(source).startswith('/nix/store/')) != release['lockSha256']:
        raise ValueError('Kernel producer source lock differs from the release')
    directory.mkdir(mode=0o700)
    with tempfile.TemporaryDirectory(prefix='assbox-kernel-producer-', dir=directory.parent) as temporary:
        private = Path(temporary)
        env = environment(private)
        expected = kernel_identity(env, source, system)
        run(env, 'nix', 'build', '--no-link', '--no-update-lock-file', '--no-write-lock-file',
            expected['derivation'] + '^out,modules,dev')
        paths = list(expected['outputs'].values())
        closure = decoded(run(env, 'nix', 'path-info', '--recursive', '--json', '--json-format', '1', *paths))
        if not isinstance(closure, dict) or not 3 <= len(closure) <= MAX_PATHS:
            raise ValueError('Excessive default kernel closure')
        config = Path(expected['outputs']['dev']) / 'lib/modules' / expected['kernelVersion'] / 'build/.config'
        config_bytes = bounded(config, 4 * MAX_INDEX, store_file=True)
        if b'# CONFIG_RFKILL_INPUT is not set\n' not in config_bytes or b'CONFIG_RFKILL_INPUT=y\n' in config_bytes:
            raise ValueError('Default kernel does not enforce Assbox radio policy')
        secret, public = private / 'secret-key', private / 'public-key'
        keyname = 'assbox-kernel-' + system + '-' + hashlib.sha256(release_bytes).hexdigest()[:16]
        cache = private / 'public-cache'
        cache.mkdir(mode=0o700)
        try:
            run(env, 'nix-store', '--generate-binary-cache-key', keyname, str(secret), str(public))
            secret.chmod(0o600)
            run(env, 'nix', 'copy', '--to', cache.as_uri() + '?secret-key=' + urllib.parse.quote(str(secret), safe='/'), *paths)
        finally:
            secret.unlink(missing_ok=True)
        key = bounded(public, 4096).decode().strip()
        for info in cache.glob('*.narinfo'):
            text = bounded(info, 256 * 1024).decode()
            urls = [line[5:] for line in text.splitlines() if line.startswith('URL: ')]
            if len(urls) != 1 or not re.fullmatch(r'nar/[0-9abcdfghijklmnpqrsvwxyz]{52}\.nar\.xz', urls[0]):
                raise ValueError('Unsupported producer NAR location')
            old = urls[0]
            new = 'nar-' + old.split('/')[1]
            if (cache / old).exists():
                (cache / old).rename(cache / new)
            info.write_text(text.replace('URL: ' + old + '\n', 'URL: ' + new + '\n'))
        for name in ('nar', 'log', 'build-trace-v2'):
            if (cache / name).exists():
                (cache / name).rmdir()
        assets = {path.name: {'size': path.stat().st_size, 'sha256': file_digest(path)} for path in sorted(cache.iterdir())}
        index = dict(schema=1, kind='assbox-release-kernel-cache', releaseManifestSha256=hashlib.sha256(release_bytes).hexdigest(),
                     coreCommit=release['coreCommit'], lockSha256=release['lockSha256'], system=system,
                     **expected, publicKey=key, configSha256=hashlib.sha256(config_bytes).hexdigest(),
                     closure={path: {field: proof[field] for field in ('narHash', 'narSize', 'references')}
                              for path, proof in closure.items()}, cacheAssets=assets)
        raw = encoded(index)
        index = validate_index(raw, release_sha=hashlib.sha256(release_bytes).hexdigest(), core=release['coreCommit'],
                               lock_sha=release['lockSha256'], system=system, expected=expected)
        validate_cache(cache, index)
        for path in cache.iterdir():
            path.rename(directory / (prefix(system) + path.name))
        (directory / index_name(system)).write_bytes(raw)
    return {'system': system, 'assets': len(assets), 'bytes': sum(proof['size'] for proof in assets.values()), **expected}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    for name in ('produce', 'consume'):
        command = commands.add_parser(name)
        command.add_argument('source', type=Path)
        command.add_argument('release', type=Path)
        command.add_argument('directory', type=Path)
        command.add_argument('system', choices=SYSTEMS)
        if name == 'consume':
            command.add_argument('repository_id', type=int)
            command.add_argument('owner_id', type=int)
            command.add_argument('--store', type=Path)
            command.add_argument('--force-download', action='store_true')
    args = parser.parse_args()
    for path in (args.source, args.release, args.directory):
        if not path.is_absolute() or path.resolve() != path:
            raise ValueError('Kernel paths must be absolute and unredirected')
    if args.command == 'produce':
        result = produce(args.source, args.release, args.directory, args.system)
    else:
        store = None
        if args.store is not None:
            if not args.store.is_absolute() or args.store.resolve() != args.store:
                raise ValueError('Kernel target store must be absolute and unredirected')
            store = 'local?root=' + urllib.parse.quote(str(args.store), safe='/')
        result = consume(args.source, args.release, args.directory, args.system, args.repository_id, args.owner_id, store,
                         force_download=args.force_download)
    print(json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        raise SystemExit('Prebuilt Assbox kernel unavailable or invalid: ' + str(error)) from error
