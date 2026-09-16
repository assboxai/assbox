# Verification contract

Source inspection is not compilation; compilation is not execution; a VM is not a
Parallels graphics or Mac firmware/macOS acceptance test. Test definitions alone
are not evidence that they passed. Keep source-specific executed results external.

## Publication and acceptance

Publishing the repository makes implementation available for review. It does not
approve an authenticated release, deploy infrastructure or authorize installation
on a production machine. The order is native bootstrap and source review, complete
release/VM acceptance, controlled infrastructure deployment and disposable manual
VM testing, then production rollout. Keep the release scheduler disabled until its
own dispatch, resource-limit and notification tests pass.

The full acceptance derivations below are not yet implemented. They remain hard
promotion blockers on **both architectures**; the existing build matrix and fixture
VMs are not substitutes. Track implementation here rather than repeating dated
validation reports throughout product documentation.

| Required check | Acceptance it must establish |
| --- | --- |
| `install-boot-vm` | Production install, pre-write refusal, installed-disk boot |
| `activation-recovery-vm` | Real staging/activation, interruption, recovery and retention |
| `authenticated-release-vm` | Real verification, lineage, replay and tamper refusal |
| `application-chatgpt-vm` | ChatGPT profile and authenticated application behavior |
| `application-opencode-vm` | OpenCode profile and authenticated application behavior |
| `application-openclaw-vm` | OpenClaw profile and authenticated application behavior |

A genuine reviewed `flake.lock` and provisioned repository/owner identities are
also required. Default zero IDs intentionally refuse release acceptance. No source
checksum, test fixture or local report substitutes for successful native gates and
verified external provisioning.

## Existing gates

`scripts/verify` requires the internal dependency/effect guard, native Rust formatting,
warning-free Clippy, locked workspace build/tests, source/tooling tests, independent
bounded specification checks, Node tests for both infrastructure Workers, and
native guard-removal mutations. It also requires
Nix formatting, Bash/ShellCheck, actionlint and genuine Nix flake checks, including
representative system builds and the defined disposable VMs.

Release checks require a clean committed core or a release candidate compared
byte-for-byte with that core, allowing only generated lock/context changes. They
additionally require measured core line
coverage of at least 90%, Cargo dependency advisory review and NixOS closure scans.
There is no measured shell-coverage floor. A mutation counts only when a passing
native baseline becomes a real assertion failure, not a compiler error, missing
tool or timeout. Crates.io advisory checks do not scan the compiler itself.

Both native architectures must pass. Cross-compiling a binary or evaluating an ARM
derivation on x86 is not an ARM execution result. Format/compile/test failures remain
real failures even when higher-level source checks passed.

## Configuration and VM matrix

The x86-64 fixture matrix contains fourteen systems: nine none/OpenCode/OpenClaw
presentation combinations, ChatGPT/X11, two BIOS shapes and two Intel Mac profiles.
The AArch64 matrix contains the ten generic application/presentation combinations,
all UEFI. Negative checks reject ChatGPT/Wayland on both and ARM BIOS/Intel-Apple
combinations. Synthetic identifiers are not real user hardware profiles.

The storage/policy VM exercises non-repairing ext4/FAT/exFAT checks on disposable
images, byte preservation, mount/read-back and read-only write refusal. It invokes
the production probe and **plan-only** wizard with a synthetic live disk and a real
optical `rom`/ISO9660 device shape. x86 uses a BIOS plan; ARM boots a UEFI VM and
uses a UEFI/GPT plan. The optical fixture is not the actual installer ISO that
booted the guest. These checks do not execute `install --apply`.

The management VM invokes the real CLI against preparation/retirement orphans,
pre-activation/publication recovery, unrelated edits, activation-inspection refusal,
a corrupt active journal and a foreign rollback target. It checks that a foreign
generation is neither selected nor executed. An immutable runtime fixture also
checks that pending-boot handling precedes a corrupt staging budget, and that an
unresolved journal blocks it even with exhausted retries. These fixtures do not
exercise real package activation, a completed update, generation pruning or
filesystem power loss.

## Required end-to-end acceptance

The checks listed under [publication and acceptance](#publication-and-acceptance)
must exist as `checks.<system>.<name>` and pass before promotion. Each advancing
application input must pass its application check, and the composed final candidate
must pass the full gate on both architectures. The release script checks their
presence and refuses missing checks. Adding names or dummy passing derivations is
not sufficient; review implementations and execution against the contract below.

Full installation acceptance must execute the production source binding, prebuild,
external backup, target apply, installed-disk boot and post-boot checks for x86
UEFI/GPT, BIOS/GPT, BIOS/MBR and ARM UEFI/GPT. Hash target bytes at injected failures
before the first-write boundary. Exercise nonempty/dirty media, recovered files
inside `lost+found`, misleading recovery-directory types/ownership, optical/live-media
exclusion, EFI boot paths and subsequent rescue access. Check displayed disk model,
serial, capacity and by-id identity against the selected devices and final confirmation.

Full activation/recovery acceptance must perform real package add/remove, automatic
staging, profile activation, target-receipt validation, failed effects, reboot and
retention/GC on disposable systems. Test interruption cuts before the first journal
publication, during source/profile/boot changes and during retirement. Inspect
incomplete activation instead of asserting a fictional whole-system rollback.
Test allowed boot-menu limit changes in both directions and rejected changes to
immutable bindings or receipt schema. Test a pending update with unavailable release
servers and corrupt/exhausted staging budgets: pending boot must take priority over
new staging. An unresolved or unreadable journal must prevent reboot, including
when the retry budget would otherwise skip staging. Authenticated-release acceptance must exercise the
actual verifier, replay/expiry rules and publication journal described in
[release authentication](release-authentication.md); a valid Git branch or a Nix
substitute signature is not a substitute for that release-approval check.

4Kn storage, hardware disappearance, actual power loss, EFI ownership and the Intel
Apple shared-ESP path require appropriate dedicated tests. No test may claim to
boot macOS from an APFS-type sentinel containing no macOS installation.

## Hardware and application acceptance

For every promoted profile, verify live-media and installed-target boot, storage
identities, networking/credentials, TTY and graphical input, display policy, USB
input/Ethernet, denied raw storage access, rescue boot and retained generations.
Exercise scheduled updates while the GUI and agents are active, low/unknown power
retries and disk-space pressure. On Intel Macs verify both rEFInd and macOS boot.
On Parallels record guest architecture, firmware, virtual devices and GUI behavior
separately from host architecture. Follow [the acceptance guide](parallels.md).

For each application version/architecture, test actual onboarding/provider login,
authenticated tasks, headed/headless client behavior, loopback binding, shutdown
timeout and restart after reboot. A running service or built package does not prove
an authenticated end-to-end task works.

## Bounded specification and assumptions

`scripts/model_check.py` explores journal publication/retirement cuts and maintenance
combinations with explicit battery presence and uncertain observations. It assumes
ordered durable writes and atomic rename; it does not model every filesystem,
firmware or Linux crash behavior and does not call compiled Rust. Report its results
as separate requirement-level specification exploration, never formal verification
of the implementation or extra Rust test passes.

Rust contracts separately test validated architecture/media/boot choices, prepared
root observations, explicit proprietary-package consent, safe terminal rendering,
source identity, lock rebasing, recovery/reboot policy, retention and owned mounts.
The tooling suite executes the shipped X11 and Wayland wrappers with explicit fake
systemctl/window-manager adapters to test lifecycle ordering, failures and termination; it does not run
LightDM, greetd, Xorg, labwc, Openbox or a real user manager. It also executes the
actual Python lock-composition/archive/publisher policies and jq decoders with
synthetic evidence. These tests do not perform real GitHub/Sigstore cryptography
or evaluate Nix locks. The no-token GitHub CLI patch must build and verify actual
public immutable releases in native acceptance. Nix checks compare emitted generation
receipts and assert the headed OpenCode package set excludes Chromium.
A successful Rust test still does not establish the corresponding hardware effect.

## Evidence

Record exact source/archive hashes, tool versions, commands and return codes.
Keep logs, mutation/coverage/scan output external to the public source archive.
Unavailable checks are unexecuted, not passed. Never inherit counts from a different
implementation or earlier source revision. A lock, checksum, test definition or
this document is not itself release approval.

## Release-specific failure injection

Exercise a failed application advance with successful OS/final retained-pin checks,
a vulnerable retained pin that must block publication, missing/duplicate/cross-arch
reports, mutable source files hidden in an archive, tag/manifest/core mismatch,
publication without immutability, failed post-publication verification and latest
promotion refusal. Verify that publication jobs never execute candidate code.
Test multi-file source journal cuts and replay state across failed builds, source
restoration and boot rollback. Enforce unknown time/ref/identity/runner failures
before candidate Nix evaluation. Real public-release bootstrap and clock/TUF/API
behavior cannot be established by fake certificates or a source-order assertion.

The management VM also defines all eight old/candidate combinations across the
three release-source files, whole-restore refusal after an administrator edit, and
preservation of an independent high-water-mark sentinel. These are recovery
fixtures, not authenticated staging, real power-loss injection or completed updates.

## Lineage, dispatch and monitor acceptance

Check reserved-genesis creation against an empty release/tag inventory, refusal of
an orphan/deleted genesis or mismatched inventories, canonical parent digests,
invalid highest-history entries, backward/missing latest, pagination limits, and
stale advertising reruns. A candidate must extend the exact installed floor:
exercise parent tampering, a missing parent, a fork, a skipped floor and bounded
traversal before Nix evaluation. Test equal-release retries and keep protocol-1
refusal explicit. Use real attestations for the final authenticated-release VM;
synthetic certificate fields and source-order checks are not substitutes.

Verify that the CI API-read step exits before any candidate Nix process starts,
that child commands cannot inherit API/OIDC credentials, and that the privileged
publisher executes no candidate program. Both native post-publication verification
jobs must run the bootstrap client, then build the client from the authenticated
release source/lock and perform a second fresh public verification. Missing or
differing manifest/lock/source receipts, failure of either binary, and candidate
build errors must prevent advertisement. Test changed verifier dependencies, not
just source-identical renewals. The fake-command orchestration tests execute this
ordering but are not native builds or cryptographic round trips.

Run `scripts/workflow_policy.py` and its mutation-style document tests. Verify that
additional workflows cannot obtain write/OIDC permissions, environment/declared
secrets or unreviewed effect entrypoints, regardless of trigger. Include push-only,
workflow-run, scheduled and reusable workflows, actual file discovery, and renamed
release jobs; only the reviewed `release.yml` publication jobs have exceptions.
Scan token and secret references across workflow/job fields, mapping keys and
nested matrices as well as steps. Test outputs, raw conditions, bracket/dynamic
indexing, whole-context serialization and quoted braces inside expressions. Only
exact approved command environments may bind `GH_TOKEN`; adding a name, shell,
condition, working directory or alternative binding must not create another escape.
Scalar identity reads remain allowed. Actions in a privileged job still have
implicit access to that job's token and must remain pinned and reviewed.

The lint applies to current source, not historical rerunnable versions. Test a moved
master before attestation, each publication write/upload and advertising. The guard
is not a complete proof of shell/action behavior and cannot inspect repository settings. Environment protection
must be checked in the real GitHub settings: it is not a certificate field that the
client has established it can verify.

Worker tests use synthetic HTTP effects; the scheduler additionally signs/verifies
real ephemeral test JWTs through Node WebCrypto. Deploy to the actual Workers Free
plan only after source review, confirm CPU and subrequest limits, provision exactly
one repository's App installation, and execute real dispatch/disabled-workflow/API
error cases. Inspect the actual returned token permissions and repository IDs.
Confirm that no token, key or provider response body is written into logs. Test
App suspension/revocation as the emergency stop, not just workflow disabling.

Configure the external monitor, force backward latest despite unexpired metadata,
missing/orphaned/paginated history, harmless non-`r-*` source tags/releases after
genesis, and malformed `r-*` identities that must never be filtered away. Compare
the actual CI and monitor namespace decisions on identical fixtures; unrelated
entries still count toward pagination/resource bounds and cannot authorize genesis
or make a non-head latest healthy. Test fresh failure despite an earlier success,
queue/run-grace expiry, stale success and near-expiry cases, and confirm an
actual notification and recovery message. A plain request to GitHub that returns
200 is not a freshness test. The monitor endpoint is read-only availability
telemetry, not release signature verification; account compromise of its shared
hosting provider can falsify it. Neither passing local tests nor a successful
Wrangler dry run proves that a deployed Cron or notification service is active.
