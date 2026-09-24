#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Run on a disposable, configured Assbox host. Restarts the real worker once.

Uses the generated transport, not a shared-filesystem NixOS test-driver VM.
Does not authenticate a provider or examine personal account history.
"""
from pathlib import Path
import argparse
import importlib.util
import json
import os
import pwd
import subprocess
import sys
import uuid


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--acknowledge-worker-restart", action="store_true", required=True)
    args = p.parse_args()
    if os.geteuid() != 0:
        p.error("Run as the host administrator through sudo on a disposable appliance")
    source = Path(__file__).resolve().parents[2] / "scripts/worker/worker.py"
    spec = importlib.util.spec_from_file_location("worker", source)
    w = importlib.util.module_from_spec(spec); spec.loader.exec_module(w)
    c = w.load_config()
    token = uuid.uuid4().hex
    canary = Path("/home/agent") / (".worker-host-canary-" + token)
    guest_file = "/home/agent/.assbox-worker-acceptance-" + token
    tests = []
    controller = pwd.getpwnam(c["controller"])
    if controller.pw_uid <= 0 or controller.pw_gid <= 0:
        p.error("Worker acceptance SSH must use an unprivileged controller identity")
    def ssh(command):
        # The worker is hostile even during testing. Root performs local
        # lifecycle observations, not network-facing SSH protocol parsing.
        return w.bounded_capture(w.ssh_args(c) + [command], timeout=20,
                                 credentials=(controller.pw_uid, controller.pw_gid)).strip()
    def assert_test(name, condition):
        if not condition:
            raise RuntimeError("FAILED: " + name)
        tests.append(name)
    timers = ("assbox-worker-health.timer", "assbox-worker-boot-retry.timer")
    active_timers = [name for name in timers if w.run(
        [c["tools"]["systemctl"], "show", name, "-p", "ActiveState", "--value"],
        capture=True).strip() == "active"]
    try:
        w.run([c["tools"]["systemctl"], "stop", *timers,
               "assbox-worker-health.service"], timeout=150)
        acceptance = w.run([c["tools"]["systemctl"], "show", "assbox-worker-boot-retry.service",
                            "-p", "ActiveState", "--value"], capture=True).strip()
        if acceptance not in ("inactive", "failed"):
            raise RuntimeError("A boot-acceptance operation is running; do not interrupt its transaction")
        w.artifact_manifest(c, verify_hashes=True)
        w.check(c)
        state = w.run([c["tools"]["systemctl"], "show", "assbox-worker.service", "-p", "MainPID", "--value"], capture=True).strip()
        pid = int(state)
        cmdline = Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")
        assert_test("KVM-only production process", b"kvm" in cmdline and b"-accel" in cmdline)
        status = Path(f"/proc/{pid}/status").read_text()
        assert_test("VMM is not host root", "\nUid:\t0\t" not in status)
        canary.write_text(token); canary.chmod(0o600)
        assert_test("Host-home canary absent in guest", ssh(f"test ! -e {canary} && printf absent") == "absent")
        assert_test("Distinct guest role", ssh("cat /etc/assbox/worker-role") == "execution-worker")
        assert_test("No virtiofs/9p mounts", ssh("findmnt -rn -t 9p,virtiofs || true") == "")
        assert_test("No host management socket", ssh("test ! -e /run/assbox-worker/qmp.sock && printf absent") == "absent")
        assert_test("Provisioning disk has no controller private key", ssh("test ! -e /run/assbox-seed/client_ed25519 && printf absent") == "absent")
        assert_test("Health and agent are separate identities", "assbox-worker-health" in w.health_ssh_args(c))
        assert_test("Health home is immutable/nonpersistent", ssh("getent passwd assbox-health | cut -d: -f6") == "/var/empty")
        assert_test("Health private key absent from provisioning disk", ssh("test ! -e /run/assbox-seed/health_ed25519 && printf absent") == "absent")
        assert_test("Seed permissions survive the production umask and ISO mount",
                    ssh("stat -c '%a' /run/assbox-seed /run/assbox-seed/agent.pub /run/assbox-seed/assbox-health.pub /run/assbox-seed/ssh_host_ed25519_key")
                    == "755\n644\n644\n600")
        # Deliberately alter only a dedicated test file; do not rewrite real shell
        # startup files. Native health identity/ForceCommand policy is also gated.
        assert_test("Artifact command line references a guest init", "init=/nix/store/" in (Path(c["artifact"])/"cmdline").read_text())
        before_boot = ssh("cat /proc/sys/kernel/random/boot_id")
        ssh(f"umask 077; printf '%s' {token} > {guest_file}")
        w.run([c["tools"]["systemctl"], "stop", "assbox-worker.service"], timeout=150)
        stopped = w.run([c["tools"]["systemctl"], "show", "assbox-worker.service", "-p", "Result", "--value"], capture=True).strip()
        assert_test("Bounded graceful stop succeeds without service timeout", stopped == "success")
        w.run([c["tools"]["systemctl"], "start", "assbox-worker.service"], timeout=150)
        w.check(c)
        assert_test("Real guest restart occurred", ssh("cat /proc/sys/kernel/random/boot_id") != before_boot)
        assert_test("Persistent project volume survives", ssh(f"cat {guest_file}") == token)
        assert_test("Host session-side state survives", canary.read_text() == token)
        assert_test("Guest generation matches host-selected image", ssh("cat /assbox-worker-build-id") == c["buildId"])
        print(json.dumps({"passed": tests, "providerTask": "not-tested", "mobileRemote": "not-tested"}, indent=2))
    finally:
        canary.unlink(missing_ok=True)
        try:
            ssh(f"rm -f {guest_file}")
        except Exception:
            pass
        if active_timers:
            w.run([c["tools"]["systemctl"], "start", *active_timers])


if __name__ == "__main__":
    main()
