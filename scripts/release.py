#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Release orchestration for the protected master workflow, never installed on clients.

Read-only builders resolve and test dependencies. The privileged publisher only
inspects bytes with this frozen source and calls GitHub; it never evaluates Nix,
executes a downloaded candidate or consumes a long-lived credential.
"""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
import tomllib
import urllib.error
import urllib.request
import release_data as data

ROOT = Path(__file__).resolve().parents[1]
REPO = "assboxai/assbox"
API_TOKEN: str | None = None
ASSETS = ("release.json", "release.sigstore.json", "flake.lock", "assbox-source.tar.gz")


def child_environment(*, github_upload: bool = False) -> dict[str, str]:
    # Never give candidate Nix/build processes CI API, runtime-artifact or OIDC
    # credentials. The trusted Python process holds the optional read/write token.
    blocked = {"GH_TOKEN", "GITHUB_TOKEN", "GH_ENTERPRISE_TOKEN", "GITHUB_ENTERPRISE_TOKEN",
               "ACTIONS_RUNTIME_TOKEN", "ACTIONS_ID_TOKEN_REQUEST_TOKEN",
               "ACTIONS_ID_TOKEN_REQUEST_URL"}
    env = {key: value for key, value in os.environ.items() if key not in blocked}
    if github_upload:
        if not API_TOKEN:
            raise ValueError("GitHub upload requires this job's ephemeral token")
        env["GH_TOKEN"] = API_TOKEN
    return env


def run(*args: str, cwd: Path | None = None, input_bytes: bytes | None = None,
        github_upload: bool = False) -> bytes:
    if github_upload and args[:3] != ("gh", "release", "upload"):
        raise ValueError("only the fixed asset-upload command may inherit a GitHub token")
    return subprocess.run(args, cwd=cwd, input=input_bytes, stdout=subprocess.PIPE,
                          env=child_environment(github_upload=github_upload),
                          check=True, timeout=21600).stdout


def bounded_bytes(path: Path, limit: int) -> bytes:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > limit:
        raise ValueError(f"not a bounded regular input file: {path}")
    with path.open("rb") as file:
        value = file.read(limit + 1)
    if len(value) > limit:
        raise ValueError("input grew beyond its size limit")
    return value


def load(path: Path):
    return data.decode(bounded_bytes(path, 16 * 1024 * 1024))


def write(path: Path, value: object) -> None:
    path.write_bytes(data.json_bytes(value))


def core_tree(*, require_lock: bool = True) -> tuple[str, dict]:
    sha = run("git", "rev-parse", "HEAD", cwd=ROOT).decode().strip()
    if not re.fullmatch(r"[0-9a-f]{40}", sha) or sha != os.environ.get("GITHUB_SHA"):
        raise ValueError("workflow source identity mismatch")
    if os.environ.get("GITHUB_REPOSITORY") != REPO or os.environ.get("GITHUB_REF") != "refs/heads/master":
        raise ValueError("release operations require the official master workflow")
    if os.environ.get("GITHUB_EVENT_NAME") not in {"schedule", "workflow_dispatch"}:
        raise ValueError("release operations cannot run in a pull request, push or workflow_run context")
    files = {}
    for entry in run("git", "ls-tree", "-rz", "HEAD", cwd=ROOT).split(b"\0"):
        if not entry:
            continue
        metadata, raw_name = entry.split(b"\t", 1)
        mode, kind, blob = metadata.decode().split()
        if mode not in {"100644", "100755"} or kind != "blob":
            raise ValueError("source links/submodules are not release inputs")
        name = raw_name.decode("utf-8")
        if any(ord(char) < 32 for char in name):
            raise ValueError("control character in tracked source path")
        files[name] = (int(mode, 8) & 0o777, run("git", "cat-file", "blob", blob, cwd=ROOT))
    if (require_lock and "flake.lock" not in files) or "release-context.json" in files:
        raise ValueError("commit a genuine bootstrap lock; keep release context out of master")
    return sha, files


def policy() -> dict:
    p = load(ROOT / "release/policy.json")
    for key in ("repositoryId", "ownerId"):
        if type(p.get(key)) is not int or p[key] <= 0:
            raise ValueError("cold-administrator bootstrap must provision actual repository and owner IDs")
    if p["repository"] != REPO or p["sourceRef"] != "refs/heads/master" or p["workflow"] != ".github/workflows/release.yml":
        raise ValueError("unsupported release identity policy")
    if p.get("channel") != "stable":
        raise ValueError("only the authenticated stable channel is supported")
    if p["maximumLifetimeSeconds"] != 604800 or p["refreshAfterSeconds"] != 259200:
        raise ValueError("lifetime policy requires coordinated Rust/CI review")
    return p


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("GitHub API redirect refused; revalidate repository ownership")


def api(path: str, payload: object | None = None, token: bool = False, method: str | None = None):
    if path != f"/repos/{REPO}" and not path.startswith(f"/repos/{REPO}/"):
        raise ValueError("unexpected API repository")
    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2026-03-10",
               "User-Agent": "Assbox-release-workflow"}
    if token and not API_TOKEN:
        raise ValueError("this API operation requires the job's ephemeral GitHub token")
    if API_TOKEN:
        headers["Authorization"] = "Bearer " + API_TOKEN
    body = None if payload is None else data.json_bytes(payload)
    req = urllib.request.Request("https://api.github.com" + path, data=body, headers=headers, method=method)
    with urllib.request.build_opener(NoRedirect).open(req, timeout=60) as response:
        raw = response.read(4 * 1024 * 1024 + 1)
        if len(raw) > 4 * 1024 * 1024:
            raise ValueError("API response exceeds bound")
        return data.decode(raw) if raw else None


def check_repository(*, privileged: bool = False) -> None:
    p = policy()
    repo = api(f"/repos/{REPO}", token=privileged)
    if (repo["id"] != p["repositoryId"] or repo["owner"]["id"] != p["ownerId"]
            or repo["default_branch"] != "master" or repo["private"] or repo["fork"]):
        raise ValueError("repository identity/default branch/visibility changed")
    current = api(f"/repos/{REPO}/git/ref/heads/master", token=privileged)
    if current["object"]["sha"] != os.environ["GITHUB_SHA"]:
        raise ValueError("master moved or this is an old rerun; do not resolve/publish stale core")


def materialize(files: dict, path: Path) -> None:
    path.mkdir(parents=True, exist_ok=False)
    for name, (mode, content) in files.items():
        target = path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        target.chmod(mode)


def context(sha: str, files: dict, lock_bytes: bytes) -> dict:
    version = tomllib.loads(files["Cargo.toml"][1].decode())["workspace"]["package"]["version"]
    return {"coreCommit": sha, "coreVersion": version, "lockSha256": data.digest(lock_bytes)}


def resolved_lock(tree: Path) -> dict:
    return data.decode(run("nix", "flake", "metadata", "--json", "--no-use-registries",
                           "--no-update-lock-file", "--no-write-lock-file",
                           str(tree.resolve())))["locks"]


def normalized_lock(core: dict, selected: dict) -> bytes:
    # The composer deliberately isolates application subtrees. Nix assigns its
    # own node names; authenticate that exact graph, after checking every pin.
    with tempfile.TemporaryDirectory(prefix="assbox-lock-") as temp:
        tree = Path(temp) / "source"
        materialize({**core, "flake.lock": (0o644, data.json_bytes(selected))}, tree)
        resolved = resolved_lock(tree)
    data.require_same_inputs(selected, resolved)
    return data.json_bytes(resolved)


def check_lock(tree: Path) -> None:
    committed = load(tree / "flake.lock")
    data.validate_lock(committed)
    if committed != resolved_lock(tree):
        raise ValueError("resolved graph differs from the source lock; normalize before authenticating it")
    print("Resolved source lock matches exactly.")


def output(name: str, value: str) -> None:
    if "\n" in value or "\r" in value:
        raise ValueError("unsafe workflow output")
    with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as file:
        file.write(f"{name}={value}\n")


def inventory() -> tuple[dict | None, str | None]:
    def pages(endpoint: str) -> list[dict]:
        result = []
        for page in range(1, 1001):
            values = api(f"/repos/{REPO}/{endpoint}?per_page=100&page={page}")
            if not isinstance(values, list) or len(values) > 100 or any(not isinstance(v, dict) for v in values):
                raise ValueError("invalid paginated GitHub inventory")
            result.extend(values)
            if len(values) < 100:
                return result
        raise ValueError("release history exceeds its inventory bound; do not truncate history")
    return data.history_head(pages("releases"), pages("tags"))


def public_manifest(tag: str) -> bytes:
    data.release_sequence(tag)
    url = f"https://github.com/{REPO}/releases/download/{tag}/release.json"
    # Public asset downloads deliberately carry no API token, including redirects
    # to GitHub's asset CDN. These bytes have authority only after digest checks.
    class HttpsOnly(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            if not newurl.startswith("https://"):
                raise ValueError("non-HTTPS release asset redirect")
            return super().redirect_request(req, fp, code, msg, headers, newurl)
    req = urllib.request.Request(url, headers={"User-Agent": "Assbox-release-workflow"})
    with urllib.request.build_opener(HttpsOnly).open(req, timeout=60) as response:
        raw = response.read(65537)
    if len(raw) > 65536:
        raise ValueError("release manifest exceeds bound")
    value = data.decode(raw)
    data.validate_manifest(value)
    if data.json_bytes(value) != raw or value["tag"] != tag:
        raise ValueError("noncanonical predecessor manifest/tag")
    return raw


def check_parent_head(manifest: dict) -> None:
    """Last check before tag creation; serialization is enforced by workflow concurrency.

    The parent's exact digest was authenticated in read-only preparation. A mutable
    latest pointer has no role. Stale reruns, orphan tags and detached history fail.
    """
    head, prior_tag = inventory()
    if head is None:
        data.require_parent(manifest, None, None)
        return
    if manifest["previousTag"] != head["tag_name"]:
        raise ValueError("authenticated release head advanced; discard this stale candidate")
    raw = public_manifest(head["tag_name"])
    parent = data.decode(raw)
    if parent["previousTag"] != prior_tag:
        raise ValueError("head lineage does not match the complete visible release history")
    data.require_parent(manifest, parent, raw)


def discover(out: Path) -> None:
    # Runs in a dedicated API-only step. Its process exits before Nix runs, so
    # the token is not available through a live parent process either.
    sha, _ = core_tree()
    check_repository()
    head, prior = inventory()
    write(out, {"schema": 1, "coreCommit": sha, "head": head, "previousTag": prior})


def prepare(out: Path, discovery: Path) -> None:
    if API_TOKEN or any(os.environ.get(key) for key in ("GH_TOKEN", "GITHUB_TOKEN", "ACTIONS_ID_TOKEN_REQUEST_TOKEN")):
        raise ValueError("release resolution must run in a tokenless step after discovery exits")
    sha, files = core_tree()
    observed = load(discovery)
    if (set(observed) != {"schema", "coreCommit", "head", "previousTag"}
            or observed["schema"] != 1 or observed["coreCommit"] != sha):
        raise ValueError("discovery does not belong to this frozen source")
    head, prior_tag = observed["head"], observed["previousTag"]
    if head is None:
        if prior_tag is not None:
            raise ValueError("empty history cannot have a predecessor")
    elif not isinstance(head, dict) or head.get("immutable") is not True or head.get("draft") is not False or head.get("prerelease") is not False:
        raise ValueError("discovery head is not an immutable public release")
    if prior_tag is not None:
        data.release_sequence(prior_tag)
    out.mkdir(parents=True, exist_ok=False)
    previous = None
    baseline = data.decode(files["flake.lock"][1])
    if head is not None:
        tag = head["tag_name"]
        data.release_sequence(tag)
        # Authenticate the highest discovered release, even if expired. Never
        # fall back to an older release when this verification fails.
        binary = run("nix", "build", "--no-link", "--print-out-paths", "--no-update-lock-file",
                     "--no-write-lock-file", ".#assbox", cwd=ROOT).decode().strip() + "/bin/assbox"
        if not re.fullmatch(r"/nix/store/[A-Za-z0-9.+_-]+/bin/assbox", binary):
            raise ValueError("invalid verifier output")
        location = "/var/lib/assbox-release-baseline-" + os.environ["GITHUB_RUN_ID"] + "-" + os.environ["GITHUB_RUN_ATTEMPT"]
        run("sudo", binary, "internal", "release-baseline", tag, location)
        previous_bytes = run("sudo", "cat", location + "/release.json")
        previous = data.decode(previous_bytes)
        data.validate_manifest(previous)
        if (data.json_bytes(previous) != previous_bytes or previous["tag"] != tag
                or previous["previousTag"] != prior_tag):
            raise ValueError("authenticated head does not extend visible history canonically")
        baseline_bytes = run("sudo", "cat", location + "/flake.lock")
        if data.digest(baseline_bytes) != previous["lockSha256"]:
            raise ValueError("historical dependency graph changed after authentication")
        baseline = data.decode(baseline_bytes)
    data.validate_lock(baseline)
    with tempfile.TemporaryDirectory(prefix="assbox-resolve-") as temp:
        tree = Path(temp) / "source"
        materialize(files, tree)
        write(tree / "flake.lock", baseline)
        run("nix", "flake", "update", "--flake", str(tree), *data.INPUTS)
        latest_lock = load(tree / "flake.lock")
    data.validate_lock(latest_lock)
    plan = {"coreCommit": sha, "previous": previous, "baseline": baseline, "latest": latest_lock}
    write(out / "plan.json", plan)


def application_probe(plan_path: Path, application: str, system: str, report: Path) -> None:
    sha, core = core_tree()
    plan_bytes = bounded_bytes(plan_path, 16 * 1024 * 1024)
    plan = data.decode(plan_bytes)
    if plan["coreCommit"] != sha or application not in data.APPLICATIONS or system not in data.SYSTEMS:
        raise ValueError("probe identity mismatch")
    native = run("nix", "eval", "--impure", "--raw", "--expr", "builtins.currentSystem").decode()
    if native != system:
        raise ValueError("cross-architecture reports do not count as native acceptance")
    lock_bytes = normalized_lock(core, data.compose_lock(plan["baseline"], plan["latest"], {"nixpkgs", application + "-packages"}))
    with tempfile.TemporaryDirectory(prefix="assbox-app-probe-") as temp:
        tree = Path(temp) / "source"
        materialize(data.source_files(core, lock_bytes, context(sha, core, lock_bytes)), tree)
        # Missing application VMs are failures, never a green placeholder. Final
        # release gates re-test retained pins and reject vulnerable held closures.
        target = f"path:{tree}#checks.{system}.application-{application}-vm"
        process = subprocess.run(["nix", "build", "--no-link", "--no-update-lock-file", "--no-write-lock-file", target],
                                 timeout=20000, check=False, env=child_environment())
    report.parent.mkdir(parents=True, exist_ok=True)
    write(report, {"application": application, "system": system, "planSha256": data.digest(plan_bytes),
                   "passed": process.returncode == 0, "exitCode": process.returncode})


def finalize(plan_path: Path, reports: Path, out: Path) -> None:
    sha, core = core_tree()
    plan_bytes = bounded_bytes(plan_path, 16 * 1024 * 1024)
    plan = data.decode(plan_bytes)
    if plan["coreCommit"] != sha:
        raise ValueError("candidate was resolved from a different core")
    advanced = data.select_inputs([load(p) for p in sorted(reports.rglob("probe-*.json"))], data.digest(plan_bytes))
    lock_bytes = normalized_lock(core, data.compose_lock(plan["baseline"], plan["latest"], advanced))
    ctx = context(sha, core, lock_bytes)
    files = data.source_files(core, lock_bytes, ctx)
    archive = data.pack_source(files)
    with tempfile.TemporaryDirectory(prefix="assbox-final-") as temp:
        tree = Path(temp) / "source"
        materialize(files, tree)
        nar = run("nix", "hash", "path", str(tree)).decode().strip()
    manifest = data.make_manifest(sha, ctx["coreVersion"], int(time.time()), plan["previous"], data.digest(archive),
                                  nar, data.digest(lock_bytes), sorted(set(data.INPUTS) - advanced))
    publish = data.needs_release(plan["previous"], manifest, int(time.time()))
    out.mkdir(parents=True, exist_ok=False)
    write(out / "release.json", manifest)
    (out / "flake.lock").write_bytes(lock_bytes)
    (out / "assbox-source.tar.gz").write_bytes(archive)
    output("publish", "true" if publish else "false")
    output("tag", manifest["tag"])


def validate_final(assets: Path) -> tuple[dict, dict]:
    sha, core = core_tree()
    manifest = load(assets / "release.json")
    lock_bytes = bounded_bytes(assets / "flake.lock", 8 * 1024 * 1024)
    archive = bounded_bytes(assets / "assbox-source.tar.gz", 64 * 1024 * 1024)
    if (manifest["coreCommit"] != sha or manifest["sourceSha256"] != data.digest(archive)
            or manifest["lockSha256"] != data.digest(lock_bytes)):
        raise ValueError("release manifest/artifact identity mismatch")
    ctx = context(sha, core, lock_bytes)
    if manifest["coreVersion"] != ctx["coreVersion"] or manifest["systems"] != list(data.SYSTEMS):
        raise ValueError("release version/architecture mismatch")
    data.validate_manifest(manifest)
    if data.json_bytes(manifest) != bounded_bytes(assets / "release.json", 65536):
        raise ValueError("manifest is not canonical JSON")
    if manifest["issuedAt"] > int(time.time()) + 300 or manifest["expiresAt"] <= int(time.time()):
        raise ValueError("expired or future-dated release metadata")
    return manifest, data.validate_source(archive, core, lock_bytes, ctx)


def native_gate(assets: Path, system: str, report: Path) -> None:
    manifest, files = validate_final(assets)
    native = run("nix", "eval", "--impure", "--raw", "--expr", "builtins.currentSystem").decode()
    if system not in data.SYSTEMS or native != system:
        raise ValueError("native release runner architecture mismatch")
    with tempfile.TemporaryDirectory(prefix="assbox-acceptance-") as temp:
        tree = Path(temp) / "source"
        materialize(files, tree)
        if run("nix", "hash", "path", str(tree)).decode().strip() != manifest["sourceNarHash"]:
            raise ValueError("candidate NAR differs from the manifest")
        run("bash", str(ROOT / "scripts/release-check"), "--candidate", str(tree))
        for name, (mode, content) in files.items():
            path = tree / name
            if path.is_symlink() or bounded_bytes(path, 16 * 1024 * 1024) != content or path.stat().st_mode & 0o777 != mode:
                raise ValueError("verification modified a release source file")
    report.parent.mkdir(parents=True, exist_ok=True)
    write(report, {"system": system, "manifestSha256": data.digest((assets / "release.json").read_bytes()), "passed": True})


def store_path(raw: bytes) -> str:
    """Accept exactly one top-level store object, never a flake URL or subpath."""
    text = raw.decode("utf-8").removesuffix("\n")
    if not re.fullmatch(r"/nix/store/[0-9a-df-np-sv-z]{32}-[A-Za-z0-9.+_-]+", text):
        raise ValueError("expected one immutable Nix store path")
    return text


def live_verify(tag: str, system: str, directory: Path) -> None:
    """Test both the bootstrap verifier and the verifier carried by this release.

    The candidate is built ONLY from the bootstrap-authenticated store tree, with
    its own release lock. A fresh verification/download directory for stage two
    prevents reusing stage one's evidence in place of exercising the new tools.
    This is read-only with respect to GitHub; it does not advertise a release.
    """
    if API_TOKEN is not None:
        raise ValueError("public live verification must not hold a GitHub token")
    data.release_sequence(tag)
    if (system not in data.SYSTEMS or directory.parent != Path("/var/lib")
            or not re.fullmatch(r"assbox-public-[A-Za-z0-9_-]+", directory.name)):
        raise ValueError("invalid public-verification architecture/directory")
    if run("nix", "eval", "--impure", "--raw", "--expr", "builtins.currentSystem").decode() != system:
        raise ValueError("public verification must use the native architecture")
    flags = ("--no-link", "--print-out-paths", "--no-update-lock-file", "--no-write-lock-file")
    bootstrap = store_path(run("nix", "build", *flags, f".#packages.{system}.assbox", cwd=ROOT))
    first = directory.with_name(directory.name + "-bootstrap")
    second = directory.with_name(directory.name + "-candidate")
    run("sudo", f"{bootstrap}/bin/assbox", "release", "verify", tag, str(first))
    # These files exist only after successful bootstrap verification. Do not get
    # the source from /latest, an unverified manifest field, stdout, or an artifact.
    authenticated_source = store_path(run("sudo", "cat", "--", str(first / "verified-source-path")))
    first_manifest = run("sudo", "cat", "--", str(first / "release.json"))
    first_lock = run("sudo", "cat", "--", str(first / "flake.lock"))
    manifest = data.decode(first_manifest)
    data.validate_manifest(manifest)
    if (manifest["tag"] != tag or data.json_bytes(manifest) != first_manifest
            or data.digest(first_lock) != manifest["lockSha256"]):
        raise ValueError("bootstrap inspection did not bind the requested release/lock")
    candidate = store_path(run("nix", "build", *flags,
                              f"path:{authenticated_source}#packages.{system}.assbox", cwd=ROOT))
    run("sudo", f"{candidate}/bin/assbox", "release", "verify", tag, str(second))
    if (run("sudo", "cat", "--", str(second / "release.json")) != first_manifest
            or run("sudo", "cat", "--", str(second / "flake.lock")) != first_lock
            or store_path(run("sudo", "cat", "--", str(second / "verified-source-path"))) != authenticated_source):
        raise ValueError("candidate and bootstrap verifiers disagree about the published release")
    # An unchanged lock/renewal may legitimately reproduce the same store binary.
    # This verifies the candidate's current public round trip, not every possible
    # future server/API change or actual traversal from an installed-machine floor.
    print(f"Bootstrap and candidate public verification passed: {tag} / {system}")


def ready(assets: Path, reports: Path) -> dict:
    manifest, _ = validate_final(assets)
    expected_hash = data.digest((assets / "release.json").read_bytes())
    observed = {}
    for path in reports.rglob("native-*.json"):
        report = load(path)
        system = report.get("system")
        if system not in data.SYSTEMS or system in observed or report != {"system": system, "manifestSha256": expected_hash, "passed": True}:
            raise ValueError("native acceptance reports do not bind this exact manifest")
        observed[system] = report
    if set(observed) != set(data.SYSTEMS):
        raise ValueError("missing native acceptance report")
    return manifest


def attestation_ready(assets: Path, reports: Path) -> None:
    ready(assets, reports)
    check_repository(privileged=True)


def write_api(path: str, payload: dict, *, method: str = "POST"):
    """Re-observe current master immediately before each publication mutation.

    GitHub does not make the read and subsequent write one atomic operation;
    protected master, isolated jobs and cold-admin change control remain required.
    """
    if method not in {"POST", "PATCH"}:
        raise ValueError("unexpected release write method")
    check_repository(privileged=True)
    return api(path, payload, token=True, method=method)


def publish(assets: Path, reports: Path) -> None:
    manifest = ready(assets, reports)
    check_repository(privileged=True)
    bundle = assets / "release.sigstore.json"
    if bundle.is_symlink() or not bundle.is_file() or bundle.stat().st_size > 4 * 1024 * 1024:
        raise ValueError("missing provenance bundle")
    check_parent_head(manifest)
    tag = manifest["tag"]
    # A lightweight tag is intentional: clients verify its attested commit too.
    write_api(f"/repos/{REPO}/git/refs", {"ref": "refs/tags/" + tag, "sha": manifest["coreCommit"]})
    release = write_api(f"/repos/{REPO}/releases", {"tag_name": tag, "target_commitish": manifest["coreCommit"],
                  "name": f"Assbox {manifest['coreVersion']} / {tag}", "draft": True, "prerelease": False,
                  "make_latest": "false", "body": "Authenticated dependency release. See the attached release manifest."})
    # Uploading does not execute asset content. Token is ephemeral GITHUB_TOKEN.
    check_repository(privileged=True)
    run("gh", "release", "upload", tag, *(str(assets / name) for name in ASSETS), "--repo", REPO, github_upload=True)
    published = write_api(f"/repos/{REPO}/releases/{release['id']}", {"draft": False, "make_latest": "false"}, method="PATCH")
    if published.get("immutable") is not True:
        raise ValueError("publication is not immutable; latest was NOT advanced. Enable immutable releases with the cold administrator.")
    output("tag", tag)
    output("release_id", str(release["id"]))


def promote(tag: str, release_id: str) -> None:
    core_tree()
    check_repository(privileged=True)
    if not release_id.isdigit() or not re.fullmatch(r"r-[1-9][0-9]{0,15}", tag):
        raise ValueError("invalid publication identity")
    release = api(f"/repos/{REPO}/releases/{release_id}", token=True)
    if release.get("immutable") is not True or release["tag_name"] != tag or release["draft"] or release["prerelease"]:
        raise ValueError("release cannot be advertised to clients")
    head, _ = inventory()
    if head is None or head["tag_name"] != tag or str(head["id"]) != release_id:
        raise ValueError("cannot advertise an older/non-head release, including from a rerun")
    # latest is UI/discovery metadata only, but never intentionally move it back.
    try:
        latest = api(f"/repos/{REPO}/releases/latest")
    except urllib.error.HTTPError as error:
        if error.code != 404:
            raise
    else:
        if data.release_sequence(latest.get("tag_name")) > data.release_sequence(tag):
            raise ValueError("latest indicates newer history; refuse a backward/incomplete publication")
    write_api(f"/repos/{REPO}/releases/{release_id}", {"make_latest": "true"}, method="PATCH")


def main() -> int:
    global API_TOKEN
    API_TOKEN = os.environ.pop("GH_TOKEN", None)
    # The workflow scopes GH_TOKEN to the Python API step, never an outer nix
    # develop/build invocation. Child processes get a separately scrubbed env.
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    p = commands.add_parser("check-lock"); p.add_argument("tree", type=Path)
    p = commands.add_parser("discover"); p.add_argument("out", type=Path)
    p = commands.add_parser("prepare"); p.add_argument("out", type=Path); p.add_argument("discovery", type=Path)
    p = commands.add_parser("probe"); p.add_argument("plan", type=Path); p.add_argument("application", choices=data.APPLICATIONS); p.add_argument("system", choices=data.SYSTEMS); p.add_argument("report", type=Path)
    p = commands.add_parser("finalize"); p.add_argument("plan", type=Path); p.add_argument("reports", type=Path); p.add_argument("out", type=Path)
    p = commands.add_parser("native"); p.add_argument("assets", type=Path); p.add_argument("system", choices=data.SYSTEMS); p.add_argument("report", type=Path)
    for name in ("ready", "attest-ready", "publish"):
        p = commands.add_parser(name); p.add_argument("assets", type=Path); p.add_argument("reports", type=Path)
    p = commands.add_parser("live-verify"); p.add_argument("tag"); p.add_argument("system", choices=data.SYSTEMS); p.add_argument("directory", type=Path)
    p = commands.add_parser("promote"); p.add_argument("tag"); p.add_argument("release_id")
    args = parser.parse_args()
    try:
        if args.command == "check-lock": check_lock(args.tree)
        elif args.command == "discover": discover(args.out)
        elif args.command == "prepare": prepare(args.out, args.discovery)
        elif args.command == "probe": application_probe(args.plan, args.application, args.system, args.report)
        elif args.command == "finalize": finalize(args.plan, args.reports, args.out)
        elif args.command == "native": native_gate(args.assets, args.system, args.report)
        elif args.command == "ready": ready(args.assets, args.reports)
        elif args.command == "attest-ready": attestation_ready(args.assets, args.reports)
        elif args.command == "live-verify": live_verify(args.tag, args.system, args.directory)
        elif args.command == "publish": publish(args.assets, args.reports)
        elif args.command == "promote": promote(args.tag, args.release_id)
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        print(f"Release operation refused: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
