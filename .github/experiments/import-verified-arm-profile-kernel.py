#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Import the independently verified prerequisite for the native ARM profile inventory."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import time
from tempfile import TemporaryDirectory
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

TAG = "kernel-formatter-45038354435-1-dev"
RELEASE_ID = 454755949
RELEASE_CORE = "e8a5b87432b76dc85c4fc20a988c13a726bf762a"
RELEASE_SHA = "88bd98a9babebf5c9f38dd3b6541349782103b956c954a81e82779651b6844e9"
INDEX_SHA = 'a01c3b0cbe6d5734cd5a3b2d82aa9708baf3ee6eea2384746f62873f9c5998c7'
INDEX_SIZE = 51416
SYSTEM = "aarch64-linux"
KERNEL_DERIVATION = '/nix/store/iy9lmhqpi2qmllvaq3dw5jdgn80qak4a-linux-6.18.55.drv'


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def fetch(asset, target, size, digest):
    if not re.fullmatch(r"kernel-aarch64-linux(?:\.json|-[a-z0-9.\-]+)", asset):
        raise ValueError("Unknown ARM kernel experiment asset")
    if not 0 < size <= 2 * 1024**3:
        raise ValueError("Unbounded ARM kernel experiment asset")
    url = f"https://github.com/assboxai/assbox/releases/download/{TAG}/{asset}"
    opener = build_opener(NoRedirect())
    headers = {"User-Agent": "assbox-native-ARM-test-kernel"}
    for attempt in range(3):
        partial = target.with_suffix(target.suffix + ".partial")
        try:
            try:
                opener.open(Request(url, headers=headers), timeout=60).close()
            except HTTPError as response:
                if response.code not in (301, 302, 303, 307, 308):
                    raise
                redirected = response.headers.get("Location", "")
                response.close()
            else:
                raise ValueError("Expected an immutable GitHub release asset redirect")
            destination = urlsplit(redirected)
            if (destination.scheme != "https" or destination.hostname != "release-assets.githubusercontent.com"
                    or destination.username or destination.password or destination.port not in (None, 443)
                    or destination.fragment):
                raise ValueError("Unexpected ARM kernel experiment asset host")
            total = 0
            hashed = sha256()
            deadline = time.monotonic() + 600
            with opener.open(Request(redirected, headers=headers), timeout=90) as incoming, partial.open("xb") as output:
                while chunk := incoming.read(1024 * 1024):
                    total += len(chunk)
                    if total > size or time.monotonic() > deadline:
                        raise ValueError("ARM kernel experiment asset exceeded its size or time limit")
                    hashed.update(chunk)
                    output.write(chunk)
        except (HTTPError, URLError, TimeoutError) as failure:
            partial.unlink(missing_ok=True)
            if attempt == 2 or (isinstance(failure, HTTPError) and failure.code not in (408, 429, 500, 502, 503, 504)):
                raise RuntimeError(f"ARM kernel experiment asset fetch failed for {asset}: {type(failure).__name__}") from None
            time.sleep(2 ** attempt)
        else:
            if total != size or hashed.hexdigest() != digest:
                raise ValueError(f"Incorrect ARM kernel experiment asset digest for {asset}")
            partial.rename(target)
            return


def require(predicate, description):
    if not predicate:
        raise ValueError(description)


def recording(program, evidence):
    specification = {
        "RUNNER_ENVIRONMENT": "github-hosted",
        "GITHUB_REPOSITORY": "assboxai/assbox",
        "GITHUB_REPOSITORY_ID": "1402455771",
        "GITHUB_REPOSITORY_OWNER_ID": "327835666",
        "GITHUB_EVENT_NAME": "workflow_dispatch",
        "GITHUB_RUN_ATTEMPT": "1",
        "GITHUB_REF": "refs/heads/test/arm-current-profile-signed-archive-retry",
    }
    if (platform.system() != "Linux" or platform.machine() != "aarch64"
            or any(os.environ.get(name) != value for name, value in specification.items())):
        raise ValueError("Unexpected native ARM installed fixture authority")
    if any(name in os.environ for name in ("GH_TOKEN", "GITHUB_TOKEN", "ACTIONS_RUNTIME_TOKEN",
                                           "ACTIONS_ID_TOKEN_REQUEST_TOKEN", "ACTIONS_ID_TOKEN_REQUEST_URL")):
        raise ValueError("Unexpected ARM kernel import credentials")
    authority = Path(__file__).resolve().parent
    plan = json.loads((authority / "current-arm-independent-profile-plan.json").read_bytes())
    selected = plan["groups"][os.environ["INPUT_GROUP"]]
    realized_selection = json.loads((evidence / "evaluation.json").read_bytes())
    require(realized_selection == selected, "Unexpected exact native profile selection")
    git = lambda *args: subprocess.check_output(["git", "--no-replace-objects", "-C", program, *args], text=True)
    require(git("rev-parse", "HEAD", "HEAD^{tree}").splitlines() == [plan["source"], plan["tree"]]
            and not git("status", "--porcelain"), "Unexpected native product source")
    sys.path.insert(0, str(program / "scripts"))
    import kernel_cache as cache_tools

    authority = Path(__file__).resolve().parent
    authority_git = lambda *args: subprocess.check_output(["git", "--no-replace-objects", "-C", authority, *args], text=True)
    require(authority_git("rev-parse", "HEAD").strip() == os.environ["GITHUB_SHA"]
            and not authority_git("status", "--porcelain"), "Unexpected ARM kernel experiment checkout")
    require(cache_tools.file_digest(program / "flake.lock") == plan["lockSha256"], "Unexpected installed fixture lock")
    with TemporaryDirectory(prefix="assbox-native-ARM-profile-kernel-", dir=evidence.parent) as temporary:
        work = Path(temporary)
        env = cache_tools.environment(work)
        index_path = work / "kernel-aarch64-linux.json"
        fetch(index_path.name, index_path, INDEX_SIZE, INDEX_SHA)
        expected = cache_tools.kernel_identity(env, program, SYSTEM)
        formatter = cache_tools.formatter_identity(env, program, SYSTEM)
        require(expected["derivation"] == KERNEL_DERIVATION, "Unexpected ARM kernel derivation")
        for row in selected.values():
            graph = set(cache_tools.run(env, "nix-store", "--query", "--requisites", row["derivation"],
                                        timeout=300).decode().splitlines())
            require((KERNEL_DERIVATION in graph) == row["usesVerifiedKernel"],
                    "The kernel binding in the exact native profile changed")
        raw = cache_tools.bounded(index_path, cache_tools.MAX_INDEX)
        index = cache_tools.validate_index(raw, release_sha=RELEASE_SHA, core=RELEASE_CORE, lock_sha=plan["lockSha256"],
                                           system=SYSTEM, expected=expected, expected_formatter=formatter)
        cache = work / "signed-cache"
        cache.mkdir(mode=0o700)
        with ThreadPoolExecutor(max_workers=6) as workers:
            futures = [workers.submit(fetch, cache_tools.prefix(SYSTEM) + name, cache / name, item["size"], item["sha256"])
                       for name, item in index["cacheAssets"].items()]
            for future in futures:
                future.result()
        cache_tools.validate_cache(cache, index)
        roots = list(expected["outputs"].values()) + [formatter["output"]]
        nix = shutil.which("nix", path=env["PATH"])
        require(nix is not None and Path(nix).resolve(strict=True).is_relative_to("/nix/store"),
                "Expected the provisioned Nix CLI")
        subprocess.run(["/usr/bin/sudo", "-n", "--", nix, "copy", "--offline", "--from", cache.as_uri(),
                        "--to", "daemon", "--option", "trusted-public-keys", index["publicKey"],
                        "--option", "require-sigs", "true", "--option", "substituters", "", *roots],
                       env=env, stdin=subprocess.DEVNULL, check=True, timeout=900)
        actual = cache_tools.decoded(cache_tools.run(env, "nix", "path-info", "--offline", "--recursive",
                                                   "--json", "--json-format", "1", *roots, timeout=150))
        require(set(actual) == set(index["closure"]) and all(
            {field: actual[path][field] for field in ("narHash", "narSize", "references")} == proof
            for path, proof in index["closure"].items()), "ARM kernel registration differs from the verified manifest")
        configuration = Path(expected["outputs"]["dev"]) / "lib/modules" / index["kernelVersion"] / "build/.config"
        raw_configuration = cache_tools.bounded(configuration, 4 * cache_tools.MAX_INDEX, store_file=True)
        require(sha256(raw_configuration).hexdigest() == index["configSha256"]
                and b"# CONFIG_RFKILL_INPUT is not set\n" in raw_configuration
                and b"CONFIG_RFKILL_INPUT=y\n" not in raw_configuration, "ARM kernel radio configuration differs")
        require(not git("status", "--porcelain"), "The ARM kernel import changed product source")
        with (evidence / "kernel-import.json").open("x") as result:
            json.dump({"observedAt": datetime.now(timezone.utc).isoformat(), "source": plan["source"],
                       "tree": plan["tree"], "system": SYSTEM, "groups": list(selected), "releaseId": RELEASE_ID,
                       "releaseTag": TAG, "indexSha256": INDEX_SHA, "derivation": KERNEL_DERIVATION,
                       "outputs": roots, "closurePaths": len(actual), "configSha256": index["configSha256"],
                       "kernelBuildInvoked": False}, result, indent=2)
            result.write("\n")


if __name__ == "__main__":
    os.umask(0o077)
    product, evidence = map(Path, sys.argv[1:])
    recording(product.resolve(strict=True), evidence.resolve(strict=True))
