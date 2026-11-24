from datetime import datetime,timezone
from hashlib import file_digest
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys

product, destination, nix = map(Path,sys.argv[1:4])
settings=sys.argv[4:]
assert settings in ([],['--offline'])
product=product.resolve(strict=True)
destination=destination.resolve(strict=True)
assert platform.system()=='Linux' and platform.machine() in ('x86_64','aarch64')
system=platform.machine()+'-linux'
source='d3d36054d98d1ccf3ab37853fd4c23b5621e72d5'
tree='ac7bc49124a59ad59bca1afde3d755dd88ec7370'
lock_hash='ea86256a5c0755b5dc022ef446202ea28b404144a7a2eb2202199a58c3ec57b7'
def digest(path):
    with path.open('rb') as stream:
        return file_digest(stream,'sha256').hexdigest()
def git(*args):
    return subprocess.check_output(['git','--no-replace-objects','-C',str(product),*args],text=True)
assert git('rev-parse','HEAD','HEAD^{tree}').splitlines()==[source,tree] and not git('status','--porcelain')
assert digest(product/'flake.lock')==lock_hash
authority=None
if os.environ.get('GITHUB_ACTIONS')=='true':
    expected={'RUNNER_ENVIRONMENT':'github-hosted','GITHUB_REPOSITORY':'assboxai/assbox',
              'GITHUB_REPOSITORY_ID':'1402455771','GITHUB_REPOSITORY_OWNER_ID':'327835666',
              'GITHUB_REF':'refs/heads/test/aarch64-current-profile-policy','GITHUB_EVENT_NAME':'workflow_dispatch',
              'GITHUB_RUN_ATTEMPT':'1'}
    assert system=='aarch64-linux' and all(os.environ.get(key)==value for key,value in expected.items())
    assert not {'GH_TOKEN','GITHUB_TOKEN','ACTIONS_RUNTIME_TOKEN','ACTIONS_ID_TOKEN_REQUEST_TOKEN',
                'ACTIONS_ID_TOKEN_REQUEST_URL'} & os.environ.keys()
    workflow=os.environ['GITHUB_SHA']
    assert re.fullmatch('[0-9a-f]{40}',workflow)
    controller=Path(__file__).resolve().parent
    assert subprocess.check_output(['git','-C',str(controller),'rev-parse','HEAD'],text=True).strip()==workflow
    assert not subprocess.check_output(['git','-C',str(controller),'status','--porcelain'])
    authority={'workflow':workflow,'run':int(os.environ['GITHUB_RUN_ID']),'attempt':1}
nix_command=[str(nix),'--extra-experimental-features','nix-command flakes']
opts=('--no-update-lock-file','--no-write-lock-file',*settings)
selector='.#checks.'+system
native=subprocess.check_output([*nix_command,'eval','--raw','--impure','--expr','builtins.currentSystem'],
                               cwd=product,text=True,timeout=45)
assert native==system
def run_json(argv,timeout=360):
    return json.loads(subprocess.check_output([*nix_command,*argv],cwd=product,timeout=timeout))
names=run_json(['eval','--json',*opts,selector,'--apply','builtins.attrNames'])
active=[name for name in names if name.startswith('policy-'+system+'-')]
assert len(active)==(53 if system=='x86_64-linux' else 49)
assert all(re.fullmatch(r'[a-z0-9_-]+',name) for name in active)
receipt={'source':source,'tree':tree,'architecture':system,'lockSha256':lock_hash,
         'authority':authority,'start':datetime.now(timezone.utc).isoformat(),'selected':active,'results':{}}
with (destination/'native-policy-plan.json').open('x') as stream:
    json.dump(receipt,stream,indent=2)
    stream.write('\n')
for begin in range(0,len(active),6):
    profiles=active[begin:begin+6]
    quoted=' '.join(json.dumps(name) for name in profiles)
    expression=('checks: builtins.listToAttrs (map (name: { inherit name; value = {'
                'derivation=checks.${name}.drvPath; output=checks.${name}.outPath; }; }) [ '+quoted+' ])')
    roots=run_json(['eval','--json',*opts,selector,'--apply',expression])
    assert set(roots)==set(profiles)
    target=[row['derivation']+'^out' for row in roots.values()]
    build=[*nix_command,'build','--no-link','--print-out-paths','--keep-going','--max-jobs','2','--cores','2','-L',*settings,*target]
    build_log=destination/f'profile-policy-build-{begin//6+1:02d}.log'
    with build_log.open('xb') as stream:
        completed=subprocess.run(build,cwd=product,stdout=subprocess.PIPE,stderr=stream,timeout=720,check=True)
    assert set(completed.stdout.decode().splitlines())=={row['output'] for row in roots.values()}
    for name,row in roots.items():
        observed=run_json(['path-info','--offline','--json','--json-format','1',row['output']],timeout=90)
        exact=observed[row['output']]
        assert exact is not None and exact['deriver']==row['derivation']
        output=Path(row['output'])
        data=json.loads(output.read_bytes())
        assert isinstance(data,dict) and data
        receipt['results'][name]={**row,'narHash':exact['narHash'],'policyJsonSha256':digest(output)}
    print('Verified',len(receipt['results']),'of',len(active),'exact native profile policies.',flush=True)
receipt['finishedAt']=datetime.now(timezone.utc).isoformat()
with (destination/'verified-native-profile-policies.json').open('x') as stream:
    json.dump(receipt,stream,indent=2)
    stream.write('\n')
assert not git('status','--porcelain')
