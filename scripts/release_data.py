#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Pure CI release-data transformations. No credentials, network, clock or subprocesses."""
from __future__ import annotations
import copy
import gzip
import hashlib
import io
import json
import re
import tarfile
from pathlib import PurePosixPath

from component_families import FAMILIES

APPLICATIONS = FAMILIES
INPUTS = ("nixpkgs", *(f"{name}-packages" for name in APPLICATIONS))
SYSTEMS = ("aarch64-linux", "x86_64-linux")


def json_bytes(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n").encode()


def decode(data: bytes) -> object:
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key: {key}")
            result[key] = value
        return result
    return json.loads(data, object_pairs_hook=unique,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite JSON number")))


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def validate_lock(lock: dict) -> None:
    if not isinstance(lock, dict) or type(lock.get("version")) is not int or lock.get("version") != 7 or not isinstance(lock.get("nodes"), dict):
        raise ValueError("unsupported lock graph")
    nodes = lock["nodes"]
    root = lock.get("root")
    if root not in nodes or set(nodes[root].get("inputs", {})) != set(INPUTS):
        raise ValueError("release root input set changed; explicit source migration is required")
    if len(nodes) > 10000:
        raise ValueError("excessive lock graph")
    for name, node in nodes.items():
        if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", name) or not isinstance(node, dict):
            raise ValueError("invalid lock node")
        if name != root and (node.get("locked", {}).get("type") not in {"github", "git", "tarball"}
                             or not re.fullmatch(r"sha256-[A-Za-z0-9+/]{43}=", node["locked"].get("narHash", ""))):
            raise ValueError("unlocked, local or unsupported release input")
        if "parent" in node:
            raise ValueError("relative lock schema not supported")
        if not isinstance(node.get("inputs", {}), dict):
            raise ValueError("invalid lock input map")
        for value in node.get("inputs", {}).values():
            if isinstance(value, str):
                if value not in nodes:
                    raise ValueError("dangling lock input")
            elif not isinstance(value, list) or not value or any(not isinstance(v, str) or not v for v in value):
                raise ValueError("invalid follows edge")

    def resolve(value, active):
        if isinstance(value, str):
            return value
        key = tuple(value)
        if key in active:
            raise ValueError("cyclic follows edge")
        node = root
        for part in value:
            edge = nodes[node].get("inputs", {}).get(part)
            if edge is None:
                raise ValueError("follows path missing from composed graph")
            node = resolve(edge, active | {key})
        return node

    for node in nodes.values():
        for edge in node.get("inputs", {}).values():
            resolve(edge, set())


def require_same_inputs(before: dict, after: dict) -> None:
    """Allow Nix to rename/share nodes, but never change any reachable input.

    Compare pairs of resolved nodes instead of expanding shared subtrees. This
    also terminates on recursive input graphs without discarding their edges.
    """
    validate_lock(before)
    validate_lock(after)

    def resolve(lock, edge):
        if isinstance(edge, str):
            return edge
        node = lock["root"]
        for part in edge:
            node = resolve(lock, lock["nodes"][node]["inputs"][part])
        return node

    pending, seen = [(before["root"], after["root"])], set()
    while pending:
        pair = pending.pop()
        if pair in seen:
            continue
        seen.add(pair)
        left, right = before["nodes"][pair[0]], after["nodes"][pair[1]]
        left_inputs, right_inputs = left.get("inputs", {}), right.get("inputs", {})
        if ({k: v for k, v in left.items() if k != "inputs"}
                != {k: v for k, v in right.items() if k != "inputs"}
                or left_inputs.keys() != right_inputs.keys()):
            raise ValueError("Nix changed a selected dependency or its input graph")
        pending.extend((resolve(before, left_inputs[key]), resolve(after, right_inputs[key]))
                       for key in left_inputs)


def compose_lock(previous: dict, latest: dict, advanced: set[str]) -> dict:
    """Copy a complete pinned input subtree, not merely its top-level revision.

    Absolute follows paths retain their root-relative meaning. String node edges
    are namespaced per selected root, preventing one application from upgrading
    another application's transitive dependencies by accidental node aliasing.
    """
    validate_lock(previous)
    validate_lock(latest)
    if not advanced <= set(INPUTS):
        raise ValueError("unknown release input")
    out = {"version": 7, "root": "root", "nodes": {"root": {"inputs": {}}}}
    for input_name in INPUTS:
        source = latest if input_name in advanced else previous
        nodes = source["nodes"]
        prefix = input_name.replace("-", "_") + "__"
        copied = {}

        def visit(edge):
            if isinstance(edge, list):
                return copy.deepcopy(edge)
            if edge in copied:
                return copied[edge]
            name = prefix + str(len(copied))
            copied[edge] = name
            value = copy.deepcopy(nodes[edge])
            out["nodes"][name] = value
            if "inputs" in value:
                value["inputs"] = {key: visit(ref) for key, ref in sorted(value["inputs"].items())}
            return name

        out["nodes"]["root"]["inputs"][input_name] = visit(nodes[source["root"]]["inputs"][input_name])
    validate_lock(out)
    return out


def select_inputs(reports: list[dict], plan_digest: str) -> set[str]:
    expected = {(app, system) for app in APPLICATIONS for system in SYSTEMS}
    indexed = {}
    for report in reports:
        key = (report.get("application"), report.get("system"))
        if key not in expected or key in indexed or report.get("planSha256") != plan_digest:
            raise ValueError("missing, duplicate or unrelated application probe evidence")
        if type(report.get("passed")) is not bool or type(report.get("exitCode")) is not int:
            raise ValueError("invalid probe result")
        if report["passed"] != (report["exitCode"] == 0):
            raise ValueError("contradictory probe evidence")
        indexed[key] = report
    if set(indexed) != expected:
        raise ValueError("both native architectures must report every application")
    return {"nixpkgs"} | {f"{app}-packages" for app in APPLICATIONS
                         if all(indexed[(app, system)]["passed"] for system in SYSTEMS)}


def source_files(core: dict[str, tuple[int, bytes]], lock_bytes: bytes, context: dict) -> dict[str, tuple[int, bytes]]:
    validate_lock(decode(lock_bytes))
    if "flake.lock" not in core or "release-context.json" in core:
        raise ValueError("core needs a reviewed bootstrap lock, not generated release context")
    files = dict(core)
    files["flake.lock"] = (0o644, lock_bytes)
    files["release-context.json"] = (0o644, json_bytes(context))
    return files


def pack_source(files: dict[str, tuple[int, bytes]]) -> bytes:
    out = io.BytesIO()
    with gzip.GzipFile(fileobj=out, mode="wb", filename="", mtime=0) as zipped:
        with tarfile.open(fileobj=zipped, mode="w", format=tarfile.USTAR_FORMAT) as tar:
            for name in sorted(files):
                mode, data = files[name]
                path = PurePosixPath(name)
                if path.is_absolute() or ".." in path.parts or str(path) != name or mode not in {0o644, 0o755}:
                    raise ValueError("unsafe source member")
                member = tarfile.TarInfo("assbox/" + name)
                member.mode, member.size, member.mtime = mode, len(data), 0
                tar.addfile(member, io.BytesIO(data))
    return out.getvalue()


def unpack_source(data: bytes) -> dict[str, tuple[int, bytes]]:
    """Inspect into memory; never extract untrusted paths or follow links."""
    result, total = {}, 0
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
        for member in tar:
            path = PurePosixPath(member.name)
            if (not member.isfile() or member.mode not in {0o644, 0o755} or member.pax_headers
                    or len(path.parts) < 2 or path.parts[0] != "assbox" or ".." in path.parts
                    or str(path) != member.name or member.size > 16 * 1024 * 1024):
                raise ValueError("unsafe release source member")
            name = str(PurePosixPath(*path.parts[1:]))
            total += member.size
            if name in result or len(result) >= 20000 or total > 128 * 1024 * 1024:
                raise ValueError("duplicate or excessive source archive")
            content = tar.extractfile(member)
            if content is None:
                raise ValueError("source content missing")
            result[name] = (member.mode, content.read())
    return result


def validate_source(archive: bytes, core: dict, lock_bytes: bytes, context: dict) -> dict:
    expected = source_files(core, lock_bytes, context)
    actual = unpack_source(archive)
    if actual != expected:
        raise ValueError("release contains changed core bytes, unexpected files or changed executable modes")
    return actual


def release_sequence(tag: str) -> int:
    if not isinstance(tag, str) or not re.fullmatch(r"r-[1-9][0-9]{0,15}", tag):
        raise ValueError("invalid immutable release tag")
    return int(tag[2:])


def validate_manifest(manifest: dict) -> None:
    """Validate schema/lineage shape, not cryptographic authorization or freshness."""
    fields = {"schema", "protocol", "channel", "tag", "coreCommit", "coreVersion",
              "issuedAt", "expiresAt", "sourceSha256", "sourceNarHash", "lockSha256",
              "systems", "heldInputs", "previousTag", "previousManifestSha256"}
    if (not isinstance(manifest, dict) or set(manifest) != fields
            or type(manifest["schema"]) is not int or manifest["schema"] != 3
            or type(manifest["protocol"]) is not int or manifest["protocol"] != 3
            or manifest["channel"] != "stable" or manifest["systems"] != list(SYSTEMS)):
        raise ValueError("unsupported release manifest schema/protocol/channel")
    m = manifest
    sequence = release_sequence(m["tag"])
    for field, pattern in (("coreCommit", r"[0-9a-f]{40}"), ("coreVersion", r"[A-Za-z0-9.-]{1,40}"),
                           ("sourceSha256", r"[0-9a-f]{64}"), ("lockSha256", r"[0-9a-f]{64}"),
                           ("sourceNarHash", r"sha256-[A-Za-z0-9+/]{43}=")):
        if not isinstance(m[field], str) or not re.fullmatch(pattern, m[field]):
            raise ValueError("invalid release identity field: " + field)
    if (any(type(m[k]) is not int or not 0 < m[k] <= 9007199254740991 for k in ("issuedAt", "expiresAt"))
            or m["expiresAt"] - m["issuedAt"] != 604800):
        raise ValueError("invalid release lifetime")
    held = m["heldInputs"]
    if (not isinstance(held, list) or any(not isinstance(v, str) for v in held)
            or sorted(set(held)) != held or not set(held) <= set(INPUTS) - {"nixpkgs"}):
        raise ValueError("invalid held-input report")
    parent, digest_value = m["previousTag"], m["previousManifestSha256"]
    if parent is None or digest_value is None:
        if parent is not None or digest_value is not None or sequence != 1:
            raise ValueError("only the reserved r-1 genesis may have no parent")
    elif (release_sequence(parent) >= sequence or not isinstance(digest_value, str)
          or not re.fullmatch(r"[0-9a-f]{64}", digest_value)):
        raise ValueError("invalid/non-forward release parent")


def require_parent(child: dict, parent: dict | None, parent_bytes: bytes | None) -> None:
    """Bind to actual predecessor bytes; parsed/re-serialized JSON is not a substitute."""
    validate_manifest(child)
    if parent is None:
        if parent_bytes is not None or child["tag"] != "r-1":
            raise ValueError("a non-genesis release requires its authenticated predecessor")
        return
    validate_manifest(parent)
    if (parent_bytes is None or decode(parent_bytes) != parent or json_bytes(parent) != parent_bytes
            or child["previousTag"] != parent["tag"]
            or child["previousManifestSha256"] != digest(parent_bytes)
            or child["issuedAt"] < parent["issuedAt"]):
        raise ValueError("release is not a forward hash-linked child of the authenticated head")


def make_manifest(core_commit: str, core_version: str, issued_at: int, previous: dict | None,
                  source_sha: str, source_nar: str, lock_sha: str, held: list[str]) -> dict:
    # All published manifests are canonical JSON. A fixed genesis tag prevents an
    # empty/deleted history from being silently recreated under a new timestamp.
    if previous is not None:
        validate_manifest(previous)
        if issued_at < previous["issuedAt"]:
            raise ValueError("release clock moved backwards")
    tag = "r-1" if previous is None else f"r-{max(issued_at, release_sequence(previous['tag']) + 1)}"
    manifest = {"schema": 3, "protocol": 3, "channel": "stable", "tag": tag,
                "coreCommit": core_commit, "coreVersion": core_version, "issuedAt": issued_at,
                "expiresAt": issued_at + 604800, "sourceSha256": source_sha, "sourceNarHash": source_nar,
                "lockSha256": lock_sha, "systems": list(SYSTEMS), "heldInputs": held,
                "previousTag": None if previous is None else previous["tag"],
                "previousManifestSha256": None if previous is None else digest(json_bytes(previous))}
    validate_manifest(manifest)
    return manifest


def history_head(releases: list[dict], tags: list[dict]) -> tuple[dict | None, str | None]:
    """Untrusted discovery, independent of latest. Caller MUST authenticate the head.

    Refuse malformed, partial or conflicting history rather than silently skipping
    a newer entry and falling back to an older authenticated dependency set.
    """
    records = {}
    for release in releases:
        name = release.get("tag_name")
        if not isinstance(name, str):
            raise ValueError("release inventory lacks tag identity")
        if not name.startswith("r-"):
            continue
        release_sequence(name)
        if (name in records or release.get("draft") is not False
                or release.get("prerelease") is not False or release.get("immutable") is not True
                or type(release.get("id")) is not int or release["id"] <= 0):
            raise ValueError("duplicate, incomplete or nonimmutable release history")
        records[name] = release
    named_tags = {}
    for tag in tags:
        name = tag.get("name")
        if not isinstance(name, str):
            raise ValueError("tag inventory lacks identity")
        if not name.startswith("r-"):
            continue
        release_sequence(name)
        commit = tag.get("commit", {}).get("sha")
        if name in named_tags or not isinstance(commit, str) or not re.fullmatch(r"[0-9a-f]{40}", commit):
            raise ValueError("duplicate or malformed release tag inventory")
        named_tags[name] = commit
    if set(named_tags) != set(records):
        raise ValueError("orphan release/tag detected; inspect partial publication or deleted history")
    if not records:
        if releases or tags:
            raise ValueError("genesis requires an empty release and tag namespace")
        return None, None
    if "r-1" not in records:
        raise ValueError("reserved genesis release missing; do not restart channel history")
    ordered = sorted(records, key=release_sequence)
    return records[ordered[-1]], (ordered[-2] if len(ordered) > 1 else None)


def needs_release(previous: dict | None, manifest: dict, now: int) -> bool:
    if previous is None:
        return True
    if now < previous["issuedAt"]:
        raise ValueError("release clock moved backwards")
    return (any(previous.get(key) != manifest[key] for key in ("coreCommit", "sourceNarHash", "lockSha256"))
            or now - previous["issuedAt"] >= 259200)
