# Security model

Assbox separates a passworded administrator from a locked, unprivileged agent.
Agent workloads can access their own files and execute ordinary user commands.
They are not trusted with sudo, raw disks, the NetworkManager administration group,
privileged container groups or Nix trusted-user access. Nix sandboxing, signed
substitutes and an explicit cache configuration remain enabled. APIs supplied by
headless application profiles bind to loopback, with authentication configured
through upstream onboarding.

This is not a sandbox against all malicious code. The agent's credentials and
workspace are in scope for its processes. X11 clients share a display security
boundary. USB identity is not authenticated. Physical access, stolen unencrypted
storage, malicious firmware/kernel/drivers, compromised root and upstream supply
chain compromise are not solved by the CLI. Redistributable firmware and selected
proprietary applications have their own trust and licensing considerations.

The prepared installer never repairs or repartitions disks. It checks filesystem
integrity, isolated backup media, identities and mount ownership near writes. These
checks reduce risk but do not make installation transactional across a power loss.
Release authentication, configuration checks, credentials and verified external
boot backups precede the first target write. The build then uses the target root;
a failed build can leave incomplete Linux files. The ESP stays read-only until the
exact built generation passes receipt checks. Once activation starts, boot files
may be partially changed. Durable phase records support inspection, not automatic
resume or rollback. Virtual backup disks separate guest devices, not physical
failure domains. Independent data backups and hardware acceptance remain necessary.

Initial installer core identity and authenticated release source/lock identities are
checked before target writes. Installed update authentication uses GitHub immutable
release verification and Sigstore build provenance, restricted to the configured
numeric repository/owner and exact master workflow identity. Privileged command
resolution uses the compiled Nix tool closure without an ambient PATH fallback.
The functional core performs no effects. No GitHub token or release private key is
installed. Key-only SSH is off for console-only installations; Avahi discovery is
optional and defaults off.

Managed updates validate the destination generation's immutable boot receipt,
build before source publication and distinguish partial activation
from a successful rollback. User data and external agent actions are never rolled
back by selecting an earlier NixOS generation. Notifications are advisory; scheduled
security maintenance can terminate work after a bounded grace period.

The evaluated audit checks selected configuration facts, not every possible NixOS
privilege grant. Arbitrary root-owned Nix code can change the entire operating
system. Direct manual administration remains supported, but must be reviewed on
its own terms. Do not represent an audit result as proof of full system isolation.

GitHub, its OIDC/Sigstore trust services, the protected repository/workflow and the
initial trusted verifier are trust roots, not adversaries
this scheme can independently defeat. Releases and bootstrap maintenance use
reviewed native GitHub schedules with inputless manual recovery. The bootstrap
writer can commit only a verified lock or an empty keepalive after both native
architectures pass. No external scheduler credential is required. Observe both
workflow freshness and release expiry through independent read-only monitoring.
Time synchronization is required, but this is not a trusted-clock design against
hostile root or time infrastructure.

The updater advances its anti-replay high-water mark before evaluating authorized
candidate Nix. Candidate lineage must reach the exact local floor; a higher number
on a different hash-chain is not sufficient. Initial applying installation requires
an explicit release tag. Source or boot rollback does not lower that mark. An
installer/core identity mismatch, old or expired metadata, unavailable trust roots
or network, and unprovisioned IDs fail closed without a mutable-branch fallback.
Installed updates may accept a newer authorized core under the existing trust policy.
The [verification contract](docs/verification.md) is required for production use;
missing full acceptance gates block promotion. See
[release authentication](docs/release-authentication.md) and
[governance](docs/governance.md) for boundaries and provisioning tasks.

## Development infrastructure

Developer tooling uses a separately locked Chainman host-Nix environment. Its
full gate freezes raw source into an independent clean Git snapshot before invoking
the unchanged production checks. The repair oracle is separately frozen; same-user
protection is cooperative. Candidate dependency code remains a supply-chain trust
boundary, not something compatibility tests can prove harmless.

Disabled [development maintenance](docs/development-maintenance.md) can write only
two developer locks after both native gates. Its fresh zero-Action writer loads only
verified trusted-base code, consumes bounded JSON evidence and uses an exact-head,
nonforcing ref update. It never runs candidate Nix/Chainman or imports its caches.
The distinct master-only Environment and readiness marker must be provisioned before
enablement. No implementation or local test grants remote publication authority.

## Reporting

Use GitHub's private vulnerability reporting for `assboxai/assbox` when the project
has enabled it. Do not put credentials, disk serials, private hardware profiles or
exploitable vulnerability details in a public issue. If private reporting is not
enabled, request a private contact path without publishing the sensitive details.
Do not assume a guaranteed response time or send private material to an unverified contact.

## Optional execution VM

When `assbox.worker.enable` is selected, its guest has a distinct kernel, filesystem
and user database. The controller `agent` account owns the Desktop session; selected
worker components share the worker VM's `agent` account, not the controller home. QEMU runs as
`assbox-vmm`, not root or the Desktop user. See [worker security](docs/worker/security.md)
for the implemented contract, acceptance requirements and limitations. In
particular, provider tokens inside the guest are compromised if the guest is
compromised; Desktop-local execution is not automatically prohibited by this module.

## Native activation and standalone execution

Native selection alone does not authorize local execution. Managed launchers require
a fresh, root-owned observation of an immutable qualified contract for the exact
client, platform and account scope. Codex Local, Work Local, Work Cloud local access,
browser/computer use and local helpers are independently denied under the strict
kiosk policy. Adding a worker does not relax those controls. No qualified native
probe ships in this candidate; clients remain staged until one is supplied.

Standalone execution defaults to public-internet egress with execution-UID IPv4/IPv6
LAN, private and overlay denial. Explicit normal/offline modes and scoped exceptions
are separate choices. Root owns enforcement and Tailscale control; private dashboard
publication requires explicit mappings and application authentication. Networking,
native-policy effectiveness and provider behavior still require runtime qualification.

Mutable-state checkpoints are root-private and may contain provider credentials.
Restore is explicit, checks local identity/integrity, preserves prior data and a durable
recovery journal, and leaves execution stopped. OS rollback alone never restores data.
