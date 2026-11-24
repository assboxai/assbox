#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Build and sign a scoped set of dependencies from the exact native installed CLI test graph."""

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
    plan_path = HERE / "native-arm-installed-build-prerequisites.json"
    plan = json.loads(plan_path.read_text())
    seed.require(platform.system() == "Linux" and platform.machine() == "aarch64",
                 "Native ARM Linux is required")
    expected_environment = {
        "RUNNER_ENVIRONMENT": "github-hosted",
        "GITHUB_REPOSITORY_ID": "1402455771",
        "GITHUB_REPOSITORY_OWNER_ID": "327835666",
        "GITHUB_REF": "refs/heads/test/arm-installed-lapack-runtime",
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
                 and not subprocess.check_output(["git", "-C", source, "status", "--porcelain"])
                 and subprocess.check_output(["git", "-C", HERE, "rev-parse", "HEAD"],text=True).strip() == identity["GITHUB_SHA"]
                 and not subprocess.check_output(["git", "-C", HERE, "status", "--porcelain"]),
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
    with tempfile.TemporaryDirectory(prefix=f"assbox-arm-installed-build-prerequisites-{group}-", dir=evidence.parent) as tmp:
        work = Path(tmp)
        env = tools.environment(work)
        env["NIX_CONFIG"] += "max-jobs = 1\ncores = 4\neval-cores = 2\n"
        fixture_root = HERE.parent.parent / "tests" / "acceptance" / "installed-headless-cli"
        for name, expected_hash in plan["fixtureFilesSha256"].items():
            seed.require(tools.file_digest(fixture_root / name) == expected_hash, "Installed fixture file changed")
        fixture = fixture_root / "fixture-current.nix"
        expression = (
            f"let fixture = import (builtins.toPath {json.dumps(str(fixture))}) "
            f"{{ source = {json.dumps(str(source))}; revision = {json.dumps(plan['source'])}; "
            'system = "aarch64-linux"; }; in fixture.test.drvPath'
        )
        wrapper = tools.run(
            env, "nix", "eval", "--raw", "--impure", "--no-update-lock-file", "--no-write-lock-file",
            "--expr", expression, timeout=210,
        ).decode().strip()
        seed.require(wrapper == plan["parentProfile"], "Exact native installed CLI test derivation changed")
        references = set(tools.run(env, "nix-store", "--query", "--requisites", wrapper).decode().splitlines())
        seed.require(set(derivations) <= references, "A selected package is outside the exact native installed CLI test graph")
        declarations = tools.decoded(tools.run(env, "nix", "derivation", "show", *derivations))["derivations"]
        for row in rows:
            detail = declarations[Path(row["derivation"]).name]
            selected = {name: "/nix/store/" + detail["outputs"][name]["path"]
                        for name in row["outputs"]}
            seed.require(detail["system"] == "aarch64-linux" and selected == row["outputs"],
                         "A native dependency output changed")
        installables = [row["derivation"] + "^" + ",".join(sorted(row["outputs"])) for row in rows]
        with (evidence / "native-build.log").open("xb") as log:
            subprocess.run(["nix", "build", "--no-link", "--max-jobs", "1", "--cores", "4", "-L", *installables],
                           env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, check=True)
        cache = evidence / "signed-cache"
        key_name = "assbox-arm-installed-build-prerequisites-" + group + "-" + identity["GITHUB_RUN_ID"]
        index = seed.signed_cache(tools, env, work, cache, paths, key_name, max_paths=4096)
        seed.verify_cold(tools, env, cache, work, paths, index, max_paths=4096)
        index.update({
            "identity": identity, "source": plan["source"], "tree": plan["tree"], "group": group,
            "architecture": "aarch64-linux", "parentProfile": wrapper, "exactRoots": rows,
            "planSha256": tools.file_digest(plan_path),
            "observedAt": datetime.now(timezone.utc).isoformat(),
        })
        (evidence / "index.json").write_bytes(tools.encoded(index))

        package, = rows
        output = Path(package["outputs"]["out"])
        declaration = declarations[Path(package["derivation"]).name]
        compiler, = [Path(path) / "bin" / "gfortran"
                     for path in declaration["env"]["nativeBuildInputs"].split()
                     if "-gfortran-wrapper-" in Path(path).name]
        seed.require(compiler.is_file(), "LAPACK's exact Nix Fortran compiler is unavailable")
        program = work / "solve.f90"
        program.write_text("""program assbox_lapack_smoke
  implicit none
  integer :: ipiv(1), info
  double precision :: a(1,1), b(1)
  a(1,1) = 2.0d0
  b(1) = 8.0d0
  call dgesv(1, 1, a, 1, ipiv, b, 1, info)
  if (info /= 0 .or. b(1) /= 4.0d0) stop 1
end program assbox_lapack_smoke
""")
        executable = work / "solve"
        library = output / "lib"
        tools.run(env, str(compiler), str(program), "-L" + str(library),
                  "-Wl,-rpath," + str(library), "-llapack", "-o", str(executable), timeout=60)
        tools.run(env, str(executable), timeout=60)
        (evidence / "native-version.txt").write_text("Native ARM LAPACK 3.12.1 dgesv solved 2x = 8.\n")


if __name__ == "__main__":
    main()
