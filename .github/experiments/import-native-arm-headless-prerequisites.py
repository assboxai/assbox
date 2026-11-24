#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Import only signed inputs that the exact native headless dependency graph selects."""
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import platform
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from zipfile import ZipFile

BRANCH = 'refs/heads/test/arm-current-headless-prerequisites'
AUTHORITY = {
    'RUNNER_ENVIRONMENT': 'github-hosted', 'GITHUB_REPOSITORY': 'assboxai/assbox',
    'GITHUB_REPOSITORY_ID': '1402455771', 'GITHUB_REPOSITORY_OWNER_ID': '327835666',
    'GITHUB_EVENT_NAME': 'workflow_dispatch', 'GITHUB_RUN_ATTEMPT': '1', 'GITHUB_REF': BRANCH,
}
CREDENTIALS = {
    'GH_TOKEN', 'GITHUB_TOKEN', 'ACTIONS_RUNTIME_TOKEN', 'ACTIONS_ID_TOKEN_REQUEST_TOKEN',
    'ACTIONS_ID_TOKEN_REQUEST_URL',
}
MAX_MEMBERS = 8193
MAX_ARCHIVE = 4 * 1024**3
STORE_PATH = re.compile(r'/nix/store/[0-9a-z]{32}-[A-Za-z0-9.+_?=-]+')


def require(value, result):
    if not value:
        raise ValueError(result)


def extract(archive, directory, pin, tools):
    require(archive.is_file() and not archive.is_symlink(), 'Expected a regular signed input archive')
    require(0 < archive.stat().st_size == pin['zipBytes'] <= MAX_ARCHIVE, 'Unexpected signed artifact size')
    require('sha256:' + tools.file_digest(archive) == pin['artifactSha256'], 'Signed artifact checksum changed')
    cache = directory / 'signed-cache'
    cache.mkdir(mode=0o700)
    with ZipFile(archive) as zipped:
        files = [member for member in zipped.infolist() if not member.is_dir()]
        named = {member.filename: member for member in files}
        require(3 <= len(files) == len(named) <= MAX_MEMBERS, 'Unexpected artifact file count')
        require(sum(member.file_size for member in files) <= MAX_ARCHIVE, 'Signed artifact is oversized')
        index_member = named.pop('index.json')
        require(0 < index_member.file_size <= 16 * 1024**2, 'Signed manifest is oversized')
        require(stat.S_IFMT(index_member.external_attr >> 16) in (0, stat.S_IFREG), 'Invalid signed manifest type')
        payload = zipped.read(index_member)
        require(sha256(payload).hexdigest() == pin['rawIndexSha256'], 'Signed manifest checksum changed')
        index = json.loads(payload)
        require(index['identity'] == pin['identity'] and index['publicKey'] == pin['publicKey'],
                'Signed artifact authority differs from verified pin')
        require(index['architecture'] == 'aarch64-linux' and index['group'] == pin['group'],
                'Signed artifact has a different architecture or group')
        require(index['source'] == pin['source'] and index['tree'] == pin['tree'], 'Signed source changed')
        assets = index['cacheAssets']
        require(set(named) == {'signed-cache/' + name for name in assets}, 'Unexpected signed cache members')
        for name, expected in assets.items():
            require(re.fullmatch(tools.ASSET, name), 'Invalid signed cache asset name')
            member = named['signed-cache/' + name]
            require(stat.S_IFMT(member.external_attr >> 16) in (0, stat.S_IFREG)
                    and 0 < member.file_size == expected['size'] <= tools.MAX_ASSET, 'Invalid signed asset type or size')
            with zipped.open(member) as stream, (cache / name).open('xb') as output:
                shutil.copyfileobj(stream, output, 1024 * 1024)
    tools.validate_cache(cache, index)
    return index, cache


def exact_selected_outputs(pin, index, live, recipes):
    source = {record['derivation']: record['outputs'] for record in index['exactRoots']}
    result = {}
    for derivation, requested in pin['selected'].items():
        name = Path(derivation).name
        require(STORE_PATH.fullmatch(derivation) and name in live and name in recipes,
                'Signed input is outside the exact headless prerequisite graph')
        evaluated = recipes[name]
        require(evaluated['system'] == 'aarch64-linux', 'Signed derivation is not native ARM')
        for output, path in requested.items():
            require(STORE_PATH.fullmatch(path) and output in live[name]['outputs'],
                    'Signed output is outside the current headless prerequisite selection')
            require(source[derivation][output] == path and '/nix/store/' + evaluated['outputs'][output]['path'] == path,
                    'Signed output differs from the native evaluation')
            result[path] = index['closure'][path]
    require(result, 'No matching direct native output in this archive')
    return result


def expected_closure(paths, registry):
    pending, result = list(paths), {}
    while pending:
        path = pending.pop()
        if path in result:
            continue
        row = registry[path]
        result[path] = row
        pending.extend(row['references'])
    return result


def main():
    require(platform.system() == 'Linux' and platform.machine() == 'aarch64', 'Native ARM Linux is required')
    require(all(os.environ.get(key) == value for key, value in AUTHORITY.items()) and not CREDENTIALS & os.environ.keys(),
            'Unexpected hosted authority or credentials')
    product, downloads, evidence = (Path(argument).resolve(strict=True) for argument in sys.argv[1:])
    controller = Path(__file__).resolve().parent
    plan = json.loads((controller / 'native-arm-headless-prerequisites.json').read_bytes())
    for checkout, expected in ((controller, [os.environ['GITHUB_SHA']]), (product, [plan['source'], plan['tree']])):
        git = ['git','--no-replace-objects','-C',str(checkout)]
        args = ['HEAD','HEAD^{tree}'] if len(expected) == 2 else ['HEAD']
        require(subprocess.check_output(git + ['rev-parse', *args], text=True).splitlines() == expected
                and not subprocess.check_output(git + ['status','--porcelain']), 'Unexpected checkout')
    sys.path.insert(0, str(product / 'scripts'))
    import kernel_cache as tools
    require(tools.file_digest(product / 'flake.lock') == plan['lockSha256'], 'Product lock changed')
    with tempfile.TemporaryDirectory(prefix='verified-arm-headless-inputs-', dir=evidence.parent) as work:
        area = Path(work)
        env = tools.environment(area)
        selector = product.as_uri().replace('file:','git+file:',1) + '?rev=' + plan['source']
        wrapper = tools.run(env, 'nix', 'eval', '--raw', '--no-update-lock-file', '--no-write-lock-file',
                            selector + '#nixosConfigurations.aarch64-linux-uefi-none-headless.config.system.build.toplevel.drvPath').decode().strip()
        require(wrapper == plan['parentProfile'], 'Native headless profile changed')
        roots = [item["derivation"] for item in plan["groups"]["headless-prerequisites"]]
        admissible = set(tools.run(env, 'nix-store', '--query', '--requisites', wrapper).decode().splitlines())
        require(set(roots) <= admissible, 'Native prerequisite recipes changed')
        graph = tools.decoded(tools.run(env, 'nix', 'derivation', 'show', '--recursive', *roots))['derivations']
        live = {}
        for row in graph.values():
            for key, selected in row['inputs']['drvs'].items():
                require(not selected['dynamicOutputs'], 'Unexpected dynamic native input')
                live.setdefault(key, {'outputs': set()})['outputs'].update(selected['outputs'])
        nix = shutil.which('nix', path=env['PATH'])
        require(nix and Path(nix).resolve(strict=True).is_relative_to('/nix/store'), 'Expected provisioned native Nix')
        claims, found = [], set()
        for pin in plan['archives']:
            group = pin['group']
            require(re.fullmatch(r'[a-z][a-z-]*', group), 'Invalid input group')
            download = downloads / group
            archives = list(download.iterdir())
            require(len(archives) == 1, 'Unexpected group download inventory')
            directory = area / group
            directory.mkdir(mode=0o700)
            index, cache = extract(archives[0], directory, pin, tools)
            recipes = tools.decoded(tools.run(env,'nix','derivation','show',*sorted(pin['selected'])))['derivations']
            paths = sorted(exact_selected_outputs(pin,index,live,recipes))
            require(not set(paths) & found, 'Duplicate exact direct input across archives')
            found.update(paths)
            subprocess.run(['/usr/bin/sudo','-n','--',nix,'copy','--offline','--from',cache.as_uri(),'--to','daemon',
                            '--option','trusted-public-keys',index['publicKey'],'--option','require-sigs','true',
                            '--option','substituters','',*paths],
                           env=env,stdin=subprocess.DEVNULL,check=True,timeout=1200)
            actual = tools.decoded(tools.run(env,'nix','path-info','--offline','--recursive','--json','--json-format','1',*paths))
            expected = expected_closure(paths,index['closure'])
            require(actual.keys() == expected.keys() and all(
                {key:row[key] for key in ('narHash','narSize','references')} == expected[path] for path,row in actual.items()),
                'Native store registration differs from the signed input closure')
            claims.append({'group':group,'run':pin['identity']['GITHUB_RUN_ID'],'artifact':pin['artifact'],
                           'rootCount':len(paths),'closurePaths':len(actual)})
            shutil.rmtree(directory)
        require(len(claims) == len(plan['archives']) and len(found) == sum(len(paths) for pin in plan['archives'] for paths in pin['selected'].values()),
                'Incomplete native signed import result')
        with (evidence / 'signed-input-imports.json').open('x') as output:
            json.dump({'source':plan['source'],'tree':plan['tree'],'architecture':'aarch64-linux',
                       'parentProfile':wrapper,'roots':roots,'groups':claims,'selected':len(found),
                       'observedAt':datetime.now(timezone.utc).isoformat()},output,indent=2)
            output.write('\n')


if __name__ == '__main__':
    os.umask(0o077)
    main()
