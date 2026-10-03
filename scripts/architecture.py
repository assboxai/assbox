#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Fail-closed workspace graph and effect-boundary lint; not a Rust purity proof."""
from __future__ import annotations
import re
import sys
import tomllib
from pathlib import Path

GRAPH = {
    "assbox-domain": set(),
    "assbox-policy": {"assbox-domain"},
    "assbox-config": {"assbox-domain", "assbox-policy"},
    "assbox-system": {"assbox-domain"},
    "assbox-engine": {"assbox-domain", "assbox-policy", "assbox-config", "assbox-system"},
    "assbox-cli": {"assbox-domain", "assbox-policy", "assbox-config", "assbox-system", "assbox-engine"},
}
# Reviewed MIT/Apache-compatible signal and terminal adapters; Windows is lock-only.
# rustix's build script probes the compiler/target, with no network or external build dependencies.
REVIEWED_ADAPTERS = {
    "signal-hook": {"version": "=0.4.4", "default-features": False},
    "rustix": {"version": "=1.1.4", "default-features": False, "features": ["std", "termios"]},
}
REVIEWED_ADAPTER_DEPENDENCIES = [{'name': 'bitflags', 'version': '2.13.1', 'source': 'registry+https://github.com/rust-lang/crates.io-index', 'checksum': 'b588b76d00fde79687d7646a9b5bdf3cc0f655e0bbd080335a95d7e96f3587da'}, {'name': 'errno', 'version': '0.3.14', 'source': 'registry+https://github.com/rust-lang/crates.io-index', 'checksum': '39cab71617ae0d63f51a36d69f866391735b51691dbda63cf6f96d042b63efeb', 'dependencies': ['libc', 'windows-sys']}, {'name': 'libc', 'version': '0.2.189', 'source': 'registry+https://github.com/rust-lang/crates.io-index', 'checksum': '3eaf3ede3fee6db1a4c2ee091bf8a8b4dccdc6d17f656fb07896ee72867612f2'}, {'name': 'linux-raw-sys', 'version': '0.12.1', 'source': 'registry+https://github.com/rust-lang/crates.io-index', 'checksum': '32a66949e030da00e8c7d4434b251670a91556f4144941d37452769c25d58a53'}, {'name': 'rustix', 'version': '1.1.4', 'source': 'registry+https://github.com/rust-lang/crates.io-index', 'checksum': 'b6fe4565b9518b83ef4f91bb47ce29620ca828bd32cb7e408f0062e9930ba190', 'dependencies': ['bitflags', 'errno', 'libc', 'linux-raw-sys', 'windows-sys']}, {'name': 'signal-hook', 'version': '0.4.4', 'source': 'registry+https://github.com/rust-lang/crates.io-index', 'checksum': 'b2a0c28ca5908dbdbcd52e6fdaa00358ab88637f8ab33e1f188dd510eb44b53d', 'dependencies': ['libc', 'signal-hook-registry']}, {'name': 'signal-hook-registry', 'version': '1.4.8', 'source': 'registry+https://github.com/rust-lang/crates.io-index', 'checksum': 'c4db69cba1110affc0e9f7bcd48bbf87b3f4fc7c61fc9155afd4c469eb3d6c1b', 'dependencies': ['errno', 'libc']}, {'name': 'windows-link', 'version': '0.2.1', 'source': 'registry+https://github.com/rust-lang/crates.io-index', 'checksum': 'f0805222e57f7521d6a62e36fa9163bc891acd422f971defe97d64e70d0a4fe5'}, {'name': 'windows-sys', 'version': '0.61.2', 'source': 'registry+https://github.com/rust-lang/crates.io-index', 'checksum': 'ae137229bcbd6cdf0f7b80a31df61766145077ddf49416a728b02cb3921ff3fc', 'dependencies': ['windows-link']}]

EFFECT_MODULES = {"fs", "io", "net", "process", "thread", "time", "env", "sync"}


def code_only(text: str) -> str:
    """Remove comments and literals for linting. This does not parse Rust grammar."""
    result: list[str] = []
    i = 0
    while i < len(text):
        if text.startswith("//", i):
            end = text.find("\n", i)
            i = len(text) if end < 0 else end
            result.append(" ")
        elif text.startswith("/*", i):
            depth = 1
            i += 2
            while i < len(text) and depth:
                if text.startswith("/*", i):
                    depth += 1
                    i += 2
                elif text.startswith("*/", i):
                    depth -= 1
                    i += 2
                else:
                    i += 1
            if depth:
                raise ValueError("unterminated block comment")
            result.append(" ")
        else:
            raw = re.match(r'(?:br|r)(#{0,255})"', text[i:])
            if raw:
                end = text.find('"' + raw[1], i + raw.end())
                if end < 0:
                    raise ValueError("unterminated raw string")
                i = end + 1 + len(raw[1])
                result.append(" LITERAL ")
            elif text[i] == '"' or text[i:i+2] == 'b"':
                if text[i] == "b":
                    i += 1
                i += 1
                while i < len(text):
                    if text[i] == "\\":
                        i += 2
                    elif text[i] == '"':
                        i += 1
                        break
                    else:
                        i += 1
                else:
                    raise ValueError("unterminated string")
                result.append(" LITERAL ")
            elif text[i] == "'" and (char := re.match(r"'(?:\\(?:u\{[0-9A-Fa-f]+\}|x[0-9A-Fa-f]{2}|.)|[^'\\])'", text[i:])):
                i += char.end()
                result.append(" LITERAL ")
            else:
                result.append(text[i])
                i += 1
    return "".join(result)


def core_violations(text: str) -> list[str]:
    code = code_only(text)
    errors: list[str] = []
    for declaration in re.findall(r"\buse\s+([^;]+);", code):
        if re.search(r"\bstd\b", declaration):
            names = set(re.findall(r"[A-Za-z_][A-Za-z_0-9]*", declaration))
            if names & EFFECT_MODULES:
                errors.append("effectful standard-library import")
            if re.search(r"\bstd\s+as\b", declaration):
                errors.append("standard-library alias hides the effect boundary")
    if re.search(r"\bstd\s*::\s*(?:" + "|".join(EFFECT_MODULES) + r")\b", code):
        errors.append("fully-qualified effect access")
    if re.search(r"\b(?:print|println|eprint|eprintln|dbg|include|include_str|include_bytes)\s*!", code):
        errors.append("effect or source-inclusion macro in the functional core")
    if re.search(r"\b(?:extern|unsafe)\b|\bstatic\s+mut\b", code):
        errors.append("foreign, unsafe or mutable-global escape")
    if re.search(r"#\s*\[\s*path\s*=", code):
        errors.append("cross-file path escape")
    return errors


def check(root: Path) -> list[str]:
    errors: list[str] = []
    workspace = tomllib.loads((root / "Cargo.toml").read_text())
    package = workspace["workspace"]["package"]
    if package.get("publish") is not False or package.get("edition") != "2024":
        errors.append("workspace must be internal and use the declared Rust edition")
    members = workspace["workspace"]["members"]
    found: dict[str, set[str]] = {}
    for relative in members:
        path = root / relative
        manifest = tomllib.loads((path / "Cargo.toml").read_text())
        name = manifest["package"]["name"]
        dependencies = manifest.get("dependencies", {})
        found[name] = set(dependencies) - (set(REVIEWED_ADAPTERS) if name == "assbox-system" else set())
        side = "functional-core" if name in {"assbox-domain", "assbox-policy", "assbox-config"} else "imperative-shell"
        if Path(relative).parts[:2] != ("crates", side):
            errors.append(f"incorrect architectural location: {name}")
        if manifest["package"].get("publish") != {"workspace": True}:
            errors.append(f"publication policy is not inherited: {name}")
        if manifest.get("lints") != {"workspace": True}:
            errors.append(f"workspace lints are not inherited: {name}")
        if (path / "build.rs").exists() or "build-dependencies" in manifest:
            errors.append(f"unreviewed build-time execution: {name}")
        for dep, spec in dependencies.items():
            if name == "assbox-system" and dep in REVIEWED_ADAPTERS and spec == REVIEWED_ADAPTERS[dep]:
                continue
            if not isinstance(spec, dict) or set(spec) != {"path"}:
                errors.append(f"only reviewed internal path dependencies are currently allowed: {name}/{dep}")
            elif not (path / spec["path"]).resolve().is_relative_to(root.resolve()):
                errors.append(f"dependency escapes the workspace: {name}/{dep}")
            elif tomllib.loads((path / spec["path"] / "Cargo.toml").read_text())["package"]["name"] != dep:
                errors.append(f"dependency alias hides a different crate: {name}/{dep}")
        source = path / "src" / ("main.rs" if name == "assbox-cli" else "lib.rs")
        if "#![forbid(unsafe_code)]" not in source.read_text():
            errors.append(f"unsafe code is not forbidden at the crate root: {name}")
        if side == "functional-core":
            for rust in (path / "src").rglob("*.rs"):
                errors.extend(f"{rust.relative_to(root)}: {e}" for e in core_violations(rust.read_text()))
    if found != GRAPH:
        errors.append(f"internal dependency graph changed without an architectural update: {found}")
    lock = tomllib.loads((root / "Cargo.lock").read_text())
    internal = [p for p in lock["package"] if p["name"] in GRAPH]
    locked = {p["name"]: set(p.get("dependencies", [])) - (set(REVIEWED_ADAPTERS) if p["name"] == "assbox-system" else set()) for p in internal}
    registry = [p for p in lock["package"] if p["name"] not in GRAPH]
    if registry != REVIEWED_ADAPTER_DEPENDENCIES:
        errors.append("unreviewed system adapter dependency graph; review exact versions, licenses and checksums")
    if locked != GRAPH or any("source" in p or p["version"] != package["version"] for p in internal):
        errors.append("Cargo.lock does not describe the internal workspace exactly")
    for path in root.rglob("*"):
        if any(part in {".git", "target", "reports", "__pycache__", ".chainman", ".cache"} for part in path.relative_to(root).parts):
            continue
        if path.is_symlink():
            errors.append(f"source symlink: {path.relative_to(root)}")
    return errors


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    try:
        errors = check(root)
    except (OSError, ValueError, KeyError) as error:
        print(f"Architecture check could not complete: {error}", file=sys.stderr)
        return 1
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    print(f"Architecture checks passed: {len(GRAPH)} internal crates; declared inward dependency graph.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
