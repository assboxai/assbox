# Verification contract

Source inspection is not compilation; compilation is not execution; a VM is not a
Parallels graphics or Mac firmware/macOS acceptance test. Test definitions alone
are not evidence that they passed. Keep source-specific executed results external.

## Publication and acceptance

Publishing the repository makes implementation available for review. It does not
approve an authenticated release, deploy infrastructure or authorize installation
on a production machine. The order is native bootstrap and source review, complete
release/VM acceptance, controlled infrastructure deployment and disposable manual
VM testing, then production rollout. Enable the native release/bootstrap workflows
only after their gates and repository protections are ready; provision and test
independent monitor alerts separately.

The acceptance checks remain hard promotion blockers on **both architectures**.
The existing build matrix and fixture VMs are not substitutes. Track engineering
here and keep dated, source-specific execution reports outside the repository.

| Required check | Implementation and remaining acceptance |
| --- | --- |
| `install-boot-vm` | Defined: prepared-media refusal, verified backup, target-store build, explicit retry/cancellation, power-loss cuts and actual installed-disk boot; native execution and real-media/hardware acceptance remain required |
| `activation-recovery-vm` | Defined: real package changes, staging/activation, failed effects, interruption, recovery, pending reboot and retention/GC; native execution remains required |
| `authenticated-release-vm` | Defined: compiled pipeline with controlled external evidence, plus genuine upstream signature fixtures; complete native execution and public-release acceptance remain required |
| `application-chatgpt-vm` | Defined: actual locked package in X11; native execution and provider-authenticated tasks remain required |
| `application-opencode-vm` | Defined: actual locked package in headless/X11/Wayland, invalid-credential startup refusal, local authentication, frontend-child crash recovery, X11 window close and explicit stop; native execution and provider tasks remain required |
| `application-openclaw-vm` | Defined: actual locked package in headless/X11/Wayland, authenticated Gateway restart handoffs, independent dashboard/browser processes, dashboard crash recovery, X11 window close and explicit stop; native execution and provider tasks remain required |
| `remote-lifecycle-vm` | Defined: real remote/editor/application units with substitute providers, CLI onboarding and frontend launch, crash/clean-exit recovery, descendant/session cleanup, diagnostics and NixOS reconfiguration; native execution remains required |
| `editor-vm` | Defined: actual VS Code/Zed/Emacs foreground entry points, visible X11 windows, main-process crash recovery, normal close and session teardown/restart; generic GNU/Linux rust-analyzer LSP handshakes from agent login and user service; native execution remains required |
| `desktop-services-vm` | Defined: real portal file/folder open, save and cancel dialogs on X11 and Wayland; GNOME first-use keyring creation and disposable-secret persistence across client/session/daemon restart and reboot, private files and deletion; Zed-only browser dependency, session URL-handler/rendered loopback callback and browser cleanup; repeated greetd crashes, compositor failure/logout, old-session cleanup and deliberate stop; native execution remains required |
| `radio-policy-vm` | Defined: X11/Wayland active-seat ACLs with Wi-Fi enabled/disabled, denied agent radio writes, disabled kernel radio-hotkey handler, root control, NetworkManager preference restoration, session restart and software-radio hotplug; native execution remains required |

Engineering readiness requires implemented behavior and substantive verification
gates capable of checking it. Pending execution alone is different from missing
implementation. The named suites are now present; their definitions are not passing
results. The expensive follow-up tranche must execute and fix the installation,
activation, release, application and resource VMs, then run the full native gates,
coverage, mutations and vulnerability scans. A stopped or partially executed check
supplies no passing result. Execution-driven fixes remain in that tranche while
other work shares the development host.

A genuine `flake.lock` is committed. Reviewed pins and provisioned repository/owner
identities are also required. Default zero IDs intentionally refuse release acceptance. No source
checksum, test fixture or local report substitutes for successful native gates and
verified external provisioning.

## Expanded component gates

See [component qualification](component-acceptance.md) for the expanded matrix,
per-family native checks, access/firewall VMs, closure absence checks and owner-run
provider procedures. All new native/provider checks remain unexecuted until the
deferred tranche. Blocked capabilities reject configuration and carry no support claim.

## Existing gates

`just verify` is the complete developer gate, including an independent clean
production snapshot and a fresh canonical interactive install. `scripts/verify`
with no arguments remains the existing production stage dispatcher. For targeted local work,
select exactly one stage: `static` (source/tooling/model/Node tests and formatting/lint),
`rust` (Clippy, compilation and Rust tests), `mutations`, or `nix` (flake evaluation,
system builds and VM checks). Stages stop on failure and preserve command exit codes.
Selecting a stage never constitutes a passing full gate. Even the `rust` stage can
be expensive on a cold cache; resource restrictions still apply.

Rust integration tests feed actual rendered Wi-Fi keyfiles through libnm and
compare SSID bytes and passphrases, including numeric/semicolon names, backslashes,
spaces and UTF-8. This catches the keyfile reader's legacy byte-list interpretation
and separate SSID escaping rules. See the pinned
[NetworkManager keyfile implementation](https://github.com/NetworkManager/NetworkManager/blob/1.56.0/src/libnm-core-impl/nm-keyfile.c).
The gate uses the locked libnm in Nix; it needs no daemon or network connection and
does not establish successful radio/driver association on physical hardware.

The verification workflow provisions Just, runs Chainman setup without hooks and
calls the finite full coordinator. Developer stages use `scripts/verify_observed.py`,
which records memory/swap availability, disk space,
pressure indicators and readable cgroup memory-event counters before execution,
every 30 seconds and at completion. Missing metrics are unknown, not zero. No
environment dump, password, or process command line is collected. Diagnostics
are best effort and do not turn failed or interrupted verification into success.

Records stream to the job log and to `${RUNNER_TEMP}/assbox-verification` in Actions,
or `reports/verification` for a deliberate local wrapper invocation. Each stage's
file is capped at approximately 8 MiB plus its final record. The pinned final
`always()` upload retains that diagnostics directory and bounded top-level
candidate/canonical summary records for 14 days, named by
architecture, commit and run attempt. A destroyed runner can prevent both final
sampling and upload; absence of evidence never proves an OOM or a passing check.

`scripts/verify` requires the internal dependency/effect guard, native Rust formatting,
warning-free Clippy, locked workspace build/tests, source/tooling tests, independent
bounded specification checks, Node tests for the read-only monitor Worker, and
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

The installation gate calls the production installer through a noninstalled Rust
test executable, performs real `nix build --store` and `nixos-install --system`,
then boots the resulting disk without the live medium. It includes x86 UEFI/GPT,
BIOS/GPT, BIOS/MBR and rEFInd/shared-ESP variants, ARM UEFI/GPT, and 4Kn UEFI on
both architectures. Cases cover root-content refusals, corrupt backup read-back,
insufficient backup space,
pre-write byte preservation, credential cancellation, termination of an actual
builder grandchild, configuration/mount drift, target ENOSPC, same-process retry
after an unavailable fixed-output build input, and abrupt VM exits at durable
installation boundaries. It checks private credentials/state and real admin SSH
after boot. The optical source is still an observation fixture; real ISO boot is
manual acceptance.

The activation gate uses that installed disk for real add/remove, generation-limit
changes, foreign binding/schema refusal, failed build/activation, three-file release
publication, staging, reboot and retention/GC. Power cuts bracket preparation,
publication, profile/activation and durable retirement. A pending generation must
boot with unavailable release transport and a corrupt or exhausted retry budget;
unresolved journals must still block it. Source recovery preserves the real release
high-water mark. The shared offline source mirror serves locked archives whose NAR
hashes Nix verifies. Release certificate observations remain test-controlled; these
gates do not replace public cryptographic release acceptance.

The new release VM invokes an ignored, root-only Rust test executable compiled with
a fixture tool closure. It calls the same release-fetch function as production,
while the external HTTP and verified-certificate observations are deterministic.
A separate phase executes the pinned real GitHub CLI against its genuine upstream
signed fixtures, including tampered bytes and incorrect certificate constraints.
The test executable is not installed as `assbox`, and the production binary retains
its compiled trust IDs, fixed tools and normal CA bundle. Neither test layer proves
that an Assbox release or GitHub environment is correctly provisioned.

The application VMs use the actual locked packages and real user services/session
managers. They define local credential gates, loopback checks, process failure and
restart, logout, shutdown and reboot checks. They use disposable local credentials;
no provider account is logged in and no paid model task is claimed.
The OpenClaw gate opens ordinary Chromium and the dashboard in both launch orders,
checks separate service cgroups, and verifies that dashboard recovery and closure
preserve the ordinary browser. Its profile-persistence marker checks retained local
state, not successful provider authentication.
The Gateway receives SIGUSR1 on its main process to exercise its successful
supervisor handoff. The gate requires a new process, restored authenticated health,
loopback-only listening, a closed dashboard staying closed and an explicit backend
stop remaining stopped beyond the maximum restart delay.

The separate `remote-lifecycle-vm` runs the production remote, editor and application
adapter modules with harmless substitute provider executables. It checks service
supervision, permission markers, graphical ownership, doctor output and private
diagnostic capture, including actual NixOS switches that change settings or remove
a component. It exercises the real CLI setup path for first OpenCode/OpenClaw
onboarding: failed initial setup leaves units stopped, successful setup opens the
selected frontend only in an active graphical session, and removing the launcher
leaves setup usable. It also checks that backend restarts do not reopen a normally
closed frontend, including an OpenClaw backend clean exit, descendant cleanup and
explicit stop. It keeps the production restart policy and shortens only delays.
This mandatory gate complements the package VMs; it cannot establish compatibility
with provider binaries or accounts.

`resources-vm` observes the background slice, a real Nix sandbox child and zram's
logical/allocated size. It checks the absence of Assbox CPU quotas and memory
ceilings. See [resource behavior](resources.md) for the intended policy.

## Required end-to-end acceptance

The checks listed under [publication and acceptance](#publication-and-acceptance)
must exist as `checks.<system>.<name>` and pass before promotion. Each advancing
application input must pass its application check, and the composed final candidate
must pass the full gate on both architectures. The release script checks their
presence and refuses missing checks. Adding names or dummy passing derivations is
not sufficient; review implementations and execution against the contract below.

Full installation acceptance must execute the production source binding, external
backup, target-store build, target activation, installed-disk boot and post-boot checks for x86
UEFI/GPT, BIOS/GPT, BIOS/MBR and ARM UEFI/GPT. Compare all target bytes at injected failures
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

The virtual 4Kn and shared-ESP cases supplement physical checks of hardware
disappearance, actual power loss, EFI ownership and Intel Apple firmware. No test may claim to
boot macOS from an APFS-type sentinel containing no macOS installation.

## Hardware and application acceptance

For every promoted profile, verify live-media and installed-target boot, storage
identities, networking/credentials, TTY and graphical input, display policy, USB
input/Ethernet, denied raw storage access, rescue boot and retained generations.
Exercise scheduled updates while the GUI and agents are active, low/unknown power
retries and disk-space pressure. On Intel Macs verify both rEFInd and macOS boot.
On Parallels record guest architecture, firmware, virtual devices and GUI behavior
separately from host architecture. Follow [the acceptance guide](parallels.md).
For Intel Macs use the [model and networking acceptance procedure](intel-mac-acceptance.md).
Rust gates cover model/profile refusal, unbound/insecure wireless drivers, supported
external adapters and hardware drift. Sysfs adapter tests use local fixture trees.
The Apple install VM supplies a synthetic MacBookPro12,1 DMI identity through QEMU
and exercises profile refusal before target writes; this remains no evidence about
physical Mac firmware or wireless hardware.

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

Monitor tests use synthetic read-only HTTP effects. Before deployment, confirm the
actual Workers plan's CPU/subrequest limits and exercise disabled-workflow, stalled
run and API-error cases. Test the bootstrap writer's environment protection and
non-forcing expected-head update in the provisioned repository. Its ephemeral
repository token must not reach candidate evaluation or logs. The monitor requires
no GitHub App installation or dispatch credential.

Configure the external monitor, force backward latest despite unexpired metadata,
missing/orphaned/paginated history, harmless non-`r-*` source tags/releases after
genesis, and malformed `r-*` identities that must never be filtered away. Compare
the actual CI and monitor namespace decisions on identical fixtures; unrelated
entries still count toward pagination/resource bounds and cannot authorize genesis
or make a non-head latest healthy. Test fresh failure despite an earlier success,
queue/run-grace expiry, stale success and near-expiry cases, and confirm an
actual notification and recovery message. A plain request to GitHub that returns
200 is not a freshness test. The monitor endpoint is read-only availability
telemetry, not release signature verification; account compromise of its
hosting provider can falsify it. Neither passing local tests nor a successful
Wrangler dry run proves that a deployed Cron or notification service is active.

## Isolated worker gates

The worker adds `worker-tools`, `worker-policy`, `worker-artifact`,
`worker-boot-gate-vm`, `worker-sshd-policy-vm`, and `worker-network-vm`
to native checks and the release prerequisite names. Python helper checks also
run in the static stage. These do not replace production KVM lifecycle or
authenticated Desktop/mobile tests; see [worker acceptance](worker/acceptance.md)
and [observed worker status](worker/implementation-status.md).
