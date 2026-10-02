# Implementation architecture

The accepted deployment contract is in [product architecture](product/architecture.md); [instance types](product/instance-types.md) defines the purpose-first target. [Implementation status](implementation-status.md) distinguishes that target from the baseline source described below.

Sensitive local controllers require explicitly qualified execution separation. Standalone examples never override controller placement policy. The managed-worker subsystem is specialized; it is not required for every headless or remotely operated Assbox.

## Internal crates

Every crate is internal (`publish = false`). The Cargo workspace has six members:

```text
crates/
  functional-core/
    assbox-domain/     values, validated names, explicit observations
    assbox-policy/     installation plans, compatibility, recovery and reboot decisions
    assbox-config/     deterministic rendering of ordinary local Nix and keyfile text
  imperative-shell/
    assbox-system/     Linux observations, commands, files, locks and owned mounts
    assbox-engine/     installation and management operation orchestration
    assbox-cli/        commands, interactive prompts and application onboarding
```

Dependencies flow as follows:

```text
policy → domain
config → policy, domain
system → domain
engine → system, config, policy, domain
cli    → engine, system, config, policy, domain
```

There is no core-to-shell dependency. Core crates do not read the environment,
filesystem, network, clock or entropy source, launch processes, log, or use mutable
global state. Effects cannot be hidden behind injected callback interfaces. Pure
functions receive observations and return values, plans or errors. A public
`InstallPlan` has a private constructor path through policy validation.

The shell owns observations and authorized effects. It uses explicit argv arrays,
a build-time Nix tool closure, root-owned paths, operation locks and journaled file
publication. Core types do not confer perpetual authority: relevant devices,
geometry, holders and mount ownership are re-observed before consequential phases.
The core rejects a stale installation plan. Owned mounts acquire a provisional
cleanup lease immediately after a successful mount, before fallible mount-ID
observation. They retain kernel identity and source
so cleanup does not blindly unmount a replacement; uncertain ownership is reported
for manual inspection.

`scripts/architecture.py` checks the workspace dependency graph and known forbidden
core syntax. It is a deliberately limited static guard, not a Rust parser or proof
of purity. Code review must check transitive behavior and policy placement too.

## Architecture, boot, presentation and application

CPU architecture, hardware/boot strategy, presentation and application are separate.
AArch64 permits generic UEFI/GPT only. x86-64 also permits BIOS and Intel Apple
profiles. Live media is an explicit disk-or-read-only-optical value, not a fake
whole-disk parent for every possible source. The Nix module
is authoritative for installed packages/services. Rust validates installer choices
and consumes evaluation-derived facts before managed activation. Compatibility
errors, including ChatGPT on Wayland, must be rejected rather than silently choosing
a different application or session.

A reviewed JSON catalog generates typed Rust component identifiers and release-family
metadata. Nix reads the same catalog; services remain ordinary handwritten modules.
The drift check rejects missing/unknown dependencies, cycles and duplicate curated
command exports. There is no runtime plugin loader or command interpreter in metadata.
The component model replaces the prerelease application enum directly; no installed
clients require compatibility machinery or a release-protocol bridge.

## Configuration authority

The public source owns appliance policy. The machine owns its local flake and
hardware binding. All permanent settings are normal NixOS configuration. There is
no Assbox-only database that must be consulted to reproduce a system.

`hardware-configuration.nix` and `storage.nix` are generated bindings. Installer
choices are recorded in `assbox-settings.nix` with normal overridable defaults.
`assbox-packages.nix` is a narrow CLI-managed Nix representation. `local.nix` is
human-owned and is never rewritten by updates. The CLI intentionally refuses to
parse or rewrite arbitrary Nix expressions as a package list.

Management stages a complete private copy of the local configuration, evaluates
security facts and builds before publishing a journaled set of managed source files. Before
publication it checks that the original local tree and system profile are unchanged.
The operation lock coordinates Assbox commands, not other root administrators or
normal `nixos-rebuild`; concurrent non-Assbox changes can therefore cause refusal.

## Immutable source and installation boundaries

An immutable core revision, release tag, manifest digest and release high-water mark
are distinct domain values. The release adapter delegates cryptography to the
Nix-pinned GitHub CLI. Pure policy consumes verified identity facts and explicit
time/state, not a network client or logger. The shell verifies the immutable release,
workflow provenance, source archive, NAR and exact generated lock before candidate
Nix evaluation. No moving update-track abstraction is part of installed release
consumption. Installation additionally binds the binary's core commit; updates can
accept an authorized newer core under the existing trust policy.

The machine flake carries the authenticated graph with literal immutable input
syntax. Release authentication, local configuration evaluation, credential capture
and external boot-backup read-back finish before the first target write. The
installer uses Nix's standard target/chroot store and a build directory on that
same root, keeping the ESP read-only. After the build it resolves the immutable
receipt inside the target store and validates it against the captured install plan.
`nixos-install --system` then activates that exact closure without resolving a new
graph. No additional scratch disk or intermediate installed OS is needed.

Initial installation has its own deliberately small phase record:
`target-writes → building → activating → complete`. Its external write intent and
target record bind the operation, storage identities, backup name and release/config
digests. They are diagnostic evidence, never authorization to resume. Build retries
require explicit input within the original process and recheck identity, owned
mounts, configuration bytes and release freshness. Signals cancel the operation;
build/installation subprocesses run in dedicated systemd cgroups that are stopped
before mount leases can be dropped. Password-client output stays in bounded memory.
Release CI uses ordinary Python scripts with a pure release-data module and an
effectful orchestrator. The installed program remains the six-crate Rust workspace.

## State transitions and recovery

```text
prepared → built → published → activating → committed
```

The first complete private journal is published atomically; incomplete preparation
never occupies the active name. Retirement removes that name atomically before
recursive cleanup. Both cuts are part of the recovery contract.

`published` and the complete changed-file list are durable before any individual
rename. Recovery checks all affected files for old/candidate bytes before changing
any; it refuses third-party edits. The release acceptance watermark is deliberately
outside source rollback and is durable before candidate evaluation. An
interruption during `activating` is different: source restoration does not undo
service changes, boot files or mutable application state. It requires inspection.
The CLI never describes a failed activation as a proven rollback.

Each built generation carries a schema-2 receipt. Its `binding` contains
architecture, strategy, platform, storage identities, filesystem types and immutable
loader details. Its separate `policy` contains the active boot-menu generation limit.
The boot guard compares the actual destination generation's binding, not merely
current local settings, before profile changes or activation. Pure policy allows
limits from 2 to 32 without weakening binding equality. Foreign/old-schema receipts
and storage/strategy migrations require expert NixOS administration.
The update boot guard records partition-table geometry. In Apple mode it also
records firmware output and unrelated ESP contents, and retains a local ESP archive
while an operation is pending. A boot-strategy change is not an ordinary update.
The initial installer makes a separately verified external boot backup; the update
journal is local and is not an independent backup against disk loss.

The bounded executable specification in `scripts/model_check.py` records ordering
assumptions and explores interruption observations and maintenance combinations.
It does not establish refinement to compiled Rust or prove Linux, Nix or firmware
behavior. Rust contract tests are a separate bridge to implementation, and real VM
and hardware tests are separate again.

## Rust policy

The workspace declares edition 2024 and minimum Rust 1.90. Nix's committed input
lock supplies the release toolchain; a machine-global rustup default is not the
release specification. Every crate forbids unsafe Rust. That restriction does not
assert that dependency crates, the Rust standard library, the toolchain or external
system tools contain no unsafe code.

The functional core uses the standard library and internal crates only. The system
adapter uses two pinned crates.io dependencies: `signal-hook` for cooperative
cancellation and `rustix` (only `std` and `termios` features) for safe terminal
restoration and unread-password flushing. `Cargo.lock` and the architecture guard
record their reviewed versions, features and transitive dependency graph; the
release gate checks Cargo advisories. Their safe interfaces let Assbox keep its own
unsafe-code prohibition without reimplementing signal handlers or termios bindings.

Structured command output is decoded through the Nix-pinned `jq`, not an ad-hoc
JSON parser. Disk operations remain delegated to established system tools; Assbox
is not a GPT, filesystem or firmware implementation. A new dependency must justify
its purpose, license, transitive dependencies and reproducible locking.
