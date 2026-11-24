#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Run the exact native authenticated plain UEFI installer check."""
from datetime import datetime, timezone
from hashlib import file_digest
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
from tempfile import TemporaryDirectory

HERE = Path(__file__).resolve().parent
AUTHORITY = {
    'RUNNER_ENVIRONMENT':'github-hosted', 'GITHUB_REPOSITORY':'assboxai/assbox',
    'GITHUB_REPOSITORY_ID':'1402455771', 'GITHUB_REPOSITORY_OWNER_ID':'327835666',
    'GITHUB_EVENT_NAME':'workflow_dispatch', 'GITHUB_RUN_ATTEMPT':'1',
    'GITHUB_REF':'refs/heads/test/x86-current-signed-uefi512', 'INPUT_GROUP':'install-boot-uefi-512',
}
TOKENS = {'GH_TOKEN', 'GITHUB_TOKEN', 'ACTIONS_RUNTIME_TOKEN',
          'ACTIONS_ID_TOKEN_REQUEST_TOKEN', 'ACTIONS_ID_TOKEN_REQUEST_URL'}

def require(value, message):
    if not value:
        raise ValueError(message)

def digest(path):
    with path.open('rb') as handle:
        return file_digest(handle, 'sha256').hexdigest()

def json_file(path):
    return json.loads(path.read_bytes())

def save(path, data):
    with path.open('x') as stream:
        json.dump(data, stream, indent=2)
        stream.write('\n')

def check_checkout(checkout, arguments, expected):
    git = ['git','--no-replace-objects','-C',str(checkout)]
    require(subprocess.check_output(git + ['rev-parse', *arguments], text=True).splitlines() == expected
            and not subprocess.check_output(git + ['status','--porcelain']), 'Unexpected checkout')

def main():
    phase = sys.argv[1]
    source, evidence = (Path(argument).resolve(strict=True) for argument in sys.argv[2:4])
    require(platform.system() == 'Linux' and platform.machine() == 'x86_64', 'Native x86 Linux is required')
    require(all(os.environ.get(key) == value for key, value in AUTHORITY.items())
            and not TOKENS & os.environ.keys(), 'Unexpected hosted authority or credentials')
    plan = json_file(HERE / 'current-x86-signed-uefi512-plan.json')
    workflow = os.environ['GITHUB_SHA']
    require(re.fullmatch('[0-9a-f]{40}', workflow), 'Unexpected workflow revision')
    run_id = os.environ['GITHUB_RUN_ID']
    require(re.fullmatch('[1-9][0-9]*', run_id), 'Unexpected workflow run identifier')
    check_checkout(HERE, ['HEAD'], [workflow])
    check_checkout(source, ['HEAD','HEAD^{tree}'], [plan['source'],plan['tree']])
    require(digest(source / 'flake.lock') == plan['lockSha256'], 'Unexpected product lock')
    sys.path.insert(0, str(source / 'scripts'))
    import kernel_cache as tools
    selection = plan['groups'][AUTHORITY['INPUT_GROUP']]
    root = selection[AUTHORITY['INPUT_GROUP']]
    with TemporaryDirectory(prefix='assbox-native-x86-uefi512-', dir=evidence.parent) as temporary:
        env = tools.environment(Path(temporary))
        if phase == 'evaluate':
            selector = source.as_uri().replace('file:','git+file:',1) + '?rev=' + plan['source']
            attr = selector + '#' + plan['attribute']
            actual = tools.decoded(tools.run(env,'nix','eval','--json','--no-update-lock-file','--no-write-lock-file',
                                            attr, '--apply','p: { derivation = p.drvPath; output = p.outPath; }'))
            require(all(root[key] == value for key, value in actual.items()), 'Unexpected exact signed UEFI test derivation')
            recipe = tools.decoded(tools.run(env,'nix','derivation','show',root['derivation']))
            recipe = recipe['derivations'][Path(root['derivation']).name]
            require(recipe['system'] == 'x86_64-linux'
                    and set(recipe['env']['requiredSystemFeatures'].split()) == {'kvm', 'nixos-test'},
                    'The installer check did not require native KVM')
            save(evidence / 'evaluation.json', selection)
            return
        require(phase == 'verify' and json_file(evidence / 'evaluation.json') == selection, 'Missing exact gate evaluation')
        kernel = json_file(evidence / 'kernel-import.json')
        require((kernel['source'],kernel['tree'],kernel['system'],kernel['kernelBuildInvoked'])
                == (plan['source'],plan['tree'],'x86_64-linux',False), 'Missing verified kernel import')
        kvm = json_file(evidence / 'native-kvm-build-user.json')
        require(kvm['architecture'] == 'x86_64' and kvm['apiVersion'] == 12 and kvm['createVm'] is True
                and kvm['buildUser'].startswith('nixbld'), 'Missing actual sandbox build-user KVM access')
        config = tools.decoded(tools.run(env, 'nix','config','show','--json'))
        require(config['sandbox']['value'] is True and config['sandbox-fallback']['value'] is False
                and config['access-tokens']['value'] == {}, 'Unexpected native Nix configuration or credentials')
        output_log = evidence / 'native-output.txt'
        log_path = evidence / 'native-build.log'
        started = datetime.now(timezone.utc).isoformat()
        args = ['nix','build','--no-link','--print-out-paths','--max-jobs','2','--cores','4','-L',root['derivation']+'^out']
        with output_log.open('xb') as output, log_path.open('xb') as log:
            status = subprocess.run(args, env=env, stdin=subprocess.DEVNULL, stdout=output, stderr=log, timeout=16500)
        log_data = log_path.read_bytes()
        built = root['derivation'].encode()
        ran_driver = b"building '" + built + b"'..." in log_data and b'test script finished in ' in log_data
        record = {
            'source':plan['source'],'tree':plan['tree'],'architecture':'x86_64-linux','attestationScope':'hosted native KVM diagnostic',
            'runId':int(run_id),'attempt':1,'workflow':workflow,'attribute':plan['attribute'],
            'derivation':root['derivation'],'output':root['output'],'exit':status.returncode,'ranOriginalVmDriver':ran_driver,
            'startedAt':started,'finishedAt':datetime.now(timezone.utc).isoformat(),
            'logSha256':digest(log_path),'kernelImportSha256':digest(evidence / 'kernel-import.json'),
            'nativeKvmSha256':digest(evidence / 'native-kvm-build-user.json'),
        }
        if status.returncode == 0:
            require(ran_driver and output_log.read_text().splitlines() == [root['output']], 'Expected a fresh exact native VM execution')
            actual_registry = tools.decoded(tools.run(env, 'nix','path-info','--offline','--json','--json-format','1',root['output']))
            require(set(actual_registry) == {root['output']} and actual_registry[root['output']]['deriver'] == root['derivation'],
                    'Unexpected exact native result registration')
            record['registeredNarHash'] = actual_registry[root['output']]['narHash']
            check_checkout(source, ['HEAD','HEAD^{tree}'], [plan['source'],plan['tree']])
        save(evidence / 'native-result.json', record)
        return status.returncode

if __name__ == '__main__':
    os.umask(0o077)
    sys.exit(main())
