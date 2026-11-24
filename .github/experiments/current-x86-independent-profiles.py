#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Build, inventory and scan the exact independent native x86 profile roots."""
from collections import deque
from datetime import datetime, timezone
from hashlib import file_digest
from importlib.util import module_from_spec, spec_from_file_location
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile

BRANCH = 'refs/heads/test/x86-current-independent-profile-inventories'
HOSTED = {
    'RUNNER_ENVIRONMENT':'github-hosted', 'GITHUB_REPOSITORY':'assboxai/assbox',
    'GITHUB_REPOSITORY_ID':'1402455771', 'GITHUB_REPOSITORY_OWNER_ID':'327835666',
    'GITHUB_EVENT_NAME':'workflow_dispatch', 'GITHUB_RUN_ATTEMPT':'1', 'GITHUB_REF':BRANCH,
}
HERE = Path(__file__).resolve().parent


def save(location, payload):
    with location.open('x') as output:
        json.dump(payload, output, indent=2)
        output.write('\n')


def sha(path):
    with path.open('rb') as stream:
        return file_digest(stream, 'sha256').hexdigest()


def require(condition, detail):
    if not condition:
        raise ValueError(detail)


def main():
    require(platform.system() == 'Linux' and platform.machine() == 'x86_64', 'Native x86 is required')
    require(all(os.environ.get(key) == value for key,value in HOSTED.items()), 'Unexpected native profile workflow authority')
    require(not set(os.environ) & {'GH_TOKEN','GITHUB_TOKEN','ACTIONS_RUNTIME_TOKEN',
                'ACTIONS_ID_TOKEN_REQUEST_TOKEN','ACTIONS_ID_TOKEN_REQUEST_URL'}, 'Unexpected credentials')
    phase, product, evidence = sys.argv[1:]
    require(phase in ('evaluate','realize'), 'Unexpected native profile phase')
    product, evidence = (Path(item).resolve(strict=True) for item in (product,evidence))
    plan = json.loads((HERE/'current-x86-independent-profile-plan.json').read_bytes())
    source, tree = plan['source'], plan['tree']
    group = os.environ['INPUT_GROUP']
    expected = plan['groups'][group]
    for checkout, identities in ((product,[source,tree]),(HERE,[os.environ['GITHUB_SHA']])):
        git = ['git','--no-replace-objects','-C',str(checkout)]
        refs = ['HEAD','HEAD^{tree}'] if len(identities) == 2 else ['HEAD']
        require(subprocess.check_output([*git,'rev-parse',*refs],text=True).splitlines() == identities
                and not subprocess.check_output([*git,'status','--porcelain']), 'Unexpected checked-out Git identity')
    require(sha(product/'flake.lock') == plan['lockSha256'], 'Product lock identity changed')
    os.chdir(product)
    sys.path.insert(0,str(product/'scripts'))
    import kernel_cache as tools
    with tempfile.TemporaryDirectory(prefix='assbox-native-x86-profiles-', dir=evidence.parent) as scratch:
        env = tools.environment(Path(scratch))
        env['NIX_CONFIG'] += 'max-jobs = 2\ncores = 3\neval-cores = 2\n'
        settings = ('--no-update-lock-file','--no-write-lock-file')
        for name, row in expected.items():
            built = tools.decoded(tools.run(env,'nix','eval','--json',*settings,
                '.#'+row['attribute'],'--apply','p: { derivation = p.drvPath; output = p.outPath; }',timeout=180))
            require(all(built[key] == row[key] for key in ('derivation','output')), f'Exact profile changed for {name}')
        if phase == 'evaluate':
            save(evidence/'evaluation.json',expected)
            save(evidence/'scope.json',{
                'source':source,'tree':tree,'lockSha256':plan['lockSha256'],'group':group,'architecture':'x86_64-linux',
                'controller':os.environ['GITHUB_SHA'],'run':int(os.environ['GITHUB_RUN_ID']),'attempt':1,
                'observedAt':datetime.now(timezone.utc).isoformat(),
            })
            return

        selected = json.loads((evidence/'evaluation.json').read_bytes())
        require(selected == expected, 'Native profile list changed across stages')
        seed = json.loads((evidence/'kernel-import.json').read_bytes())
        require(seed['source'] == source and seed['tree'] == tree and seed['kernelBuildInvoked'] is False
                and seed['derivation'] == plan['kernel']['derivation'], 'Verified kernel import receipt changed')
        wanted = [row['derivation']+'^out' for row in expected.values()]
        command = ['nix','build','--no-link','--print-out-paths','--keep-going','-L',*settings,*wanted]
        build_log = Path(scratch)/'native-build.log'
        with build_log.open('xb') as log:
            try:
                status = subprocess.run(command,env=env,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,timeout=16200).returncode
            except subprocess.TimeoutExpired:
                status = 124
        with build_log.open('rb') as log:
            tail = deque(log,maxlen=240)
        (evidence/'build-tail.log').write_bytes(b''.join(tail))
        available = {}
        for name, row in expected.items():
            checked = subprocess.run(['nix-store','--check-validity',row['output']],env=env,
                    capture_output=True,text=True,timeout=60)
            if checked.returncode == 0:
                available[name] = row
        save(evidence/'build-result.json',{'exit':status,'realized':available,'requested':list(expected),
                                             'buildLogSha256':sha(build_log)})
        require(available, 'No exact native profile output registered')
        output_paths = [row['output'] for row in available.values()]
        closure = tools.decoded(tools.run(env,'nix','path-info','--recursive','--json','--json-format','1',*output_paths,timeout=180))
        require(set(output_paths) <= closure.keys(), 'Exact native output is absent from its registry')
        save(evidence/'native-registry.json',closure)

        expression = ('let f = builtins.getFlake (toString ./.); '
                      'p = import f.inputs.nixpkgs {system = "x86_64-linux";}; '
                      'in { scanner = p.vulnix.drvPath; shell = p.bash.drvPath; }')
        tool_paths=tools.decoded(tools.run(env,'nix','eval','--impure','--json','--expr',expression,timeout=180))
        common=('nix','build','--no-link','--print-out-paths','-L')
        scanner=tools.run(env,*common,tool_paths['scanner']+'^out',timeout=2400).decode().strip()+'/bin/vulnix'
        shell=tools.run(env,*common,tool_paths['shell']+'^out',timeout=600).decode().strip()+'/bin/bash'
        require(tools.run(env,scanner,'--version',timeout=30).decode().strip()=='vulnix 1.12.4',
                'Unexpected release scanner version')
        if len(output_paths) == 1:
            reference = output_paths[0]
        else:
            spec = spec_from_file_location('native_profile_union',HERE/'native-profile-union.py')
            union = module_from_spec(spec)
            spec.loader.exec_module(union)
            expr = union.reference_expression(output_paths,shell)
            reference = tools.run(env,*common,'--offline','--impure','--expr',expr,timeout=180).decode().strip()
            actual = tools.decoded(tools.run(env,'nix','path-info','--recursive','--json','--json-format','1',reference,timeout=180))
            require(set(actual.pop(reference)['references']) == set(output_paths) and actual == closure,
                    'Native scanner reference differs from the union of exact profile outputs')
        save(evidence/'scanner-roots.json',{'tested':output_paths,'reference':reference,'nativePathCount':len(closure),
                                             'inputRegistrySha256':sha(evidence/'native-registry.json')})
        cache = Path(scratch)/'fresh-vulnix'
        cache.mkdir(mode=0o700)
        feed = 'https://nvd.nist.gov/feeds/json/cve/2.0/'
        report = evidence/'raw-vulnix.json'
        scanner_log = evidence/'vulnix.log'
        with report.open('xb') as out, scanner_log.open('xb') as note:
            scan = subprocess.run([scanner,'--verbose','--cache-dir',cache,'--mirror',feed,reference,'--closure','--json'],
                                  env=env,stdin=subprocess.DEVNULL,stdout=out,stderr=note,timeout=1200).returncode
        loaded = scanner_log.read_text()
        year = datetime.now(timezone.utc).year
        require(scan in (0,2) and isinstance(json.loads(report.read_bytes()),list), 'Pinned native Vulnix did not finish normally')
        require(all(f'Loading {feed}nvdcve-2.0-{item}.json.gz' in loaded for item in range(year-5,year+1))
                and 'Reindexing database' in loaded and (cache/'Data.fs').stat().st_size > 0,
                'The pinned scanner did not ingest the expected public NVD archives')
        save(evidence/'scan-result.json',{'source':source,'tree':tree,'group':group,'scanExit':scan,
                                         'rootCount':len(available),'originalBuildExit':status,'packagePaths':len(closure),
                                         'rawSha256':sha(report),'freshNvdIndexSha256':sha(cache/'Data.fs'),
                                         'observedAt':datetime.now(timezone.utc).isoformat()})


if __name__ == '__main__':
    os.umask(0o077)
    main()
