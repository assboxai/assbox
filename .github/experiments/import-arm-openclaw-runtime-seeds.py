#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Import only signed inputs that the exact native OpenClaw wrapper graph selects."""
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

BRANCH = 'refs/heads/test/arm-openclaw-runtime-verified-inputs'
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
    direct = pin['selected']
    inherited = pin.get('closureSelected', {})
    require(not direct.keys() & inherited.keys(), 'Duplicate signed output recipe')
    for derivation, requested in (direct | inherited).items():
        name = Path(derivation).name
        require(STORE_PATH.fullmatch(derivation) and name in live and name in recipes,
                'Signed input is outside the exact native OpenClaw wrapper graph')
        evaluated = recipes[name]
        require(evaluated['system'] == 'aarch64-linux', 'Signed derivation is not native ARM')
        for output, path in requested.items():
            require(STORE_PATH.fullmatch(path) and output in live[name]['outputs'],
                    'Signed output is outside the current native OpenClaw dependency selection')
            require('/nix/store/' + evaluated['outputs'][output]['path'] == path and path in index['closure'],
                    'Signed output differs from the native evaluation or archive')
            if derivation in direct:
                require(source[derivation][output] == path, 'Direct signed output changed')
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
    require(platform.system()=="Linux" and platform.machine()=="aarch64","Expected native ARM Linux")
    require(all(os.environ.get(key)==value for key,value in AUTHORITY.items()) and not CREDENTIALS & os.environ.keys(),
            "Unexpected ARM OpenClaw input authority or credentials")
    product, downloads, evidence = (Path(arg).resolve(strict=True) for arg in sys.argv[1:])
    authority=Path(__file__).resolve().parent
    plan=json.loads((authority/"native-arm-openclaw-runtime-seeds.json").read_bytes())
    for checkout, expected in ((authority,[os.environ["GITHUB_SHA"]]),(product,[plan["source"],plan["tree"]])):
        git=["git","--no-replace-objects","-C",str(checkout)]
        refs=["HEAD","HEAD^{tree}"] if len(expected)==2 else ["HEAD"]
        require(subprocess.check_output(git+["rev-parse",*refs],text=True).splitlines()==expected
                and not subprocess.check_output(git+["status","--porcelain"]),"Unexpected OpenClaw checkout")
    selected=json.loads((evidence/"bindings.json").read_bytes())["package"]
    require(selected==[{"drvPath":plan["parentProfile"],"output":plan["parentOutput"]}],
            "The native OpenClaw wrapper has changed")
    require({item.name for item in downloads.iterdir()}=={pin["group"] for pin in plan["packageInputs"]},
            "Unexpected OpenClaw dependency downloads")
    sys.path.insert(0,str(product/"scripts"))
    import kernel_cache as tools

    with tempfile.TemporaryDirectory(prefix="assbox-signed-arm-openclaw-seeds-",dir=evidence.parent) as area:
        work=Path(area)
        env=tools.environment(work)
        require(tools.file_digest(product/"flake.lock")=="ea86256a5c0755b5dc022ef446202ea28b404144a7a2eb2202199a58c3ec57b7",
                "The native package lock has changed")
        graph=tools.decoded(tools.run(env,"nix","derivation","show","--recursive",plan["parentProfile"],
                                     timeout=180))["derivations"]
        live={}
        for row in graph.values():
            for name, requested in row["inputs"]["drvs"].items():
                require(not requested["dynamicOutputs"],"Unexpected dynamic OpenClaw dependency")
                live.setdefault(name,{"outputs":set()})["outputs"].update(requested["outputs"])
        nix=shutil.which("nix",path=env["PATH"])
        require(nix and Path(nix).resolve(strict=True).is_relative_to("/nix/store"),"Expected provisioned Nix")
        verified=[]
        for pin in plan["packageInputs"]:
            name=pin["group"]
            require(re.fullmatch(r"[a-z][a-z-]*",name),"Unexpected native dependency group")
            files=list((downloads/name).iterdir())
            require(len(files)==1,"Expected one verified input archive")
            target=work/name
            target.mkdir(mode=0o700)
            index,cache=extract(files[0],target,pin,tools)
            paths=sorted(exact_selected_outputs(pin,index,live,graph))
            subprocess.run(["/usr/bin/sudo","-n","--",nix,"copy","--offline","--from",cache.as_uri(),"--to","daemon",
                            "--option","trusted-public-keys",index["publicKey"],"--option","require-sigs","true",
                            "--option","substituters","",*paths],env=env,stdin=subprocess.DEVNULL,timeout=1200,check=True)
            readback=tools.decoded(tools.run(env,"nix","path-info","--offline","--recursive","--json","--json-format","1",
                                             *paths,timeout=180))
            wanted=expected_closure(paths,index["closure"])
            require(readback.keys()==wanted.keys() and all(
                {key:row[key] for key in ("narHash","narSize","references")}==wanted[path]
                for path,row in readback.items()),"Native package registrations differ from the signed closure")
            verified.append({"group":name,"artifact":pin["artifact"],"producerRun":pin["producerRun"],
                             "paths":paths,"closurePaths":len(readback),"selected":pin["selected"],
                             "archiveSha256":pin["artifactSha256"]})
            shutil.rmtree(target)
        require(len(verified)==2,"Expected tested Node and mypy package imports")
        scope={"source":plan["source"],"tree":plan["tree"],"architecture":"aarch64-linux",
               "parentProfile":plan["parentProfile"],"verified":verified,
               "observedAt":datetime.now(timezone.utc).isoformat()}
        with (evidence/"package-inputs-import.json").open("x") as stream:
            json.dump(scope,stream,indent=2)
            stream.write("\n")


if __name__ == "__main__":
    os.umask(0o077)
    main()
