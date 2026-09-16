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
        found[name] = set(dependencies)
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
    locked = {p["name"]: set(p.get("dependencies", [])) for p in lock["package"]}
    if locked != GRAPH or any("source" in p or p["version"] != package["version"] for p in lock["package"]):
        errors.append("Cargo.lock does not describe the internal workspace exactly")
    for path in root.rglob("*"):
        if any(part in {".git", "target", "reports", "__pycache__"} for part in path.relative_to(root).parts):
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
