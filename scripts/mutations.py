#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Only assertion failures from compiled, executed mutants count as detections."""
from __future__ import annotations
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POLICY = "crates/functional-core/assbox-policy/src/lib.rs"
MUTATIONS = [
    ("maintenance-recovery-priority", "else if transaction_pending", "else if false"),
    ("maintenance-pending-priority", "else if reboot_pending", "else if false"),
    ("live-backup-separation", "live_uses_disk(&inv, backup_disk)", "false"),
    ("arm-boot-contract", "architecture == Architecture::Aarch64 && (firmware != Firmware::Uefi || platform != Platform::Generic)", "false"),
    ("rollback-generation-binding", "current.binding != target.binding", "false"),
    ("optical-readonly", "!*read_only", "false"),
    ("same-target-backup", "backup_disk.path == target.path || backup_disk.major_minor == target.major_minor", "false"),
    ("root-readonly", "p.read_only || p.has_holders", "false || p.has_holders"),
    ("bios-embedding-gap", "root.start_bytes < 1024 * 1024", "false"),
    ("bios-gpt-readonly", "extra[0].read_only", "false"),
    ("prepared-root-empty", "entry.is_directory && entry.empty", "entry.is_directory"),
    ("bios-gpt-boot-size", "extra[0].bytes < 1024 * 1024", "false"),
    ("apple-efi-write-guard", "a.boot==BootKind::AppleRefind && a.efi_writes", "false"),
]


def main() -> int:
    cargo = shutil.which("cargo")
    if not cargo:
        raise SystemExit("cargo is required; mutation tests were not executed")
    subprocess.run([cargo, "test", "--workspace", "--locked"], cwd=ROOT, check=True)
    env = os.environ.copy()
    env["CARGO_TARGET_DIR"] = str(ROOT / "target" / "mutations")
    for name, before, after in MUTATIONS:
        with tempfile.TemporaryDirectory(prefix="assbox-mutation-") as temporary:
            copy = Path(temporary) / "source"
            shutil.copytree(ROOT, copy, ignore=shutil.ignore_patterns("target", ".git", "reports", "__pycache__"))
            source = copy / POLICY
            text = source.read_text()
            # Formatting may insert spaces but must not change the reviewed guard.
            import re
            pattern = r"\s*".join(re.escape(token) for token in re.findall(r"\w+|[^\w\s]", before))
            matches = list(re.finditer(pattern, text))
            if len(matches) != 1:
                raise SystemExit(f"mutation anchor changed: {name}; review the mutation")
            match = matches[0]
            source.write_text(text[:match.start()] + after + text[match.end():])
            result = subprocess.run([cargo, "test", "-p", "assbox-policy", "--locked"], cwd=copy,
                                    env=env, capture_output=True, text=True)
            output = result.stdout + result.stderr
            if result.returncode == 0 or "test result: FAILED" not in output or "panicked at" not in output or "could not compile" in output:
                print(output)
                raise SystemExit(f"mutation did not produce a genuine assertion failure: {name}")
            print(f"Detected by executed assertions: {name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
