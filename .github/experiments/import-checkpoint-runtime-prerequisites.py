#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Authenticate planned native prerequisite artifacts before a fresh checkpoint boot."""
from datetime import datetime, timezone
from hashlib import sha256
from importlib.util import module_from_spec, spec_from_file_location
import json
import os
from pathlib import Path, PurePosixPath
import platform
import shutil
import stat
import subprocess
import sys
import tempfile
from zipfile import ZipFile

EXPERIMENT = Path(__file__).resolve().parent
PLAN = EXPERIMENT / "checkpoint-runtime-prerequisites-plan.json"
PINS = EXPERIMENT / "checkpoint-runtime-prerequisites-pins.json"
REPO = "assboxai/assbox"
REPO_ID = 1402455771
OWNER_ID = 327835666
SEED_REF = "refs/heads/test/checkpoint-x86-runtime-seeds-v2"
CHECKPOINT_REF = "refs/heads/test/checkpoint-x86-rust-compiler-v3"
SYSTEM = "x86_64-linux"
FIELDS = ("narHash", "narSize", "references")
MAX_BYTES = 2 * 1024**3
MAX_PATHS = 240


def require(condition, message):
    if not condition:
        raise ValueError(message)


def git(checkout, *arguments):
    return subprocess.check_output(["git","--no-replace-objects","-C",checkout,*arguments],text=True)


def hosted_authority(product, plan):
    require(platform.machine() == "x86_64" and platform.system() == "Linux", "Native x86 Linux required")
    expected = {
        "RUNNER_ENVIRONMENT":"github-hosted", "GITHUB_REPOSITORY":REPO, "GITHUB_REPOSITORY_ID":str(REPO_ID),
        "GITHUB_REPOSITORY_OWNER_ID":str(OWNER_ID), "GITHUB_REF":CHECKPOINT_REF,
        "GITHUB_EVENT_NAME":"workflow_dispatch", "GITHUB_RUN_ATTEMPT":"1",
    }
    require(all(os.environ.get(name)==value for name,value in expected.items()), "Unexpected hosted checkpoint authority")
    credentials = ("GH_TOKEN","GITHUB_TOKEN","ACTIONS_RUNTIME_TOKEN","ACTIONS_ID_TOKEN_REQUEST_TOKEN",
                   "ACTIONS_ID_TOKEN_REQUEST_URL")
    require(not any(name in os.environ for name in credentials), "Credential reached checkpoint package import")
    require(git(EXPERIMENT,"rev-parse","HEAD").strip() == os.environ["GITHUB_SHA"]
            and not git(EXPERIMENT,"status","--porcelain"), "Unexpected checkpoint import controller")
    require(git(product,"rev-parse","HEAD","HEAD^{tree}").splitlines() == [plan["source"],plan["tree"]]
            and not git(product,"status","--porcelain"), "Unexpected checkpoint source during package import")


def stage(cache_tools, plan, group, archive, scratch, pin, seed_run, seed_workflow, plan_hash, forbidden):
    require(archive.is_file() and not archive.is_symlink() and 0 < pin["archiveSize"] <= MAX_BYTES
            and archive.stat().st_size == pin["archiveSize"]
            and cache_tools.file_digest(archive) == pin["archiveSha256"], "Wrong checkpoint seed archive")
    package_rows=plan["groups"][group]
    roots=sorted(path for row in package_rows for path in row["outputs"].values())
    require(pin["roots"] == roots, "Checkpoint seed output pin drifted")
    cache=scratch/"signed-cache"
    cache.mkdir(mode=0o700,parents=True)
    with ZipFile(archive) as zipped:
        entries=zipped.infolist()
        names={item.filename:item for item in entries}
        require(len(names)==len(entries) and "index.json" in names
                and names["index.json"].file_size <= 1024**2, "Invalid checkpoint seed index entry")
        index_bytes=zipped.read("index.json")
        require(sha256(index_bytes).hexdigest()==pin["indexSha256"], "Checkpoint seed index digest mismatch")
        index=json.loads(index_bytes)
        expected={
            "schema":1, "kind":"assbox-native-x86-checkpoint-package-seed", "group":group,
            "source":plan["source"], "tree":plan["tree"], "lockSha256":plan["lockSha256"],
            "planSha256":plan_hash, "architecture":SYSTEM, "repository":REPO,
            "repositoryId":REPO_ID, "ownerId":OWNER_ID, "workflow":seed_workflow, "runId":seed_run,
            "runAttempt":1, "ref":SEED_REF, "bootDerivation":plan["bootDerivation"],
            "isoDerivation":plan["isoDerivation"], "roots":roots, "packages":package_rows,
            "wrongKeyRefused":True, "correctKeyColdImportPassed":True, "publicKey":pin["publicKey"],
        }
        require(all(index.get(name)==value for name,value in expected.items()), "Checkpoint package seed scope mismatch")
        closure=index["closure"]
        require(0<len(closure)<=MAX_PATHS and set(roots)<=set(closure)
                and not forbidden.intersection(closure), "Invalid seed closure or cached checkpoint result")
        assets=index["cacheAssets"]
        require(0<len(assets)<=2*MAX_PATHS+1 and sum(item["size"] for item in assets.values())<=MAX_BYTES
                and set(names)=={"index.json"}|{"signed-cache/"+name for name in assets},
                "Unexpected checkpoint seed archive inventory")
        for name,proof in sorted(assets.items()):
            require(PurePosixPath(name).name==name and name not in (".",".."), "Unsafe cache asset name")
            item=names["signed-cache/"+name]
            require(not item.is_dir() and not stat.S_ISLNK(item.external_attr >>16)
                    and item.file_size==proof["size"], "Unsafe cache asset entry")
            with zipped.open(item) as content, (cache/name).open("xb") as output:
                shutil.copyfileobj(content,output)
        cache_tools.validate_cache(cache,index)
    return roots,index,cache


def main():
    product,download,receipt=map(Path,sys.argv[1:])
    product=product.resolve(strict=True)
    download=download.resolve(strict=True)
    plan=json.loads(PLAN.read_text())
    pins=json.loads(PINS.read_text())
    hosted_authority(product,plan)
    sys.path.insert(0,str(product/"scripts"))
    import kernel_cache as cache_tools
    spec=spec_from_file_location("native_checkpoint_seed",EXPERIMENT/"native-x86-checkpoint-package-seed.py")
    seed=module_from_spec(spec)
    spec.loader.exec_module(seed)
    plan_hash=cache_tools.file_digest(PLAN)
    require(pins["schema"]==1 and pins["source"]==plan["source"] and pins["tree"]==plan["tree"]
            and pins["planSha256"]==plan_hash and pins["seedRef"]==SEED_REF
            and pins["repositoryId"]==REPO_ID and pins["ownerId"]==OWNER_ID
            and pins["groups"].keys()=={"llvm-native","rust-bootstrap"}
            and pins["groups"].keys()<=plan["groups"].keys()
            and set(child.name for child in download.iterdir())==pins["groups"].keys(),
            "Unexpected reviewed checkpoint seed pins")
    with tempfile.TemporaryDirectory(prefix="assbox-checkpoint-seeds-",dir=download.parent) as temporary:
        scratch=Path(temporary)
        workspace=scratch/"work"
        workspace.mkdir(mode=0o700)
        environment=cache_tools.environment(workspace)
        bound = {
            group: seed.verify_product(cache_tools,product,plan,environment,group)[1]
            for group in pins["groups"]
        }
        forbidden=set()
        for derivation in (plan["bootDerivation"],plan["isoDerivation"]):
            data=cache_tools.decoded(cache_tools.run(environment,"nix","derivation","show",derivation))["derivations"]
            forbidden.update("/nix/store/"+item["path"] for item in data[Path(derivation).name]["outputs"].values())
        for output in forbidden:
            require(not cache_tools.registered(environment,[output]), "Checkpoint ISO or boot proof was already registered")
        staged={}
        shared={}
        for group,pin in sorted(pins["groups"].items()):
            folder=download/group
            require(folder.is_dir() and not folder.is_symlink(),"Unsafe checkpoint seed download folder")
            archive,=folder.iterdir()
            independent=scratch/group
            roots,index,cache=stage(cache_tools,plan,group,archive,independent,pin,
                                    pins["seedRun"],pins["seedWorkflow"],plan_hash,forbidden)
            require(roots==bound[group],"Native checkpoint seed evaluation differs from artifact")
            for path,metadata in index["closure"].items():
                require(path not in shared or shared[path]==metadata, "Conflicting independent seed NAR: "+path)
                shared[path]=metadata
            seed.verify_cold(cache_tools,environment,cache,independent,roots,index)
            staged[group]=(roots,index,cache)

        nix=shutil.which("nix",path=environment["PATH"])
        require(nix and Path(nix).resolve(strict=True).is_relative_to("/nix/store"), "Expected provisioned Nix")
        for group,(roots,index,cache) in staged.items():
            subprocess.run(
                ["/usr/bin/sudo","-n","--",nix,"copy","--offline","--from",cache.as_uri(),"--to","daemon",
                 "--option","trusted-public-keys",index["publicKey"],"--option","require-sigs","true",
                 "--option","substituters","",*roots],
                env=environment,stdin=subprocess.DEVNULL,check=True,timeout=900,
            )
            closure,_=seed.closure_metadata(cache_tools,environment,roots)
            require(closure==index["closure"],"Native daemon NAR differs from validated prerequisite seed: "+group)
        for output in forbidden:
            require(not cache_tools.registered(environment,[output]), "Package cache unexpectedly registered a protected result")
        require(not git(product,"status","--porcelain"), "Product checkout changed during prerequisite import")
    with receipt.open("x") as output:
        json.dump({**pins,"independentSignatureChecksPassed":True,"effectivePackageClosurePaths":len(shared),
                   "isoAndBootNotRegistered":True,"importedAt":datetime.now(timezone.utc).isoformat()},output,indent=2)
        output.write("\n")
    print("Imported",len(staged),"native x86 package caches with",len(shared),"consistent paths",flush=True)


if __name__=="__main__":
    os.umask(0o077)
    main()
