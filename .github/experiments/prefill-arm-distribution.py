#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Import the independently verified development cache in the ephemeral ARM scan runner."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from hashlib import sha256
import importlib.util
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

SYSTEM = 'aarch64-linux'
TAG = 'kernel-formatter-45038354435-1-dev'
REPOSITORY = 'assboxai/assbox'
RELEASE_ID = 454755949
REF = 'refs/heads/test/arm-native-checks-signed-installer-cache'
STORE_FIELDS = ('narHash', 'narSize', 'references')


class ReleaseRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        address = urlsplit(newurl)
        if (address.scheme != 'https' or address.netloc != 'release-assets.githubusercontent.com'
                or address.fragment or req.headers.get('Authorization')):
            raise ValueError('Unexpected public cache redirect')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def download(name, destination, maximum):
    require(re.fullmatch(r'[A-Za-z0-9._-]+', name) and 0 < maximum <= 2 * 1024**3,
            'Unexpected public cache asset')
    request = Request(f'https://github.com/{REPOSITORY}/releases/download/{TAG}/{name}',
                      headers={'User-Agent': 'assbox-arm-closure-cache'})
    opener = build_opener(ReleaseRedirect())
    for attempt in range(3):
        try:
            with opener.open(request, timeout=60) as response, destination.open('xb') as output:
                remaining = maximum
                deadline = time.monotonic() + 600
                while chunk := response.read(1024**2):
                    remaining -= len(chunk)
                    require(remaining >= 0 and time.monotonic() <= deadline, 'Public cache asset exceeds bounds')
                    output.write(chunk)
            return
        except (HTTPError, URLError, TimeoutError) as error:
            destination.unlink(missing_ok=True)
            if attempt == 2 or isinstance(error, HTTPError) and error.code not in {429, 500, 502, 503, 504}:
                raise ValueError('Public cache asset download failed for ' + name) from None


def load_controller(path, expected):
    require(sha256(path.read_bytes()).hexdigest() == expected, 'Unreviewed public cache verifier code')
    spec = importlib.util.spec_from_file_location('reviewed_cache', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def validate_metadata(controller, pin, manifest, index_bytes):
    require(pin['tag'] == TAG and pin['releaseId'] == RELEASE_ID and pin['architecture'] == SYSTEM,
            'Unexpected exact public development cache')
    require(sha256(manifest).hexdigest() == pin['manifestSha256']
            and sha256(index_bytes).hexdigest() == pin['indexSha256'],
            'Public cache metadata differs from independently verified bytes')
    require(controller.decoded(manifest) == {
        'schema': 1, 'kind': 'assbox-development-kernel-formatter-distribution', 'channel': 'development',
        'tag': TAG, 'coreCommit': pin['publisher'], 'canonicalSourceCommit': pin['publishedProduct'],
        'canonicalSourceTree': pin['publishedTree'], 'controllerSha256': pin['cacheControllerSha256'],
        'lockSha256': pin['lockSha256'], 'productionReleaseQualified': False, 'installationQualified': False,
    }, 'Unexpected verified development manifest scope')
    index = controller.validate_index(index_bytes, release_sha=pin['manifestSha256'], core=pin['publisher'],
                                      lock_sha=pin['lockSha256'], system=SYSTEM, expected=pin['inputs'],
                                      expected_formatter=pin['inputs']['formatter'])
    require(len(index['closure']) == pin['closurePaths'], 'Public cache closure size changed')
    return index


def stage_cache(controller, pin, directory):
    manifest = directory/'release.json'
    index_file = directory/controller.index_name(SYSTEM)
    download(manifest.name, manifest, 65536)
    download(index_file.name, index_file, controller.MAX_INDEX)
    index = validate_metadata(controller, pin, manifest.read_bytes(), index_file.read_bytes())
    cache = directory/'cache-assets'
    cache.mkdir(mode=0o700)

    def fetch(item):
        asset, record = item
        path = cache/asset
        download(controller.prefix(SYSTEM)+asset, path, record['size'])
        require(path.stat().st_size == record['size'] and controller.file_digest(path) == record['sha256'],
                'Public cache asset bytes differ from signed index')

    with ThreadPoolExecutor(max_workers=6) as pool:
        list(pool.map(fetch, index['cacheAssets'].items()))
    controller.validate_cache(cache, index)
    return cache, index


def verify_authority(product, authority, pin):
    expected = {'RUNNER_ENVIRONMENT': 'github-hosted', 'GITHUB_REPOSITORY': REPOSITORY,
                'GITHUB_REPOSITORY_ID': '1402455771', 'GITHUB_REPOSITORY_OWNER_ID': '327835666',
                'GITHUB_REF': REF, 'GITHUB_EVENT_NAME': 'workflow_dispatch', 'GITHUB_RUN_ATTEMPT': '1'}
    require(all(os.environ.get(key) == value for key, value in expected.items()), 'Unexpected hosted authority')
    require(not any(key in os.environ for key in ('GH_TOKEN', 'GITHUB_TOKEN', 'ACTIONS_RUNTIME_TOKEN',
                'ACTIONS_ID_TOKEN_REQUEST_TOKEN', 'ACTIONS_ID_TOKEN_REQUEST_URL')),
            'Unexpected credentials in public cache process')
    require(platform.system() == 'Linux' and platform.machine() == 'aarch64', 'Native ARM required')
    for repo, refs, known in (
        (product, ['HEAD','HEAD^{tree}'], [pin['product'],pin['tree']]),
        (authority, ['HEAD'], [os.environ['GITHUB_SHA']]),
    ):
        git = ['git','--no-replace-objects','-C',repo]
        require(subprocess.check_output([*git,'rev-parse',*refs],text=True).splitlines() == known
                and not subprocess.check_output([*git,'status','--porcelain']), 'Unexpected source or authority checkout')


def main():
    product, receipt = (Path(arg).resolve() for arg in sys.argv[1:])
    experiment = Path(__file__).resolve().parent
    pin = json.loads((experiment/'v71-arm-kernel-formatter.json').read_bytes())
    verify_authority(product, experiment, pin)
    controller = load_controller(product/'scripts/kernel_cache.py', pin['cacheControllerSha256'])
    require(controller.file_digest(product/'flake.lock') == pin['lockSha256'], 'Product lock differs')
    with tempfile.TemporaryDirectory(prefix='assbox-public-arm-cache-',dir=receipt.parent.parent) as name:
        directory = Path(name)
        env = controller.environment(directory)
        kernel = controller.kernel_identity(env, product, SYSTEM)
        formatter = controller.formatter_identity(env, product, SYSTEM)
        require({**kernel, 'formatter': formatter} == pin['inputs'], 'Candidate selects different native inputs')
        cache, index = stage_cache(controller, pin, directory)
        nix = shutil.which('nix', path=env['PATH'])
        require(nix and Path(nix).resolve(strict=True).is_relative_to('/nix/store'), 'Expected provisioned Nix')
        outputs = [*kernel['outputs'].values(), formatter['output']]
        subprocess.run(['/usr/bin/sudo','-n','--',nix,'copy','--offline','--from',cache.as_uri(),'--to','daemon',
                        '--option','trusted-public-keys',index['publicKey'],'--option','require-sigs','true',
                        '--option','substituters','',*outputs], env=env, stdin=subprocess.DEVNULL,
                        check=True, timeout=900)
        copied = controller.decoded(controller.run(env, 'nix','path-info','--offline','--recursive','--json',
                                                  '--json-format','1',*outputs))
        require(set(copied) == set(index['closure']) and all(
            {field: item[field] for field in STORE_FIELDS} == index['closure'][path] for path,item in copied.items()
        ), 'Native store differs from verified public cache')
        config = (Path(kernel['outputs']['dev'])/'lib/modules'/kernel['kernelVersion']/'build/.config')
        require(controller.file_digest(config,store_file=True) == index['configSha256'],
                'Imported kernel configuration differs from the verified public cache')
    with receipt.open('x') as stream:
        json.dump({**pin, 'verifiedAssets':len(index['cacheAssets']), 'signatureRequired':True,
                   'builtDerivation':False, 'importedAt':datetime.now(timezone.utc).isoformat()},stream,indent=2)
        stream.write('\n')
    print('Imported independently verified signed kernel and formatter closure with',len(copied),'paths.',flush=True)


if __name__ == '__main__':
    os.umask(0o077)
    main()
