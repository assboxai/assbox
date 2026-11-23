#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Build the reviewed x86 checkpoint prerequisite shard and verify its signed cache."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
import tempfile
from urllib.parse import urlencode

FIELDS = ("narHash", "narSize", "references")
MAX_BYTES = 2 * 1024**3
REF = "refs/heads/test/checkpoint-x86-runtime-seeds-v2"
FLAGS = ("--no-update-lock-file", "--no-write-lock-file")
PLAN = Path(__file__).with_name("checkpoint-package-seed-plan.json")


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
    return result, {path: row.get('ca') for path, row in observed.items()}


def normalize_signed_metadata(cache_tools, cache, content_addresses):
    cache_tools.normalize_export(cache)
    for info in sorted(cache.glob('*.narinfo')):
        lines = cache_tools.bounded(info, 256 * 1024).decode().splitlines(keepends=True)
        paths = [line.removeprefix('StorePath: ').rstrip('\n') for line in lines if line.startswith('StorePath: ')]
        require(len(paths) == 1 and paths[0] in content_addresses, 'Unknown producer NAR store path')
        expected = content_addresses[paths[0]]
        fields = [line for line in lines if line.startswith('CA:')]
        if expected is None:
            require(not fields, 'Unexpected NAR content address')
            continue
        require(fields == [f'CA: {expected}\n'], 'NAR content address differs from the native store')
        # Require the scoped signer even on content-addressed paths. Nix signatures bind store
        # path, NAR hash and size, and references. Removing this field preserves that signature.
        info.write_text(''.join(line for line in lines if not line.startswith('CA:')))


def signed_cache(cache_tools, env, workspace, cache, paths, name):
    closure, content_addresses = closure_metadata(cache_tools, env, paths)
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
    normalize_signed_metadata(cache_tools, cache, content_addresses)
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
            closure, _ = closure_metadata(cache_tools, env, paths, store=store)
            require(closure == index['closure'], 'Cold store closure differs from the signed content')


def verify_product(cache_tools, source, plan, environment, group):
    repo = subprocess.check_output(
        ["git", "-C", source, "rev-parse", "HEAD", "HEAD^{tree}"], text=True,
    ).splitlines()
    require(repo == [plan["source"], plan["tree"]], "Unexpected checkpoint product identity")
    require(not subprocess.check_output(["git", "-C", source, "status", "--porcelain"]),
            "Dirty checkpoint product checkout")
    require(cache_tools.file_digest(source / "flake.lock") == plan["lockSha256"],
            "Checkpoint lockfile digest mismatch")
    selector = source.as_uri().replace("file:", "git+file:", 1) + "?rev=" + plan["source"]
    for attribute, key in (("checks.x86_64-linux.physical-checkpoint-boot", "bootDerivation"),
                           ("packages.x86_64-linux.physical-checkpoint-iso", "isoDerivation")):
        actual = cache_tools.run(environment, "nix", "eval", *FLAGS, "--raw",
                                 selector + "#" + attribute + ".drvPath").decode().strip()
        require(actual == plan[key], "Checkpoint candidate graph changed: " + attribute)
    graph = set(cache_tools.run(environment, "nix-store", "--query", "--requisites",
                                plan["bootDerivation"]).decode().splitlines())
    require(plan["isoDerivation"] in graph, "Native boot no longer uses the selected ISO")
    expected = plan["groups"][group]
    descriptions = cache_tools.decoded(cache_tools.run(
        environment, "nix", "derivation", "show", *[row["derivation"] for row in expected],
    ))["derivations"]
    targets = []
    paths = set()
    for row in expected:
        drv = row["derivation"]
        require(drv in graph and drv not in (plan["bootDerivation"], plan["isoDerivation"]),
                "Invalid or unrelated checkpoint seed derivation")
        require(drv.startswith("/nix/store/") and drv.endswith(".drv"), "Malformed seed derivation")
        observed = descriptions[Path(drv).name]
        require(observed["system"] == "x86_64-linux", "Non-native package in x86 checkpoint seed")
        outputs = row["outputs"]
        for label, path in outputs.items():
            require(path == "/nix/store/" + observed["outputs"][label]["path"],
                    "Checkpoint seed output mismatch: " + label)
        targets.append(drv + "^" + ",".join(sorted(outputs)))
        paths.update(outputs.values())
    require(len(paths) == sum(len(row["outputs"]) for row in expected), "Duplicate seed outputs")
    for drv in (plan["bootDerivation"], plan["isoDerivation"]):
        value = cache_tools.decoded(cache_tools.run(environment, "nix", "derivation", "show", drv))
        generated = value["derivations"][Path(drv).name]["outputs"]
        require(not any("/nix/store/" + item["path"] in paths for item in generated.values()),
                "Candidate boot output or test result entered the package seed")
    return targets, sorted(paths)


def main():
    source = Path(sys.argv[1]).resolve(strict=True)
    evidence = Path(sys.argv[2]).resolve(strict=True)
    group = sys.argv[3]
    plan = json.loads(PLAN.read_text())
    require(group in plan["groups"] and plan["architecture"] == "x86_64-linux",
            "Unknown checkpoint package seed group")
    require(platform.machine() == "x86_64" and platform.system() == "Linux", "Native x86 Linux required")
    authority = {
        "RUNNER_ENVIRONMENT": "github-hosted", "GITHUB_RUN_ATTEMPT": "1",
        "GITHUB_REPOSITORY": "assboxai/assbox", "GITHUB_REPOSITORY_ID": "1402455771",
        "GITHUB_REPOSITORY_OWNER_ID": "327835666", "GITHUB_REF": REF,
        "GITHUB_EVENT_NAME": "workflow_dispatch",
    }
    require(all(os.environ.get(name) == expected for name, expected in authority.items()),
            "Unexpected checkpoint seed authority")
    workflow, run = os.environ["GITHUB_SHA"], os.environ["GITHUB_RUN_ID"]
    require(re.fullmatch("[a-f0-9]{40}", workflow) and re.fullmatch("[1-9][0-9]*", run),
            "Invalid checkpoint seed workflow identity")
    sys.path.insert(0, str(source / "scripts"))
    import kernel_cache as cache_tools
    with tempfile.TemporaryDirectory(prefix="assbox-checkpoint-seed-", dir=evidence.parent) as temporary:
        workspace = Path(temporary)
        environment = cache_tools.environment(workspace)
        environment["NIX_CONFIG"] += "max-jobs = 1\ncores = 4\neval-cores = 2\n"
        targets, paths = verify_product(cache_tools, source, plan, environment, group)
        (evidence / "expected.json").write_text(json.dumps(
            {"group": group, "targets": targets, "paths": paths, "source": plan["source"]}, indent=2) + "\n")
        with (evidence / "native-build.log").open("xb") as output:
            subprocess.run(["nix", "build", *FLAGS, "--no-link", "--max-jobs", "1", "--cores", "4",
                            "-L", *targets], env=environment, cwd=source, stdin=subprocess.DEVNULL,
                           stdout=output, stderr=subprocess.STDOUT, check=True, timeout=19200)
        if group == "sqlite":
            sqlite, = [Path(path) / "bin/sqlite3" for path in paths if path.endswith("-bin")]
            version = subprocess.check_output([sqlite, "--version"], env=environment, text=True, timeout=20)
            require(version.startswith("3.54.1 "), "Unexpected SQLite output version")
        cache = evidence / "signed-cache"
        signer = "assbox-x86-checkpoint-" + group + "-" + run
        index = signed_cache(cache_tools, environment, workspace, cache, paths, signer)
        verify_cold(cache_tools, environment, cache, workspace, paths, index)
        index.update(schema=1, kind="assbox-native-x86-checkpoint-package-seed", group=group,
                     source=plan["source"], tree=plan["tree"], lockSha256=plan["lockSha256"],
                     planSha256=cache_tools.file_digest(PLAN), architecture=plan["architecture"],
                     repository="assboxai/assbox", repositoryId=1402455771, ownerId=327835666,
                     workflow=workflow, runId=int(run), runAttempt=1, ref=REF,
                     bootDerivation=plan["bootDerivation"], isoDerivation=plan["isoDerivation"],
                     roots=paths, packages=plan["groups"][group],
                     wrongKeyRefused=True, correctKeyColdImportPassed=True,
                     observedAt=datetime.now(timezone.utc).isoformat())
        (evidence / "index.json").write_text(json.dumps(index, indent=2) + "\n")
        print("Verified native x86 checkpoint seed", group, len(index["closure"]), flush=True)


if __name__ == "__main__":
    main()
