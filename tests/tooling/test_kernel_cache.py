# SPDX-License-Identifier: GPL-3.0-or-later
"""Cache binding and refusal tests; these do not claim VM or signature acceptance."""
from __future__ import annotations

import base64
import copy
import hashlib
import importlib.util
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('kernel_cache_under_test', ROOT / 'scripts/kernel_cache.py')
cache = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(cache)


def nix_hash(raw):
    value = int.from_bytes(raw, 'little')
    return 'sha256:' + ''.join(cache.NIX_BASE32[(value >> (position * 5)) & 31]
                              for position in range(51, -1, -1))


def fixture(directory):
    paths = ['/nix/store/' + digit * 32 + '-linux-6.18.51' + suffix
             for digit, suffix in [('0', ''), ('1', '-modules'), ('2', '-dev')]]
    closure = {}
    key = 'assbox-kernel-fixture:' + base64.b64encode(bytes(range(32))).decode()
    (directory / 'nix-cache-info').write_bytes(b'StoreDir: /nix/store\nWantMassQuery: 1\nPriority: 40\n')
    for index, path in enumerate(paths):
        content = ('contract-only-compressed-NAR-' + str(index)).encode()
        digest = hashlib.sha256(content).digest()
        nar = 'nar-' + nix_hash(digest).removeprefix('sha256:') + '.nar.xz'
        (directory / nar).write_bytes(content)
        nar_hash = hashlib.sha256(b'contract-only-uncompressed-' + content).digest()
        closure[path] = {'narHash': 'sha256-' + base64.b64encode(nar_hash).decode(),
                         'narSize': 128, 'references': [path]}
        fields = {'StorePath': path, 'URL': nar, 'Compression': 'xz', 'FileHash': nix_hash(digest),
                  'FileSize': str(len(content)), 'NarHash': nix_hash(nar_hash), 'NarSize': '128',
                  'References': path.removeprefix('/nix/store/'),
                  'Sig': key.split(':')[0] + ':' + base64.b64encode(bytes(64)).decode()}
        (directory / (path.split('/')[3][:32] + '.narinfo')).write_text(
            ''.join(name + ': ' + value + '\n' for name, value in fields.items()))
    assets = {path.name: {'size': path.stat().st_size, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
              for path in directory.iterdir()}
    return dict(schema=1, kind='assbox-release-kernel-cache', releaseManifestSha256='a' * 64,
                coreCommit='b' * 40, lockSha256='c' * 64, system='x86_64-linux',
                derivation='/nix/store/' + '3' * 32 + '-linux-6.18.51.drv', kernelVersion='6.18.51',
                outputs=dict(zip(cache.OUTPUTS, paths)), publicKey=key, configSha256='d' * 64,
                closure=closure, cacheAssets=assets)


def publication_fixture(directory, release_bytes, system):
    """Construct only static publisher inputs, without claiming signed NARs."""
    release = cache.decoded(release_bytes)
    with tempfile.TemporaryDirectory(prefix='assbox-kernel-publication-fixture-') as temporary:
        source = Path(temporary)
        index = fixture(source)
        index.update(system=system, coreCommit=release['coreCommit'], lockSha256=release['lockSha256'],
                     releaseManifestSha256=hashlib.sha256(release_bytes).hexdigest())
        for path in source.iterdir():
            path.rename(directory / (cache.prefix(system) + path.name))
        (directory / cache.index_name(system)).write_bytes(cache.encoded(index))
    return index


class KernelCache(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='assbox-cache-contract-')
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.index = fixture(self.directory)

    def validate(self, index=None, expected=None, raw=None):
        return cache.validate_index(cache.encoded(self.index if index is None else index) if raw is None else raw,
                                    release_sha='a' * 64, core='b' * 40, lock_sha='c' * 64,
                                    system='x86_64-linux', expected=expected)

    def test_complete_structure_and_asset_bindings(self):
        self.assertEqual(self.validate(), self.index)
        cache.validate_cache(self.directory, self.index)

    def test_release_core_lock_and_architecture_are_independent_bindings(self):
        for field, value in [('releaseManifestSha256', 'e' * 64), ('coreCommit', 'f' * 40),
                             ('lockSha256', '0' * 64), ('system', 'aarch64-linux')]:
            with self.subTest(field=field):
                changed = copy.deepcopy(self.index)
                changed[field] = value
                with self.assertRaises(ValueError):
                    self.validate(changed)

    def test_independent_kernel_evaluation_rejects_other_outputs_and_derivations(self):
        expected = {field: copy.deepcopy(self.index[field]) for field in ('outputs', 'derivation', 'kernelVersion')}
        self.validate(expected=expected)
        for field in expected:
            changed = copy.deepcopy(expected)
            if field == 'outputs':
                changed[field]['dev'] = '/nix/store/' + '4' * 32 + '-linux-dev'
            else:
                changed[field] += '1'
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.validate(expected=changed)

    def test_incomplete_reference_graph_and_missing_dev_are_refused(self):
        changed = copy.deepcopy(self.index)
        changed['closure'][changed['outputs']['out']]['references'].append('/nix/store/' + '4' * 32 + '-missing')
        with self.assertRaises(ValueError):
            self.validate(changed)

        changed = copy.deepcopy(self.index)
        del changed['closure'][changed['outputs']['dev']]
        with self.assertRaises(ValueError):
            self.validate(changed)

    def test_unpacked_size_bound_is_independent_of_compressed_asset_sizes(self):
        changed = copy.deepcopy(self.index)
        for proof in changed['closure'].values():
            proof['narSize'] = cache.MAX_CACHE
        with self.assertRaisesRegex(ValueError, 'unpacked size'):
            self.validate(changed)

    def test_unreachable_closure_path_is_refused_before_download(self):
        changed = copy.deepcopy(self.index)
        path = '/nix/store/' + '4' * 32 + '-unrelated'
        changed['closure'][path] = {'narHash': next(iter(changed['closure'].values()))['narHash'],
                                    'narSize': 1, 'references': []}
        with self.assertRaisesRegex(ValueError, 'outside its output closure'):
            self.validate(changed)

    def test_noncanonical_json_duplicate_fields_and_unknown_fields_are_refused(self):
        raw = cache.encoded(self.index)
        for malformed in [raw.rstrip(), b'{"schema":1,"schema":1}', raw.replace(b'"schema":1', b'"schema":true')]:
            with self.subTest(raw=malformed[:50]), self.assertRaises(ValueError):
                self.validate(raw=malformed)
        changed = copy.deepcopy(self.index)
        changed['trusted'] = True
        with self.assertRaises(ValueError):
            self.validate(changed)

    def test_path_traversal_external_asset_and_size_overflow_are_refused(self):
        for name in ('../escape.narinfo', '/tmp/payload', 'https://other.invalid/cache', 'secret-key'):
            changed = copy.deepcopy(self.index)
            changed['cacheAssets'][name] = {'size': 1, 'sha256': '0' * 64}
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.validate(changed)
        for size in (True, 0, cache.MAX_ASSET + 1):
            changed = copy.deepcopy(self.index)
            changed['cacheAssets']['nix-cache-info']['size'] = size
            with self.subTest(size=size), self.assertRaises(ValueError):
                self.validate(changed)

    def test_changed_nar_bytes_missing_asset_and_symlinks_are_refused(self):
        nar = next(self.directory.glob('*.nar.xz'))
        original = nar.read_bytes()
        nar.write_bytes(original[:-1] + b'!')
        with self.assertRaises(ValueError):
            cache.validate_cache(self.directory, self.index)
        nar.write_bytes(original)
        nar.unlink()
        with self.assertRaises(ValueError):
            cache.validate_cache(self.directory, self.index)
        target = self.directory / 'outside'
        target.write_bytes(original)
        nar.symlink_to(target)
        with self.assertRaises(ValueError):
            cache.validate_cache(self.directory, self.index)

    def test_attested_hash_does_not_authorize_external_nar_metadata_url(self):
        info = next(self.directory.glob('*.narinfo'))
        text = info.read_text()
        old = next(line for line in text.splitlines() if line.startswith('URL: '))
        info.write_text(text.replace(old, 'URL: https://outside.invalid/payload'))
        self.index['cacheAssets'][info.name] = {'size': info.stat().st_size,
                                               'sha256': hashlib.sha256(info.read_bytes()).hexdigest()}
        with self.assertRaises(ValueError):
            cache.validate_cache(self.directory, self.index)

    def test_other_nar_signing_key_cannot_replace_attested_key(self):
        self.index['publicKey'] = self.index['publicKey'].replace('fixture:', 'other:')
        with self.assertRaises(ValueError):
            cache.validate_cache(self.directory, self.index)

    def test_nix_sha256_decoder_matches_fixed_known_bit_order(self):
        self.assertEqual(cache.nix_digest('sha256:' + '0' * 52), bytes(32))
        self.assertEqual(cache.nix_digest('sha256:1' + 'z' * 51), b'\xff' * 32)
        self.assertEqual(cache.nix_digest('sha256:' + '0' * 51 + '1'), b'\x01' + bytes(31))
        with self.assertRaises(ValueError):
            cache.nix_digest('sha256:2' + '0' * 51)

    def test_publisher_export_binds_release_and_excludes_private_or_extra_files(self):
        release = cache.encoded({'coreCommit': 'b' * 40, 'lockSha256': 'c' * 64})
        self.index['releaseManifestSha256'] = hashlib.sha256(release).hexdigest()
        system = 'x86_64-linux'
        for path in list(self.directory.iterdir()):
            path.rename(self.directory / (cache.prefix(system) + path.name))
        (self.directory / cache.index_name(system)).write_bytes(cache.encoded(self.index))
        names = cache.validate_export(self.directory, release, system)
        self.assertEqual(set(names), {path.name for path in self.directory.iterdir()})
        with self.assertRaises(ValueError):
            cache.validate_export(self.directory, release + b' ', system)
        (self.directory / 'secret-key').write_text('disposable private data must never be an upload asset')
        with self.assertRaises(ValueError):
            cache.validate_export(self.directory, release, system)

    def test_invalid_asset_selection_refuses_network_access(self):
        for tag, name in [('r-1', '../escape'), ('r-1', 'https://outside.invalid/x'),
                          ('r-1-dev', 'kernel.json'), ('r-0', 'kernel.json')]:
            with self.subTest(tag=tag, name=name), patch.object(cache.urllib.request, 'build_opener') as network:
                with self.assertRaises(ValueError):
                    cache.download(tag, name, self.directory / 'download', 1024)
                network.assert_not_called()

    def test_public_download_retries_only_bounded_transient_gets_without_credentials(self):
        opener = unittest.mock.Mock()
        error = cache.urllib.error.HTTPError('https://github.com/assboxai/assbox', 503, 'transient', {}, None)
        opener.open.side_effect = [error, error, io.BytesIO(b'public asset')]
        with patch.object(cache.urllib.request, 'build_opener', return_value=opener), \
             patch.object(cache.time, 'sleep') as sleep, \
             patch.dict(cache.os.environ, {'GH_TOKEN': 'must-not-leave-process', 'GITHUB_TOKEN': 'must-not-leave-process'}):
            cache.download('r-1', 'kernel.json', self.directory/'download', 1024)
        self.assertEqual((self.directory/'download').read_bytes(), b'public asset')
        self.assertEqual([call.args for call in sleep.call_args_list], [(1,), (3,)])
        self.assertEqual(opener.open.call_count, 3)
        for call in opener.open.call_args_list:
            request = call.args[0]
            self.assertEqual(request.get_method(), 'GET')
            self.assertEqual(request.full_url, 'https://github.com/assboxai/assbox/releases/download/r-1/kernel.json')
            self.assertFalse(any(key.lower() == 'authorization' for key in request.headers))
            self.assertIsNone(request.data)

    def test_download_refuses_external_redirect_and_does_not_retry_not_found(self):
        for status, headers, error_type in [(302, {'Location':'https://outside.invalid/x'}, ValueError),
                                            (404, {}, cache.urllib.error.HTTPError)]:
            with self.subTest(status=status):
                opener = unittest.mock.Mock()
                opener.open.side_effect = cache.urllib.error.HTTPError('https://github.com/assboxai/assbox', status, 'refuse', headers, None)
                with patch.object(cache.urllib.request, 'build_opener', return_value=opener), \
                     patch.object(cache.time, 'sleep') as sleep:
                    with self.assertRaises(error_type):
                        cache.download('r-1', 'kernel.json', self.directory/'download', 1024)
                self.assertEqual(opener.open.call_count, 1)
                sleep.assert_not_called()
                self.assertFalse((self.directory/'download').exists())

    def test_unauthenticated_index_cannot_select_nar_downloads_or_imports(self):
        release = self.directory/'release.json'
        release.write_bytes(cache.encoded({'tag':'r-1','coreCommit':'b'*40,'lockSha256':'c'*64}))
        expected = {key:self.index[key] for key in ('outputs','derivation','kernelVersion')}
        calls=[]
        def download(tag, name, destination, limit):
            calls.append(name)
            destination.write_bytes(b'untrusted metadata')
        with patch.object(cache, 'require_system'), patch.object(cache, 'kernel_identity', return_value=expected), \
             patch.object(cache, 'registered', return_value=False), patch.object(cache, 'download', side_effect=download), \
             patch.object(cache, 'verify_provenance', side_effect=ValueError('invalid provenance')), \
             patch.object(cache, 'run') as command:
            with self.assertRaisesRegex(ValueError, 'invalid provenance'):
                cache.consume(ROOT, release, self.directory/'consumer', 'x86_64-linux', 10, 20)
            command.assert_not_called()
        self.assertEqual(calls, ['kernel-x86_64-linux.json', 'kernel-x86_64-linux.sigstore.json'])

    def test_forced_public_check_cannot_reuse_registered_host_or_target_paths(self):
        release=self.directory/'release.json'
        release.write_bytes(cache.encoded({'tag':'r-1','coreCommit':'b'*40,'lockSha256':'c'*64}))
        expected={key:self.index[key] for key in ('outputs','derivation','kernelVersion')}
        def download(tag, name, destination, limit):
            destination.write_bytes(b'untrusted metadata')
        with patch.object(cache, 'require_system'), patch.object(cache, 'kernel_identity', return_value=expected), \
             patch.object(cache, 'registered', return_value=True) as registered, \
             patch.object(cache, 'download', side_effect=download), \
             patch.object(cache, 'verify_provenance', side_effect=ValueError('public proof refused')), \
             patch.object(cache, 'run') as command:
            with self.assertRaisesRegex(ValueError, 'public proof refused'):
                cache.consume(ROOT, release, self.directory/'cold', 'x86_64-linux', 10, 20,
                              'local?root=/disposable', force_download=True)
            registered.assert_not_called()
            command.assert_not_called()

    def test_unsigned_local_kernel_falls_back_to_public_proof_without_disabling_signatures(self):
        release=self.directory/'release.json'
        release.write_bytes(cache.encoded({'tag':'r-1','coreCommit':'b'*40,'lockSha256':'c'*64}))
        expected={key:self.index[key] for key in ('outputs','derivation','kernelVersion')}
        def download(tag, name, destination, limit):
            destination.write_bytes(b'untrusted metadata')
        with patch.object(cache, 'require_system'), patch.object(cache, 'kernel_identity', return_value=expected), \
             patch.object(cache, 'registered', side_effect=[False, True]), \
             patch.object(cache, 'download', side_effect=download), \
             patch.object(cache, 'verify_provenance', side_effect=ValueError('public proof refused')), \
             patch.object(cache, 'run', side_effect=cache.subprocess.CalledProcessError(1, ['nix','copy'])) as command:
            with self.assertRaisesRegex(ValueError, 'public proof refused'):
                cache.consume(ROOT, release, self.directory/'local', 'x86_64-linux', 10, 20, 'local?root=/disposable')
            self.assertEqual(command.call_args.args[1:7], ('nix','copy','--to','local?root=/disposable','--option','require-sigs'))
            self.assertEqual(command.call_args.args[7], 'true')
            self.assertEqual(command.call_count, 1)


if __name__ == '__main__':
    unittest.main()
