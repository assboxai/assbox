#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Small, fixed-purpose Assbox worker lifecycle adapter; no shell evaluation.

The public commands read the Nix-generated configuration. Privileged entry points
are called by root-owned systemd units, not exposed through sudo or polkit grants.
"""
from __future__ import annotations

import argparse
import base64
import struct
import fcntl
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import pwd
import re
import selectors
import shlex
import signal
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import time
from typing import Any

MIB = 1024 * 1024
GIB = 1024 * MIB
KVM_GET_API_VERSION = 0xAE00
MAX_REPLY = 65536
HEALTH_PROBE_USER = "assbox-health-probe"
FIXED_DIRS = {
    "dataDir": "/var/lib/assbox-worker-data",
    "controlDir": "/var/lib/assbox-worker-control",
    "identityDir": "/var/lib/assbox-worker-identity",
    "seedDir": "/var/lib/assbox-worker-seed",
    "healthProbeDir": "/var/lib/assbox-worker-health",
    "runDir": "/run/assbox-worker",
}
DENIED = tuple(ipaddress.ip_network(value) for value in (
    "0.0.0.0/8", "10.0.0.0/8", "100.64.0.0/10", "127.0.0.0/8",
    "169.254.0.0/16", "172.16.0.0/12", "192.0.0.0/24", "192.0.2.0/24",
    "192.168.0.0/16", "198.18.0.0/15", "198.51.100.0/24", "203.0.113.0/24",
    "224.0.0.0/4", "240.0.0.0/4",
))


class Refusal(RuntimeError):
    """Configuration or state is unsafe/ambiguous; do not silently repair it."""


def run(argv: list[str], *, capture: bool = False, timeout: int = 60) -> str:
    result = subprocess.run(
        argv, check=True, text=True, timeout=timeout,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
        stdin=subprocess.DEVNULL,
    )
    return result.stdout if capture else ""



def bounded_capture(argv: list[str], *, timeout: float = 10, limit: int = MAX_REPLY,
                    credentials: tuple[int, int] | None = None) -> str:
    """Bound a Linux health subprocess and its inherited pipes, then reap it.

    Do not reap the leader before signalling its group: a descendant can keep
    pipes open after the leader exits, and an unreaped leader reserves its PID.
    """
    if timeout <= 0 or limit <= 0:
        raise Refusal("Health capture requires positive time and output bounds")
    spawn = {}
    if credentials is not None:
        uid, gid = credentials
        if type(uid) is not int or type(gid) is not int or uid <= 0 or gid <= 0:
            raise Refusal("Health transport must use a non-root UID and GID")
        # Popen drops privileges in the child before exec; no Python preexec_fn.
        # Clear supplementary groups and inherited credentials/environment.
        spawn = {"user": uid, "group": gid, "extra_groups": (), "umask": 0o077,
                 "cwd": "/", "env": {"HOME": "/var/empty", "LC_ALL": "C.UTF-8"}}
    previous_term = signal.getsignal(signal.SIGTERM)
    process = None
    cancelled = None

    def terminate(signum, _frame):
        # Recording cancellation cannot interrupt Popen between spawning a
        # child and handing us its handle, or interrupt the cleanup itself.
        nonlocal cancelled
        cancelled = signum

    def check_cancelled():
        if cancelled is not None:
            raise SystemExit(128 + cancelled)

    signal.signal(signal.SIGTERM, terminate)
    output = bytearray()
    total = 0
    deadline = time.monotonic() + timeout
    try:
        process = subprocess.Popen(
            argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, start_new_session=True, close_fds=True, **spawn,
        )
        check_cancelled()
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ, True)
            selector.register(process.stderr, selectors.EVENT_READ, False)
            while selector.get_map():
                check_cancelled()
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise Refusal("Remote health response timed out")
                for key, _ in selector.select(min(remaining, 0.25)):
                    chunk = os.read(key.fileobj.fileno(), 4096)
                    if not chunk:
                        selector.unregister(key.fileobj)
                        continue
                    total += len(chunk)
                    if total > limit:
                        raise Refusal("Remote health response exceeded the size limit")
                    if key.data:
                        output.extend(chunk)
        while True:
            check_cancelled()
            status = os.waitid(os.P_PID, process.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT)
            if status is not None:
                if status.si_code != os.CLD_EXITED or status.si_status != 0:
                    raise Refusal("Remote health command failed")
                return output.decode("utf-8", errors="strict")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise Refusal("Remote health command did not exit before its deadline")
            time.sleep(min(0.02, remaining))
    finally:
        try:
            if process is not None:
                # Always signal the group, including when its leader exited.
                # No poll()/wait() occurs before this point, preventing PID reuse.
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait()
                process.stdout.close()
                process.stderr.close()
        finally:
            signal.signal(signal.SIGTERM, previous_term)
            check_cancelled()


def validate_config(c: dict[str, Any]) -> None:
    if c.get("schema") != 2 or c.get("controller") != "agent" or c.get("vmm") != "assbox-vmm":
        raise Refusal("Unsupported worker configuration identity/schema")
    for key, expected in FIXED_DIRS.items():
        if c.get(key) != expected:
            raise Refusal(f"Unexpected path for {key}")
    if not re.fullmatch(r"/nix/store/[0-9a-df-np-sv-z]{32}-[A-Za-z0-9+._?=-]+", str(c.get("artifact", ""))):
        raise Refusal("artifact must be an immutable store directory")
    if not re.fullmatch(r"[0-9a-f]{64}", str(c.get("buildId", ""))):
        raise Refusal("Invalid expected artifact build identifier")
    if c.get("healthSshConfig") != "/etc/assbox/worker-health-ssh-config":
        raise Refusal("Unexpected health SSH configuration path")
    if c.get("sshConfig") != "/etc/assbox/worker-ssh-config":
        raise Refusal("Unexpected SSH configuration path")
    for key, low, high in (
        ("memoryMiB", 2048, 65536), ("hostReserveMiB", 1024, 16384),
        ("vcpus", 1, 32), ("stateGiB", 8, 2048),
    ):
        if type(c.get(key)) is not int or not low <= c[key] <= high:
            raise Refusal(f"Invalid {key}")
    if c.get("machine") not in ("q35", "virt,gic-version=host"):
        raise Refusal("Unsupported machine type")
    names = [c["interface"], *c["uplinkInterfaces"]]
    if any(not re.fullmatch(r"[a-zA-Z0-9_-]{1,15}", n) for n in names):
        raise Refusal("Invalid interface name")
    if c["interface"] in c["uplinkInterfaces"]:
        raise Refusal("The worker TAP cannot also be an uplink")
    if c["egress"] not in ("normal", "internet", "offline"):
        raise Refusal("Invalid egress policy")
    if c["egress"] != "offline" and not c["uplinkInterfaces"]:
        raise Refusal("Internet mode requires explicitly selected uplinks")
    if c["egress"] == "offline" and (c["uplinkInterfaces"] or c["nameservers"]):
        raise Refusal("Offline mode must not select uplinks or resolvers")
    host = ipaddress.IPv4Address(c["hostAddress"])
    guest = ipaddress.IPv4Address(c["guestAddress"])
    network = ipaddress.IPv4Network(f"{host}/30", strict=False)
    if list(network.hosts()) != [host, guest] or not network.subnet_of(ipaddress.ip_network("10.0.0.0/8")):
        raise Refusal("Use the controller and worker addresses, in that order, in a dedicated 10/8 /30 subnet")
    extras = [ipaddress.IPv4Network(n, strict=True) for n in c["additionalDeniedCidrs"]]
    lan = {ipaddress.ip_network(n) for n in ("10.0.0.0/8", "100.64.0.0/10", "172.16.0.0/12", "192.168.0.0/16")}
    denied = tuple(n for n in DENIED if c["egress"] != "normal" or n not in lan)
    for resolver in c["nameservers"]:
        ip = ipaddress.IPv4Address(resolver)
        if ip in network or any(ip in prefix for prefix in (*denied, *extras)):
            raise Refusal("DNS resolver is blocked by the guest egress policy")
    if c["egress"] != "offline" and not c["nameservers"]:
        raise Refusal("Online mode requires at least one permitted resolver")
    for path in c["tools"].values():
        if not str(path).startswith("/nix/store/") or "\n" in path:
            raise Refusal("Tools must resolve from the immutable Nix tool closure")


def artifact_manifest(c: dict[str, Any], *, verify_hashes: bool = False) -> dict[str, Any]:
    """Validate a sealed artifact. Paths inside its blobs name the guest store."""
    root = Path(c["artifact"])
    manifest_file = root / "manifest.json"
    info = manifest_file.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_size > 16384:
        raise Refusal("Invalid artifact manifest")
    manifest = json.loads(manifest_file.read_text())
    if not isinstance(manifest, dict) or manifest.get("schema") != 1 or manifest.get("buildId") != c["buildId"]:
        raise Refusal("Artifact build identifier does not match the controller generation")
    size = manifest.get("rootVirtualBytes")
    if type(size) is not int or not 4 * GIB <= size <= 2 * 1024 * GIB:
        raise Refusal("Invalid artifact virtual disk size")
    expected = {"system.qcow2", "kernel", "initrd", "cmdline"}
    if not isinstance(manifest.get("files"), dict) or set(manifest["files"]) != expected:
        raise Refusal("Unexpected artifact file set")
    for name, metadata in manifest["files"].items():
        path = root / name
        info = path.lstat()
        if not isinstance(metadata, dict) or not stat.S_ISREG(info.st_mode) or info.st_size != metadata.get("bytes"):
            raise Refusal("Artifact contains a symlink, missing file or size mismatch")
        if not re.fullmatch(r"[0-9a-f]{64}", str(metadata.get("sha256", ""))):
            raise Refusal("Invalid artifact checksum")
        if name == "cmdline" and info.st_size > 16384:
            raise Refusal("Oversize artifact command line")
        if verify_hashes:
            with path.open("rb") as stream:
                digest = hashlib.file_digest(stream, "sha256").hexdigest()
            if digest != metadata["sha256"]:
                raise Refusal("Artifact checksum verification failed")
    return manifest


def load_config(candidate: str | None = None) -> dict[str, Any]:
    path = Path(candidate or os.environ.get("ASSBOX_WORKER_CONFIG", "/etc/assbox/worker-runtime.json"))
    # Candidate admission accepts only an immutable, root-owned Nix store file.
    # Runtime operations always use the active system's generated configuration.
    if candidate is not None:
        resolved = path.resolve(strict=True)
        if not resolved.is_relative_to("/nix/store"):
            raise Refusal("Candidate configuration must be a store file")
        info = resolved.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
            raise Refusal("Unsafe candidate configuration")
        path = resolved
    elif path != Path("/etc/assbox/worker-runtime.json"):
        raise Refusal("Only the generated system configuration is accepted")
    c = json.loads(path.read_text())
    validate_config(c)
    return c


def require_user(name: str) -> None:
    if pwd.getpwuid(os.geteuid()).pw_name != name:
        raise Refusal(f"This operation must run as {name}")


def fsync_dir(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def require_regular(path: Path, *, owner: int | None = None) -> os.stat_result:
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise Refusal(f"Expected a single-link regular file: {path.name}")
    if owner is not None and info.st_uid != owner:
        raise Refusal(f"Unexpected file owner: {path.name}")
    return info


def check_private_dir(path: Path, owner: int, group: int, mode: int) -> None:
    info = path.lstat()
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != owner
            or info.st_gid != group or stat.S_IMODE(info.st_mode) != mode):
        raise Refusal(f"Unsafe directory metadata: {path.name}; inspect rather than auto-repair")


def private_dir(path: Path, owner: int, group: int, mode: int) -> None:
    try:
        path.mkdir(mode=mode)
    except FileExistsError:
        check_private_dir(path, owner, group, mode)
        return
    os.chown(path, owner, group, follow_symlinks=False)
    os.chmod(path, mode, follow_symlinks=False)
    fsync_dir(path.parent)


def check_data_dir(path: Path, owner: int) -> None:
    """Inspect existing worker state without normalizing ownership/permissions."""
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != owner or stat.S_IMODE(info.st_mode) != 0o700:
        raise Refusal("Unsafe worker data directory; inspect ownership and permissions, do not auto-repair")


def ensure_data_dir(path: Path, owner: int, group: int) -> None:
    """Root provisions a new directory only; existing worker state is untouched.

    The fixed parent is root-controlled. Do not use a tmpfiles 'd' rule here:
    it would chown/chmod existing state before the refusal checks can see it.
    An interrupted first creation remains visible for operator inspection.
    """
    if owner <= 0 or group <= 0:
        raise Refusal("Worker state must belong to an unprivileged VMM identity")
    try:
        path.mkdir(mode=0o700)
    except FileExistsError:
        check_data_dir(path, owner)
        return
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        os.fchown(fd, owner, group)
        os.fchmod(fd, 0o700)
        os.fsync(fd)
    finally:
        os.close(fd)
    fsync_dir(path.parent)


def atomic_write(path: Path, data: bytes, mode: int = 0o600, *, group: int | None = None) -> None:
    """Atomic replacement in a caller-verified directory; no target symlink following."""
    if path.exists() or path.is_symlink():
        require_regular(path)
    fd, temporary = tempfile.mkstemp(prefix=".assbox-", dir=path.parent)
    tmp = Path(temporary)
    try:
        os.fchmod(fd, mode)
        if group is not None:
            os.fchown(fd, -1, group)
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
        fsync_dir(path.parent)
    finally:
        tmp.unlink(missing_ok=True)


def canonical_ed25519_public(public: str) -> str:
    words = public.split()
    if len(words) < 2 or words[0] != 'ssh-ed25519' or len(public) > 4096:
        raise Refusal("Unexpected SSH public key format")
    try:
        blob = base64.b64decode(words[1], validate=True)
    except ValueError as error:
        raise Refusal("Invalid SSH key encoding") from error
    if len(blob) != 51 or blob[:19] != b'\x00\x00\x00\x0bssh-ed25519\x00\x00\x00\x20':
        raise Refusal("SSH key must encode exactly one 32-byte Ed25519 public key")
    return 'ssh-ed25519 ' + base64.b64encode(blob).decode()


def key_identity(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid,
            info.st_nlink, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def key_public(path: Path, keygen: str, *, owner: int) -> str:
    info = require_regular(path, owner=owner)
    if stat.S_IMODE(info.st_mode) != 0o600 or info.st_gid != pwd.getpwuid(owner).pw_gid or not 1 <= info.st_size <= 16384:
        raise Refusal("SSH private key must be a bounded single-owner 0600 file with its owner's primary group")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    with os.fdopen(fd, 'rb') as stream:
        if key_identity(os.fstat(stream.fileno())) != key_identity(info):
            raise Refusal("SSH private key changed while opening it")
        data = stream.read(16385)
    lines = data.splitlines()
    if len(lines) < 3 or lines[0] != b'-----BEGIN OPENSSH PRIVATE KEY-----' or lines[-1] != b'-----END OPENSSH PRIVATE KEY-----':
        raise Refusal("Expected OpenSSH private key format")
    try:
        raw = base64.b64decode(b''.join(lines[1:-1]), validate=True)
    except ValueError as error:
        raise Refusal("Malformed SSH private key encoding") from error
    if not raw.startswith(b'openssh-key-v1\x00'):
        raise Refusal("Unsupported SSH private key version")
    offset = 15
    def field():
        nonlocal offset
        if offset + 4 > len(raw): raise Refusal("Truncated SSH private key")
        size = struct.unpack('>I', raw[offset:offset+4])[0]; offset += 4
        if size > 16384 or offset + size > len(raw): raise Refusal("Excessive SSH private key field")
        value = raw[offset:offset+size]; offset += size
        return value
    if field() != b'none' or field() != b'none' or field() != b'':
        raise Refusal("Worker identity must be unencrypted and noninteractive")
    if raw[offset:offset+4] != b'\x00\x00\x00\x01': raise Refusal("Worker identity must contain exactly one key")
    offset += 4
    expected = canonical_ed25519_public('ssh-ed25519 ' + base64.b64encode(field()).decode())
    # Parse a private copy, never reopen a mutable execution-owned pathname in
    # the privileged parser. No retained key is repaired or regenerated.
    with tempfile.TemporaryDirectory(prefix='assbox-key-') as directory:
        copy = Path(directory) / 'identity'
        copy.write_bytes(data); copy.chmod(0o600)
        parsed = bounded_capture([keygen, '-y', '-P', '', '-f', str(copy)], timeout=5, limit=4096).strip()
    if canonical_ed25519_public(parsed) != expected or key_identity(require_regular(path, owner=owner)) != key_identity(info):
        raise Refusal("SSH private identity does not match its encoded public key or changed during validation")
    return expected


def ensure_key(path: Path, keygen: str, *, owner: int = 0, group: int | None = None) -> str:
    """Create a first-provisioning key only after the caller's complete preflight."""
    if not path.exists() and not path.is_symlink():
        with tempfile.TemporaryDirectory(prefix=".new-key-", dir=path.parent) as d:
            key = Path(d) / "key"
            run([keygen, "-q", "-t", "ed25519", "-N", "", "-C", "assbox-worker", "-f", str(key)])
            atomic_write(path, key.read_bytes(), 0o600, group=group)
            os.chown(path, owner, group if group is not None else 0)
    return key_public(path, keygen, owner=owner)


def existing_state(c: dict[str, Any], owner: int) -> bool:
    """Reject partial/lost state before creating keys, directories or disk files."""
    data = Path(c["dataDir"])
    if not data.exists() and not data.is_symlink():
        return False
    check_data_dir(data, owner)
    home, overlay, partial = (data / name for name in ("home.raw", "root.qcow2", "home.raw.new"))
    if partial.exists() or partial.is_symlink():
        raise Refusal("Interrupted worker state creation requires inspection")
    present = home.exists() or home.is_symlink()
    if present:
        state = require_regular(home, owner=owner)
        if state.st_size != c["stateGiB"] * GIB or stat.S_IMODE(state.st_mode) != 0o600:
            raise Refusal("Existing worker state size/permissions differ; no automatic resize or repair")
    if overlay.exists() or overlay.is_symlink():
        if not present:
            raise Refusal("Worker home is missing but a root overlay remains; recover preserved state explicitly")
        info = require_regular(overlay, owner=owner)
        if stat.S_IMODE(info.st_mode) != 0o600:
            raise Refusal("Unsafe worker root overlay permissions")
    return present


def transport_preflight(c: dict[str, Any], *, preserved: bool) -> None:
    """Canonical identity damage is never repaired by generating replacements.

    Validate every existing key before provisioning anything, including on an
    interrupted first setup. Only derived probe keys, known_hosts and seed files
    may later be rebuilt from this canonical material.
    """
    controller = pwd.getpwnam(c["controller"])
    directories = [(Path(c["controlDir"]), 0, controller.pw_gid, 0o750),
                   (Path(c["identityDir"]), 0, 0, 0o700)]
    for path, owner, group, mode in directories:
        if preserved or path.exists() or path.is_symlink():
            check_private_dir(path, owner, group, mode)
    keys = [(Path(c["controlDir"]) / "client_ed25519", controller.pw_uid),
            (Path(c["identityDir"]) / "ssh_host_ed25519_key", 0),
            (Path(c["identityDir"]) / "health_ed25519", 0)]
    for path, owner in keys:
        if preserved or path.exists() or path.is_symlink():
            key_public(path, c["tools"]["sshKeygen"], owner=owner)


def seed_contents(root: Path, client_public: str, health_public: str, host_key: bytes) -> None:
    # sshd reads authorized_keys as the guest user; the ISO root must
    # be traversable. Only the guest SSH host private key is mode 0600.
    root.mkdir(mode=0o755)
    # mkdir's requested mode is filtered by the service's UMask=0077.
    # Set the final mode explicitly before Rock Ridge captures it.
    root.chmod(0o755)
    (root / "agent.pub").write_text(client_public + "\n")
    (root / "agent.pub").chmod(0o644)
    (root / "assbox-health.pub").write_text("restrict " + health_public + "\n")
    (root / "assbox-health.pub").chmod(0o644)
    private = root / "ssh_host_ed25519_key"
    private.write_bytes(host_key)
    private.chmod(0o600)


def provision(c: dict[str, Any]) -> None:
    require_user("root")
    uid = pwd.getpwnam(c["controller"])
    vmm = pwd.getpwnam(c["vmm"])
    preserved = existing_state(c, vmm.pw_uid)
    transport_preflight(c, preserved=preserved)
    ensure_data_dir(Path(c["dataDir"]), vmm.pw_uid, vmm.pw_gid)
    control, identity, seed = (Path(c[k]) for k in ("controlDir", "identityDir", "seedDir"))
    private_dir(control, 0, uid.pw_gid, 0o750)
    private_dir(identity, 0, 0, 0o700)
    private_dir(seed, 0, vmm.pw_gid, 0o750)
    client_public = ensure_key(control / "client_ed25519", c["tools"]["sshKeygen"], owner=uid.pw_uid, group=uid.pw_gid)
    guest_public = ensure_key(identity / "ssh_host_ed25519_key", c["tools"]["sshKeygen"])
    health_public = ensure_key(identity / "health_ed25519", c["tools"]["sshKeygen"])
    probe = pwd.getpwnam(HEALTH_PROBE_USER)
    if probe.pw_uid == 0 or probe.pw_gid == 0:
        raise Refusal("Health probe identity must be unprivileged")
    probe_dir = Path(c["healthProbeDir"])
    private_dir(probe_dir, 0, probe.pw_gid, 0o750)
    # Retain the dedicated identity; do not rotate it merely to change the
    # network-facing client's Unix identity. Never copy Desktop credentials.
    atomic_write(probe_dir / "health_ed25519", (identity / "health_ed25519").read_bytes())
    os.chown(probe_dir / "health_ed25519", probe.pw_uid, probe.pw_gid)
    atomic_write(probe_dir / "known_hosts", f"assbox-worker {guest_public}\n".encode(),
                 0o640, group=probe.pw_gid)
    atomic_write(control / "known_hosts", f"assbox-worker {guest_public}\n".encode(), 0o640, group=uid.pw_gid)
    # Build the read-only provisioning disk only from controller-generated identities.
    # It does not contain the controller's private key or any provider credential.
    with tempfile.TemporaryDirectory(prefix=".seed-", dir=identity) as d:
        root = Path(d) / "contents"
        seed_contents(root, client_public, health_public, (identity / "ssh_host_ed25519_key").read_bytes())
        image = Path(d) / "identity.iso"
        # Rock Ridge (-R) preserves private file permissions; never use -r here.
        run([c["tools"]["xorriso"], "-as", "mkisofs", "-quiet", "-R", "-V", "ASSBOX_SEED", "-o", str(image), str(root)])
        atomic_write(seed / "identity.iso", image.read_bytes(), 0o440, group=vmm.pw_gid)
    print("Worker SSH identities provisioned; no OpenAI credentials copied.")


def validate_kvm_and_memory(c: dict[str, Any]) -> None:
    try:
        fd = os.open("/dev/kvm", os.O_RDWR | os.O_CLOEXEC)
        try:
            if fcntl.ioctl(fd, KVM_GET_API_VERSION, 0) != 12:
                raise Refusal("Unsupported KVM API")
        finally:
            os.close(fd)
    except OSError as exc:
        raise Refusal("KVM is unavailable; controller execution and software emulation are not fallbacks") from exc
    memory = re.search(r"^MemTotal:\s+(\d+) kB$", Path("/proc/meminfo").read_text(), re.M)
    if not memory or int(memory[1]) * 1024 < (c["memoryMiB"] + c["hostReserveMiB"] + 1024) * MIB:
        raise Refusal("Insufficient physical RAM for worker, QEMU overhead and controller reserve")


def create_state_disk(path: Path, size: int, mkfs: str) -> None:
    if path.exists() or path.is_symlink():
        info = require_regular(path, owner=os.geteuid())
        if info.st_size != size or stat.S_IMODE(info.st_mode) != 0o600:
            raise Refusal("Existing worker state size/permissions differ; never resize or format it automatically")
        return
    temporary = path.with_name(path.name + ".new")
    # An interrupted sparse creation is not a valid state disk; leave it for explicit
    # inspection rather than guessing whether data should be discarded.
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        os.ftruncate(fd, size)
        os.fsync(fd)
    finally:
        os.close(fd)
    run([mkfs, "-q", "-F", "-m", "0", "-E", "nodiscard", "-L", "ASSBOX_WORK", str(temporary)], timeout=300)
    with temporary.open("rb") as stream:
        os.fsync(stream.fileno())
    os.rename(temporary, path)
    fsync_dir(path.parent)


def disk_admission(c: dict[str, Any], manifest: dict[str, Any], *, owner: int) -> dict[str, int]:
    """Read-only admission on the state filesystem, including sparse allocation.

    A measurement is not a reservation. Recheck again at actual worker start.
    Never mount, parse or repair guest-controlled filesystem contents here.
    """
    data = Path(c["dataDir"])
    if data.exists() or data.is_symlink():
        check_data_dir(data, owner)
        filesystem = data
    else:
        filesystem = data.parent
    home, root = data / "home.raw", data / "root.qcow2"
    present = existing_state(c, owner)
    state_needed = c["stateGiB"] * GIB
    if present:
        state = require_regular(home, owner=owner)
        state_needed = max(0, state_needed - state.st_blocks * 512)
    reclaim = require_regular(root, owner=owner).st_blocks * 512 if root.exists() else 0
    usage = shutil.disk_usage(filesystem)
    # Sizing leaves max(32 GiB, 20%) for controller growth. It is consumable:
    # keep only this emergency floor at admission, including on later boots.
    reserve = 8 * GIB
    needed = manifest["rootVirtualBytes"] + reserve + state_needed
    free = usage.free
    if free + reclaim < needed:
        raise Refusal("Insufficient disk space for persistent state and a fully dirtied root; no state disk was reformatted")
    return {"requiredBytes": needed, "freeBytes": free, "reclaimableRootBytes": reclaim}


def admit(c: dict[str, Any]) -> None:
    """Post-build/pre-publication gate for a candidate, not its running guest."""
    require_user("root")
    # Validate image metadata from the immutable candidate, not /etc or an old VM.
    manifest = artifact_manifest(c)
    try:
        owner = pwd.getpwnam(c["vmm"]).pw_uid
        if owner <= 0:
            raise Refusal("Worker state must belong to an unprivileged VMM identity")
    except KeyError:
        # First enable from an older/no-Assbox system may precede identity
        # activation. A preserved disk never authorizes guessing its owner.
        if Path(c["dataDir"]).exists() or Path(c["dataDir"]).is_symlink():
            raise Refusal("Existing worker state has no known VMM owner; restore the declared infrastructure identities before re-enabling")
        owner = -1
    admission = disk_admission(c, manifest, owner=owner)
    transport_preflight(c, preserved=existing_state(c, owner))
    print(json.dumps({"admission": "accepted", **admission}))


def prepare(c: dict[str, Any]) -> None:
    require_user(c["vmm"])
    validate_kvm_and_memory(c)
    data = Path(c["dataDir"])
    check_data_dir(data, os.geteuid())
    manifest = artifact_manifest(c)
    disk_admission(c, manifest, owner=os.geteuid())
    root = data / "root.qcow2"
    create_state_disk(data / "home.raw", c["stateGiB"] * GIB, c["tools"]["mkfs"])
    if root.exists():
        root.unlink()
    base = str(Path(c["artifact"]) / "system.qcow2")
    run([c["tools"]["qemuImg"], "create", "-q", "-f", "qcow2", "-F", "qcow2", "-b", base, str(root)])
    root.chmod(0o600)
    fsync_dir(data)
    print("Worker prepared: fresh system overlay, retained /home, KVM required.")


def qemu_args(c: dict[str, Any]) -> list[str]:
    data, run_dir = Path(c["dataDir"]), Path(c["runDir"])
    artifact_manifest(c)
    artifact = Path(c["artifact"])
    command_line = (artifact / "cmdline").read_text()
    if not command_line or "\n" in command_line or "\x00" in command_line:
        raise Refusal("Invalid artifact kernel command line")
    args = [
        c["tools"]["qemu"], "-name", "assbox-worker", "-machine", c["machine"],
        "-accel", "kvm", "-cpu", "host", "-smp", str(c["vcpus"]), "-m", str(c["memoryMiB"]),
        "-nodefaults", "-no-user-config", "-display", "none", "-serial", "null", "-monitor", "none",
        "-no-reboot", "-kernel", str(artifact / "kernel"), "-initrd", str(artifact / "initrd"),
        "-append", command_line,
        "-drive", f"file={data}/root.qcow2,if=none,id=root,format=qcow2,cache=none,werror=stop,rerror=stop",
        "-device", f"virtio-blk-pci,drive=root",
        "-drive", f"file={data}/home.raw,if=none,id=home,format=raw,cache=none,werror=stop,rerror=stop",
        "-device", f"virtio-blk-pci,drive=home",
        "-drive", f"file={c['seedDir']}/identity.iso,if=none,id=seed,format=raw,readonly=on",
        "-device", f"virtio-blk-pci,drive=seed",
        "-netdev", f"tap,id=worker,ifname={c['interface']},script=no,downscript=no",
        "-device", f"virtio-net-pci,netdev=worker,mac=02:ab:00:00:00:02",
        "-object", "rng-random,filename=/dev/urandom,id=rng0",
        "-device", f"virtio-rng-pci,rng=rng0",
        "-qmp", f"unix:{run_dir}/qmp.sock,server=on,wait=off",
        "-sandbox", "on,obsolete=deny,elevateprivileges=deny,spawn=deny,resourcecontrol=deny",
    ]
    return args


def network_up(c: dict[str, Any]) -> None:
    require_user("root")
    ip = c["tools"]["ip"]
    links = json.loads(run([ip, "-j", "link", "show"], capture=True))
    if any(row["ifname"] == c["interface"] for row in links):
        raise Refusal("Worker interface already exists; refuse to adopt an unknown network device")
    wanted = ipaddress.IPv4Network(f"{c['hostAddress']}/30", strict=False)
    routes = json.loads(run([ip, "-j", "-4", "route", "show", "table", "all"], capture=True))
    for row in routes:
        destination = row.get("dst", "default")
        if destination != "default" and ipaddress.IPv4Network(destination, strict=False).overlaps(wanted):
            raise Refusal("Worker subnet overlaps an existing controller route; choose another /30")
    # Firewall unit ordering is also enforced by systemd. Missing table is fatal.
    run([c["tools"]["nft"], "list", "table", "inet", "assbox-worker"], capture=True)
    run([ip, "tuntap", "add", "dev", c["interface"], "mode", "tap", "user", c["vmm"]])
    try:
        run([ip, "address", "add", f"{c['hostAddress']}/30", "dev", c["interface"]])
        run([ip, "link", "set", "dev", c["interface"], "up"])
        # Disable IPv6 on this dedicated link, including host link-local services.
        ipv6 = Path(f"/proc/sys/net/ipv6/conf/{c['interface']}/disable_ipv6")
        if ipv6.exists():
            ipv6.write_text("1\n")
    except Exception:
        run([ip, "link", "delete", "dev", c["interface"]])
        raise


def network_down(c: dict[str, Any]) -> None:
    require_user("root")
    run([c["tools"]["ip"], "link", "delete", "dev", c["interface"]])


def qmp_powerdown(c: dict[str, Any]) -> None:
    require_user(c["vmm"])
    path = str(Path(c["runDir"]) / "qmp.sock")
    if not Path(path).exists():
        return
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.settimeout(5)
        sock.connect(path)
        stream = sock.makefile("rwb", buffering=0)
        greeting = stream.readline(MAX_REPLY + 1)
        if len(greeting) > MAX_REPLY or "QMP" not in json.loads(greeting):
            raise Refusal("Invalid QMP greeting")
        commands = ("qmp_capabilities", "system_powerdown")
        for command in commands:
            stream.write((json.dumps({"execute": command}) + "\n").encode())
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                response = stream.readline(MAX_REPLY + 1)
                if not response or len(response) > MAX_REPLY:
                    raise Refusal("Invalid QMP response")
                item = json.loads(response)
                if "error" in item:
                    raise Refusal("QMP refused the shutdown command")
                if "return" in item:
                    break
            else:
                raise Refusal("QMP acknowledgement timeout")
        # Wait for process exit, not merely command acknowledgement.
        sock.settimeout(1)
        deadline = time.monotonic() + 80
        while time.monotonic() < deadline:
            try:
                if sock.recv(MAX_REPLY) == b"":
                    return
            except socket.timeout:
                continue
        raise Refusal("Guest did not shut down; systemd will enforce its bounded stop timeout")


def ssh_args(c: dict[str, Any], *, tty: bool = False) -> list[str]:
    args = [c["tools"]["ssh"], "-F", c["sshConfig"], "-o", "BatchMode=yes", "-o", "ConnectTimeout=5"]
    if tty:
        args.append("-t")
    return args + ["assbox-worker"]


def merge_ssh_config(existing: str, managed: str) -> str:
    begin = "# BEGIN ASSBOX WORKER (managed)\n"
    end = "# END ASSBOX WORKER\n"
    if "\x00" in existing or "\x00" in managed:
        raise Refusal("Invalid SSH configuration bytes")
    if existing.count(begin) != existing.count(end) or existing.count(begin) > 1:
        raise Refusal("Ambiguous managed SSH block")
    rest = existing
    if begin in existing:
        start, stop = existing.index(begin), existing.index(end)
        if stop < start:
            raise Refusal("Invalid managed SSH block order")
        rest = existing[:start] + existing[stop + len(end):]
    for line in rest.splitlines():
        # OpenSSH accepts both whitespace and '=' separators and quoted values.
        # Only inspect Host declarations; never evaluate Includes or Match exec.
        declaration = re.match(r"^\s*Host(?:\s+|=)(.*)$", line, re.I)
        if declaration:
            try:
                names = shlex.split(declaration[1].lstrip("= \t"), comments=True)
            except ValueError as exc:
                raise Refusal("Invalid unmanaged SSH Host declaration") from exc
            if any(name.lower() == "assbox-worker" for name in names):
                raise Refusal("An unmanaged assbox-worker SSH alias already exists")
    # First value wins for most directives, but IdentityFile and forwarding
    # lists can accumulate; this is not a sandbox for arbitrary user Includes.
    # Restore global scope before the pre-existing text: otherwise its leading
    # defaults would accidentally apply only to assbox-worker.
    return begin + managed.rstrip() + "\nHost *\n" + end + rest


def parse_ssh_settings(output: str) -> dict[str, list[str]]:
    fields: dict[str, list[str]] = {}
    for line in output.splitlines():
        key, separator, value = line.partition(" ")
        if not separator or not key or not value:
            raise Refusal("Invalid effective SSH configuration")
        fields.setdefault(key, []).append(value)
    return fields


def validate_ssh_settings(c: dict[str, Any], fields: dict[str, list[str]], *, health: bool = False) -> None:
    identity_dir = c["healthProbeDir"] if health else c["controlDir"]
    expected = {
        "hostname": c["guestAddress"], "port": "22",
        "user": "assbox-health" if health else "agent",
        "identityfile": str(Path(identity_dir) / ("health_ed25519" if health else "client_ed25519")),
        "globalknownhostsfile": str(Path(identity_dir) / "known_hosts"),
        "userknownhostsfile": "/dev/null", "hostkeyalias": "assbox-worker",
        "identitiesonly": "yes", "identityagent": "none", "forwardagent": "no",
        "forwardx11": "no", "forwardx11trusted": "no", "permitlocalcommand": "no",
        "controlmaster": "false", "canonicalizehostname": "false",
        "passwordauthentication": "no", "kbdinteractiveauthentication": "no",
        "preferredauthentications": "publickey", "pubkeyauthentication": "true",
        "updatehostkeys": "false", "tunnel": "false",
    }
    for key, value in expected.items():
        if fields.get(key) != [value]:
            raise Refusal(f"Unsafe effective worker SSH setting: {key}; scope other SSH settings away from assbox-worker")
    if fields.get("stricthostkeychecking") not in (["true"], ["yes"]):
        raise Refusal("Worker SSH host-key checking must be strict")
    for key in ("proxycommand", "proxyjump", "remotecommand", "controlpath", "certificatefile"):
        if fields.get(key, ["none"]) != ["none"]:
            raise Refusal(f"Unexpected worker SSH override: {key}")
    for key in ("localforward", "remoteforward", "dynamicforward"):
        if key in fields:
            raise Refusal(f"Automatic SSH forwarding is not allowed for the worker alias: {key}")


def verify_ssh_config(c: dict[str, Any], path: Path | None = None) -> None:
    # ssh -G may evaluate user Match exec rules. Never run them as root.
    controller = pwd.getpwnam(c["controller"])
    if controller.pw_uid <= 0 or controller.pw_gid <= 0:
        raise Refusal("SSH configuration must be evaluated as the unprivileged controller")
    credentials = (controller.pw_uid, controller.pw_gid) if os.geteuid() == 0 else None
    if credentials is None:
        require_user(c["controller"])
    argv = [c["tools"]["ssh"], "-G"]
    if path is not None:
        argv += ["-F", str(path)]
    output = bounded_capture(argv + ["assbox-worker"], credentials=credentials)
    validate_ssh_settings(c, parse_ssh_settings(output))


def setup_ssh(c: dict[str, Any]) -> None:
    require_user(c["controller"])
    home = Path(pwd.getpwnam(c["controller"]).pw_dir)
    directory = home / ".ssh"
    private_dir(directory, os.geteuid(), os.getegid(), 0o700)
    path = directory / "config"
    if path.exists() or path.is_symlink():
        require_regular(path, owner=os.geteuid())
        existing = path.read_text()
    else:
        existing = ""
    managed = Path(c["sshConfig"]).read_text()
    result = merge_ssh_config(existing, managed)
    # -F suppresses the system config. Include it explicitly in this temporary
    # preflight to match normal Desktop/OpenSSH discovery before publication.
    system_config = Path("/etc/ssh/ssh_config")
    effective = result
    if system_config.exists():
        effective += "\nHost *\nInclude /etc/ssh/ssh_config\n"
    with tempfile.NamedTemporaryFile(mode="w", dir=directory, prefix=".assbox-check-") as temporary:
        temporary.write(effective)
        temporary.flush()
        verify_ssh_config(c, Path(temporary.name))
    if existing != result:
        atomic_write(path, result.encode())
    print("SSH alias installed. In Desktop, select assbox-worker and a worker project folder.")


def health_ssh_args(c: dict[str, Any]) -> list[str]:
    return [c["tools"]["ssh"], "-F", c["healthSshConfig"], "-o", "BatchMode=yes",
            "-o", "ConnectTimeout=5", "-o", "LogLevel=ERROR", "assbox-worker-health", "health"]


def health_matches(c: dict[str, Any], reply: str) -> bool:
    return reply == "ASSBOX-WORKER-HEALTH/1\n" + c["buildId"] + "\n"


def check(c: dict[str, Any]) -> None:
    # A guest assertion of identity is a compatibility/liveness check, not
    # attestation. The controller-selected image path is the authoritative build input.
    require_user("root")
    artifact_manifest(c)
    probe = pwd.getpwnam(HEALTH_PROBE_USER)
    if probe.pw_uid == 0 or probe.pw_gid == 0:
        raise Refusal("Health transport must not run as root")
    credentials = (probe.pw_uid, probe.pw_gid)
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        try:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            reply = bounded_capture(health_ssh_args(c), timeout=min(10, remaining), credentials=credentials)
            if health_matches(c, reply):
                # Stable diagnostic keys: guestGeneration refers to the worker;
                # hostLocalTools refers to controller-tool enforcement by this
                # helper, not to which tools a remote Desktop session can call.
                print(json.dumps({"transport": "ready", "guestGeneration": "matches", "providerAuth": "not-checked", "hostLocalTools": "not-enforced"}))
                return
        except (Refusal, subprocess.SubprocessError, OSError, UnicodeError):
            pass
        remaining = deadline - time.monotonic()
        if remaining > 0:
            time.sleep(min(3, remaining))
    raise Refusal("Worker SSH/generation check failed; local execution is not a fallback")


def status(c: dict[str, Any]) -> None:
    state = run([c["tools"]["systemctl"], "show", "assbox-worker.service", "-p", "ActiveState", "-p", "SubState"], capture=True)
    print(state.strip())
    print("ExpectedBuild=" + c["buildId"])
    print("Artifact=" + c["artifact"])
    print("Machine=" + c["machine"])
    print("GuestComponents=" + ",".join(c["selectedComponents"]))
    print("Egress=" + c["egress"])
    print("ProviderAuth=not-checked\nHostLocalTools=not-enforced")


def doctor(c: dict[str, Any]) -> None:
    status(c)
    artifact_manifest(c, verify_hashes=True)
    print("ArtifactChecksums=verified")
    verify_ssh_config(c)
    print("SshAliasPolicy=verified")
    # Deliberately do not read a provider auth file or the Desktop profile.
    run([c["tools"]["systemctl"], "--no-pager", "--failed"])
    if os.geteuid() == 0:
        check(c)
    else:
        print("TransportHealth=run sudo assbox worker check for the root-only probe")
    print("Worker-to-controller/private-prefix policy is direct isolation, not an Internet exfiltration block.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--configuration", help="immutable candidate runtime; admissible only with admit")
    parser.add_argument("command", choices=[
        "status", "doctor", "check", "admit", "setup-ssh", "login", "shell", "stop", "start",
        "internal-provision", "internal-network-up", "internal-network-down",
        "internal-prepare", "internal-run", "internal-powerdown",
    ])
    args = parser.parse_args()
    try:
        if args.configuration is not None and args.command != "admit":
            raise Refusal("Candidate configuration is only valid for read-only admission")
        c = load_config(args.configuration) if args.configuration is not None else load_config()
        if args.command in ("start", "stop"):
            require_user("root")
            if args.command == "stop":
                # Pause new acceptance attempts, but do not terminate an engine
                # that may hold a durable maintenance/cleanup transaction.
                run([c["tools"]["systemctl"], "stop", "assbox-worker-health.timer", "assbox-worker-boot-retry.timer",
                     "assbox-worker-health.service", "assbox-worker.service"], timeout=150)
            else:
                run([c["tools"]["systemctl"], "start", "assbox-worker.service", "assbox-worker-health.timer", "assbox-worker-boot-retry.timer"])
        elif args.command in ("login", "shell"):
            require_user(c["controller"])
            if args.command == "login" and "codex" not in c["selectedComponents"]:
                raise Refusal("Codex is not selected in this worker")
            argv = ssh_args(c, tty=True)
            if args.command == "login":
                argv.append("umask 077; codex login --device-auth")
            os.execv(argv[0], argv)
        elif args.command == "internal-run":
            require_user(c["vmm"])
            argv = qemu_args(c)
            os.execv(argv[0], argv)
        else:
            actions = {
                "status": status, "doctor": doctor, "check": check, "admit": admit, "setup-ssh": setup_ssh,
                "internal-provision": provision, "internal-network-up": network_up,
                "internal-network-down": network_down, "internal-prepare": prepare,
                "internal-powerdown": qmp_powerdown,
            }
            actions[args.command](c)
        return 0
    except (Refusal, OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
        # Do not print provider responses, key contents or subprocess stderr.
        print(f"assbox-worker: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
