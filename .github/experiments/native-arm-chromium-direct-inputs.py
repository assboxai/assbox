#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Build and sign a scoped set of dependencies from the native Chromium graph."""

from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("arm_chromium_seed", HERE / "native-arm-chromium-seed.py")
seed = importlib.util.module_from_spec(spec)
spec.loader.exec_module(seed)
STORE_PATH = re.compile(r"/nix/store/[0-9a-z]{32}-[A-Za-z0-9.+_?=-]+")


def main():
    source = Path(sys.argv[1]).resolve(strict=True)
    evidence = Path(sys.argv[2]).resolve(strict=True)
    group = sys.argv[3]
    plan_path = HERE / "native-arm-chromium-direct-inputs.json"
    plan = json.loads(plan_path.read_text())
    seed.require(platform.system() == "Linux" and platform.machine() == "aarch64",
                 "Native ARM Linux is required")
    expected_environment = {
        "RUNNER_ENVIRONMENT": "github-hosted",
        "GITHUB_REPOSITORY_ID": "1402455771",
        "GITHUB_REPOSITORY_OWNER_ID": "327835666",
        "GITHUB_REF": "refs/heads/test/arm-chromium-current-libraries",
        "GITHUB_RUN_ATTEMPT": "1",
        "GITHUB_EVENT_NAME": "workflow_dispatch",
    }
    seed.require(all(os.environ.get(key) == value for key, value in expected_environment.items()),
                 "Unexpected hosted producer authority")
    identity = {key: os.environ[key] for key in ("GITHUB_RUN_ID", "GITHUB_SHA", "GITHUB_RUN_ATTEMPT")}
    seed.require(re.fullmatch("[a-f0-9]{40}", identity["GITHUB_SHA"])
                 and re.fullmatch("[1-9][0-9]*", identity["GITHUB_RUN_ID"]),
                 "Invalid hosted producer identity")
    version = subprocess.check_output(
        ["git", "-C", source, "rev-parse", "HEAD", "HEAD^{tree}"], text=True
    ).splitlines()
    seed.require(version == [plan["source"], plan["tree"]] == [seed.SOURCE, seed.TREE]
                 and not subprocess.check_output(["git", "-C", source, "status", "--porcelain"]),
                 "Native dependency source changed")
    sys.path.insert(0, str(source / "scripts"))
    import kernel_cache as tools

    seed.require(tools.file_digest(source / "flake.lock") == seed.LOCK, "Native dependency lock changed")
    rows = plan["groups"][group]
    paths = sorted({p for row in rows for p in row["outputs"].values()})
    derivations = [row["derivation"] for row in rows]
    seed.require(len(derivations) == len(set(derivations))
                 and all(STORE_PATH.fullmatch(path) for path in paths + derivations),
                 "Invalid dependency selector")
    (evidence / "expected.json").write_bytes(tools.encoded({
        "source": plan["source"], "tree": plan["tree"], "group": group, "roots": rows, "identity": identity,
    }))
    with tempfile.TemporaryDirectory(prefix=f"assbox-arm-chromium-{group}-", dir=evidence.parent) as tmp:
        work = Path(tmp)
        env = tools.environment(work)
        env["NIX_CONFIG"] += "max-jobs = 2\ncores = 3\neval-cores = 2\n"
        selector = source.as_uri().replace("file:", "git+file:", 1) + "?rev=" + plan["source"]
        attr = selector + "#nixosConfigurations.aarch64-linux-uefi-none-headless.pkgs.chromium.drvPath"
        wrapper = tools.run(env, "nix", "eval", "--raw", "--no-update-lock-file", "--no-write-lock-file",
                            attr).decode().strip()
        seed.require(wrapper == plan["previousChromium"]["chromiumDrv"], "Native Chromium selector changed")
        references = set(tools.run(env, "nix-store", "--query", "--requisites", wrapper).decode().splitlines())
        seed.require(set(derivations) <= references, "A selected package is outside the Chromium build graph")
        declarations = tools.decoded(tools.run(env, "nix", "derivation", "show", *derivations))["derivations"]
        for row in rows:
            detail = declarations[Path(row["derivation"]).name]
            selected = {name: "/nix/store/" + detail["outputs"][name]["path"]
                        for name in row["outputs"]}
            seed.require(detail["system"] == "aarch64-linux" and selected == row["outputs"],
                         "A native dependency output changed")
        installables = [row["derivation"] + "^" + ",".join(sorted(row["outputs"])) for row in rows]
        with (evidence / "native-build.log").open("xb") as log:
            subprocess.run(["nix", "build", "--no-link", "--max-jobs", "2", "--cores", "3", "-L", *installables],
                           env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, check=True)
        cache = evidence / "signed-cache"
        key_name = "assbox-arm-chromium-" + group + "-" + identity["GITHUB_RUN_ID"]
        index = seed.signed_cache(tools, env, work, cache, paths, key_name, max_paths=4096)
        seed.verify_cold(tools, env, cache, work, paths, index, max_paths=4096)
        index.update({
            "identity": identity, "source": plan["source"], "tree": plan["tree"], "group": group,
            "architecture": "aarch64-linux", "parentChromium": wrapper, "exactRoots": rows,
            "planSha256": tools.file_digest(plan_path),
            "observedAt": datetime.now(timezone.utc).isoformat(),
        })
        (evidence / "index.json").write_bytes(tools.encoded(index))


if __name__ == "__main__":
    main()
