#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Verified lock-only maintenance; the final writer executes no candidate code."""
from __future__ import annotations
import argparse
import base64
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import urllib.request
import release as rel
import release_data as data

ROOT = Path(__file__).resolve().parents[1]
VARIANTS = ("candidate", "current")
GATES = ("source-clean", "verify", "acceptance-vms", "core-coverage-90", "cargo-audit", "closure-vulnix")
LOCK_LIMIT = 8 * 1024 * 1024
UPDATE = "mutation AssboxBootstrap($input: UpdateRefsInput!) { updateRefs(input: $input) { clientMutationId } }"


def release_sequence(tag: str) -> int:
    # Use the same 16-digit release namespace as the publisher and Rust client.
    return data.release_sequence(tag)


def identity() -> dict:
    if (os.environ.get("GITHUB_REPOSITORY") != rel.REPO or os.environ.get("GITHUB_REF") != "refs/heads/master"
            or os.environ.get("GITHUB_EVENT_NAME") not in {"schedule", "workflow_dispatch"}):
        raise ValueError("bootstrap requires the official master maintenance workflow")
    result = {"baseSha": os.environ.get("GITHUB_SHA", ""), "runId": os.environ.get("GITHUB_RUN_ID", ""),
              "runAttempt": os.environ.get("GITHUB_RUN_ATTEMPT", "")}
    oid(result["baseSha"])
    if any(not re.fullmatch(r"[1-9][0-9]{0,19}", result[key]) for key in ("runId", "runAttempt")):
        raise ValueError("invalid run identity")
    return result


def oid(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{40}", value) or value == "0" * 40:
        raise ValueError("invalid Git object identity")
    return value


def observe_repository() -> dict:
    expected = identity()
    policy = rel.load(ROOT / "release/policy.json")
    if (policy.get("repository") != rel.REPO or policy.get("sourceRef") != "refs/heads/master"
            or policy.get("workflow") != ".github/workflows/release.yml" or policy.get("channel") != "stable"
            or any(type(policy.get(k)) is not int or policy[k] < 0 for k in ("repositoryId", "ownerId"))):
        raise ValueError("unsupported bootstrap policy")
    repo = rel.api(f"/repos/{rel.REPO}")
    if (repo.get("full_name") != rel.REPO or repo.get("default_branch") != "master"
            or repo.get("private") is not False or repo.get("fork") is not False
            or type(repo.get("id")) is not int or repo["id"] <= 0
            or type(repo.get("owner", {}).get("id")) is not int or repo["owner"]["id"] <= 0
            or not isinstance(repo.get("node_id"), str) or not repo["node_id"]):
        raise ValueError("bootstrap repository changed")
    # Zero means unprovisioned, never an invented immutable identity. Once set,
    # numeric identity checks apply to every maintenance operation too.
    for name, value in (("repositoryId", repo["id"]), ("ownerId", repo["owner"]["id"])):
        if policy[name] and policy[name] != value:
            raise ValueError("provisioned immutable identity changed")
    ref = rel.api(f"/repos/{rel.REPO}/git/ref/heads/master")
    if ref.get("ref") != "refs/heads/master" or ref.get("object", {}).get("sha") != expected["baseSha"]:
        raise ValueError("master moved; stale maintenance cannot write")
    return repo


def tokenless() -> None:
    if rel.API_TOKEN or any(os.environ.get(k) for k in ("GH_TOKEN", "GITHUB_TOKEN", "ACTIONS_ID_TOKEN_REQUEST_TOKEN", "ACTIONS_ID_TOKEN_REQUEST_URL")):
        raise ValueError("candidate execution requires a separate tokenless process")


def source() -> dict:
    identity()
    _, files = rel.core_tree(require_lock=False)
    for name, (mode, raw) in files.items():
        path = ROOT / name
        if rel.bounded_bytes(path, 16 * 1024 * 1024) != raw or path.stat().st_mode & 0o777 != mode:
            raise ValueError("checkout differs from frozen master")
    return files


def lock(path: Path) -> bytes:
    raw = rel.bounded_bytes(path, LOCK_LIMIT)
    data.validate_lock(data.decode(raw))
    return raw


def discover(out: Path) -> None:
    source()
    observe_repository()
    head, prior = rel.inventory()
    if head is None:
        # Genesis requires truly empty raw namespaces, not merely no recognized
        # release prefix after filtering. inventory has already traversed history.
        for collection in ("releases", "tags"):
            if rel.api(f"/repos/{rel.REPO}/{collection}?per_page=1&page=1") != []:
                raise ValueError("nonempty raw namespace cannot authorize genesis")
    rel.write(out, {"schema": 1, **identity(), "head": head, "previousTag": prior})


def prepare(discovery: Path, out: Path) -> None:
    tokenless()
    core = source()
    observed = rel.load(discovery)
    if (set(observed) != {"schema", *identity(), "head", "previousTag"} or type(observed["schema"]) is not int or observed["schema"] != 1
            or any(observed[k] != v for k, v in identity().items())):
        raise ValueError("discovery is not from this exact run")
    current = core.get("flake.lock", (0, None))[1]
    if current is not None:
        data.validate_lock(data.decode(current))
    head, prior = observed["head"], observed["previousTag"]
    origin, tag = "genesis", None
    try:
        if head is None:
            if prior is not None:
                raise ValueError("empty namespace has a predecessor")
            if current is not None:
                candidate, origin = current, "existing"
            else:
                with tempfile.TemporaryDirectory(prefix="assbox-bootstrap-genesis-") as temp:
                    tree = Path(temp) / "source"
                    rel.materialize(core, tree)
                    rel.run("nix", "flake", "lock", "--flake", str(tree))
                    candidate = lock(tree / "flake.lock")
        else:
            if (not isinstance(head, dict) or head.get("immutable") is not True
                    or head.get("draft") is not False or head.get("prerelease") is not False or current is None):
                raise ValueError("history requires an immutable head and an existing pinned verifier")
            tag = head["tag_name"]
            release_sequence(tag)
            if prior is not None:
                release_sequence(prior)
            binary = rel.run("nix", "build", "--no-link", "--print-out-paths", "--no-update-lock-file",
                             "--no-write-lock-file", ".#assbox", cwd=ROOT).decode().strip() + "/bin/assbox"
            if not re.fullmatch(r"/nix/store/[A-Za-z0-9.+_-]+/bin/assbox", binary):
                raise ValueError("invalid bootstrap verifier path")
            location = "/var/lib/assbox-bootstrap-" + identity()["runId"] + "-" + identity()["runAttempt"]
            rel.run("sudo", binary, "internal", "release-baseline", tag, location)
            manifest_bytes = rel.run("sudo", "cat", location + "/release.json")
            manifest = data.decode(manifest_bytes)
            candidate = rel.run("sudo", "cat", location + "/flake.lock")
            if (len(candidate) > LOCK_LIMIT or data.json_bytes(manifest) != manifest_bytes or manifest["tag"] != tag
                    or manifest["previousTag"] != prior or data.digest(candidate) != manifest["lockSha256"]):
                raise ValueError("authenticated head/lock disagrees with complete history")
            origin = "authenticated-release"
        data.validate_lock(data.decode(candidate))
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        if current is None:
            raise
        print(f"Candidate refused; only independently verified existing-lock keepalive is eligible: {error}", file=sys.stderr)
        candidate, origin, tag = current, "existing-after-refusal", None
    out.mkdir(parents=True, exist_ok=False)
    (out / "candidate.lock").write_bytes(candidate)
    if current is not None:
        (out / "current.lock").write_bytes(current)
    rel.write(out / "plan.json", {"schema": 1, **identity(), "origin": origin, "releaseTag": tag,
        "candidateSha256": data.digest(candidate), "currentSha256": None if current is None else data.digest(current)})


def plan(assets: Path) -> tuple[dict, dict]:
    value = rel.load(assets / "plan.json")
    if (not isinstance(value, dict) or set(value) != {"schema", *identity(), "origin", "releaseTag", "candidateSha256", "currentSha256"}
            or type(value["schema"]) is not int or value["schema"] != 1 or any(value[k] != v for k, v in identity().items())
            or value["origin"] not in {"genesis", "existing", "authenticated-release", "existing-after-refusal"}):
        raise ValueError("invalid/stale bootstrap plan")
    if value["origin"] == "authenticated-release":
        release_sequence(value["releaseTag"])
    elif value["releaseTag"] is not None:
        raise ValueError("unauthenticated selection cannot claim a release identity")
    locks = {"candidate": lock(assets / "candidate.lock"), "current": None}
    if value["currentSha256"] is not None:
        locks["current"] = lock(assets / "current.lock")
    for variant, raw in locks.items():
        if value[variant + "Sha256"] != (None if raw is None else data.digest(raw)):
            raise ValueError("bootstrap lock digest mismatch")
    names = {"plan.json", "candidate.lock"} | ({"current.lock"} if locks["current"] is not None else set())
    if assets.is_symlink() or {p.name for p in assets.iterdir()} != names:
        raise ValueError("unexpected bootstrap artifacts")
    if value["origin"] == "genesis":
        if locks["current"] is not None:
            raise ValueError("genesis cannot carry a baseline lock")
    elif locks["current"] is None:
        raise ValueError("non-genesis maintenance requires the committed lock")
    if value["origin"] in {"existing", "existing-after-refusal"} and locks["candidate"] != locks["current"]:
        raise ValueError("existing-lock maintenance cannot claim a different candidate")
    return value, locks


def clean_tree(tree: Path, expected: dict) -> None:
    actual = set()
    for path in tree.rglob("*"):
        relative = path.relative_to(tree)
        if relative.parts[0] in {"target", "reports"} or "__pycache__" in relative.parts:
            continue
        if path.is_symlink():
            raise ValueError("verification created a source symlink")
        if path.is_file():
            actual.add(relative.as_posix())
    if actual != set(expected):
        raise ValueError("verification added or removed source files")
    for name, (mode, raw) in expected.items():
        path = tree / name
        if path.stat().st_mode & 0o777 != mode or rel.bounded_bytes(path, 16 * 1024 * 1024) != raw:
            raise ValueError("verification modified source instead of checking it")


def native(assets: Path, variant: str, system: str, report: Path) -> None:
    tokenless()
    core = source()
    value, locks = plan(assets)
    if variant not in VARIANTS or system not in data.SYSTEMS:
        raise ValueError("unknown native bootstrap selection")
    if rel.run("nix", "eval", "--impure", "--raw", "--expr", "builtins.currentSystem").decode().strip() != system:
        raise ValueError("cross-architecture reports are not native acceptance")
    if core.get("flake.lock", (0, None))[1] != locks["current"]:
        raise ValueError("baseline artifact differs from frozen master")
    passed = False
    raw = locks[variant]
    if raw is not None:
        files = {**core, "flake.lock": (0o644, raw)}
        try:
            with tempfile.TemporaryDirectory(prefix="assbox-bootstrap-native-") as temp:
                tree = Path(temp) / "source"
                rel.materialize(files, tree)
                rel.run("nix", "develop", "--no-update-lock-file", "--no-write-lock-file", "path:" + str(tree) + "#release-check",
                        "--command", "bash", str(tree / "scripts/release-check"), "--bootstrap", str(tree))
                clean_tree(tree, files)
                passed = True
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            print(f"Native {variant}/{system} refused: {error}", file=sys.stderr)
    report.parent.mkdir(parents=True, exist_ok=True)
    rel.write(report, {"schema": 1, **identity(), "planSha256": data.digest((assets / "plan.json").read_bytes()),
        "variant": variant, "system": system, "lockSha256": value[variant + "Sha256"],
        "passed": passed, "gates": list(GATES) if passed else []})


def select(assets: Path, reports: Path) -> tuple[dict, bytes, bytes | None]:
    value, locks = plan(assets)
    seen = {}
    if reports.is_symlink():
        raise ValueError("evidence directory symlink")
    for path in sorted(reports.rglob("*")):
        if path.is_symlink():
            raise ValueError("evidence symlink")
        if not path.is_file():
            continue
        report = data.decode(rel.bounded_bytes(path, 16384))
        if not isinstance(report, dict) or set(report) != {"schema", *identity(), "planSha256", "variant", "system", "lockSha256", "passed", "gates"}:
            raise ValueError("invalid bootstrap evidence schema")
        key = (report["variant"], report["system"])
        if (key in seen or key[0] not in VARIANTS or key[1] not in data.SYSTEMS or type(report["schema"]) is not int or report["schema"] != 1
                or any(report[k] != v for k, v in identity().items())
                or report["planSha256"] != data.digest((assets / "plan.json").read_bytes())
                or report["lockSha256"] != value[key[0] + "Sha256"] or type(report["passed"]) is not bool
                or report["gates"] != (list(GATES) if report["passed"] else [])
                or report["passed"] and locks[key[0]] is None):
            raise ValueError("duplicate, incomplete, mismatched or stale native evidence")
        seen[key] = report["passed"]
    if set(seen) != {(v, s) for v in VARIANTS for s in data.SYSTEMS}:
        raise ValueError("both variants and native architectures require unique reports")
    for variant in VARIANTS:
        if all(seen[(variant, s)] for s in data.SYSTEMS):
            return value, locks[variant], locks["current"]
    raise ValueError("neither lock is natively verified; no keepalive")


def tree_entries(tree: dict) -> dict:
    if not isinstance(tree, dict) or tree.get("truncated") is not False or not isinstance(tree.get("tree"), list):
        raise ValueError("truncated/invalid Git tree")
    result = {}
    for entry in tree["tree"]:
        name = entry["path"]
        if not isinstance(name, str) or "/" in name or name in result:
            raise ValueError("invalid top-level Git tree")
        result[name] = (entry["mode"], entry["type"], oid(entry["sha"]))
    return result


def compare_and_swap(node: str, before: str, after: str) -> None:
    if not rel.API_TOKEN:
        raise ValueError("writer requires its ephemeral token")
    mutation_id = "assbox-bootstrap-" + identity()["runId"] + "-" + identity()["runAttempt"]
    payload = {"query": UPDATE, "variables": {"input": {"repositoryId": node, "clientMutationId": mutation_id,
        "refUpdates": [{"name": "refs/heads/master", "beforeOid": oid(before), "afterOid": oid(after), "force": False}]}}}
    request = urllib.request.Request("https://api.github.com/graphql", data=data.json_bytes(payload),
        headers={"Authorization": "Bearer " + rel.API_TOKEN, "Content-Type": "application/json", "User-Agent": "Assbox-bootstrap-writer"}, method="POST")
    with urllib.request.build_opener(rel.NoRedirect).open(request, timeout=60) as response:
        raw = response.read(65537)
    if len(raw) > 65536:
        raise ValueError("oversized ref update response; inspect master")
    result = data.decode(raw)
    response_data = result.get("data") if isinstance(result, dict) else None
    update = response_data.get("updateRefs") if isinstance(response_data, dict) else None
    if (not isinstance(update, dict) or result.get("errors")
            or update.get("clientMutationId") != mutation_id):
        raise ValueError("atomic ref update refused or uncertain; inspect master, never force")


def write(assets: Path, reports: Path) -> None:
    """Only this command has write authority. No subprocess or candidate executes."""
    value, selected, baseline = select(assets, reports)
    repo = observe_repository()
    base = value["baseSha"]
    def api(suffix, payload=None):
        return rel.api(f"/repos/{rel.REPO}/git/{suffix}", payload, token=True)
    commit = api("commits/" + base)
    old_tree = oid(commit["tree"]["sha"])
    before = tree_entries(api("trees/" + old_tree))
    entry = before.get("flake.lock")
    if entry is not None:
        if entry[:2] != ("100644", "blob") or baseline is None:
            raise ValueError("baseline is not an ordinary committed lock")
        blob = api("blobs/" + entry[2])
        if blob.get("encoding") != "base64" or base64.b64decode(blob["content"], validate=False) != baseline:
            raise ValueError("baseline differs from current master bytes")
    elif baseline is not None:
        raise ValueError("baseline claims an uncommitted lock")
    new_tree = old_tree
    if selected != baseline:
        blob = api("blobs", {"encoding": "base64", "content": base64.b64encode(selected).decode("ascii")})
        new_blob = oid(blob["sha"])
        tree = api("trees", {"base_tree": old_tree, "tree": [{"path": "flake.lock", "mode": "100644", "type": "blob", "sha": new_blob}]})
        new_tree = oid(tree["sha"])
        if tree_entries(api("trees/" + new_tree)) != {**before, "flake.lock": ("100644", "blob", new_blob)}:
            raise ValueError("maintenance attempted a change other than flake.lock")
    message = "Maintain verified bootstrap lock" if new_tree != old_tree else "Keep verified bootstrap active"
    created = api("commits", {"message": message, "tree": new_tree, "parents": [base]})
    new_commit = oid(created["sha"])
    if created["tree"]["sha"] != new_tree or [p["sha"] for p in created["parents"]] != [base]:
        raise ValueError("created commit is not the verified single-parent tree")
    observe_repository()
    compare_and_swap(repo["node_id"], base, new_commit)
    print(f"Published bounded bootstrap commit {new_commit}; lock SHA-256 {data.digest(selected)}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    p = commands.add_parser("discover"); p.add_argument("out", type=Path)
    p = commands.add_parser("prepare"); p.add_argument("discovery", type=Path); p.add_argument("out", type=Path)
    p = commands.add_parser("native"); p.add_argument("assets", type=Path); p.add_argument("variant", choices=VARIANTS); p.add_argument("system", choices=data.SYSTEMS); p.add_argument("report", type=Path)
    p = commands.add_parser("write"); p.add_argument("assets", type=Path); p.add_argument("reports", type=Path)
    args = parser.parse_args()
    rel.API_TOKEN = os.environ.pop("GH_TOKEN", None)
    try:
        if args.command == "discover": discover(args.out)
        elif args.command == "prepare": prepare(args.discovery, args.out)
        elif args.command == "native": native(args.assets, args.variant, args.system, args.report)
        elif args.command == "write": write(args.assets, args.reports)
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        print(f"Bootstrap maintenance refused: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
