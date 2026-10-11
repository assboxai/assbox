# Assbox

Assbox is a dedicated machine for running AI agents and, when selected, a physical terminal for ChatGPT and Claude. It uses ordinary NixOS configuration and management tooling; upstream applications own their agent experiences and orchestration.

**Source status:** beta implementation candidate with native/authenticated qualification outstanding. The [accepted product contract](docs/product/index.md) defines the implementation target; [implementation status](docs/implementation-status.md) identifies what this source baseline does and does not yet contain. A target feature listed here is not a claim of completed support.

## Choose the job, then the application

| Instance type | Application choices |
|---|---|
| Assistant | OpenClaw recommended; Hermes alternative |
| Coder | Happier recommended; Codex external Desktop SSH; Claude native access; grouped native alternatives; terminal/SSH |
| Kiosk | ChatGPT Desktop, Claude Desktop or both; no local execution by default; optional protected local Code; explicit web alternative |
| Custom / Advanced | Components, presentation, execution placement and access directly |

Assistant/Happier presets select the eight curated coding CLIs by default, individually deselectable. Native and bare presets are minimal with optional expansion. Package installation, provider login, service activation and network exposure are separate choices. Nano and tmux remain base tools. Tailscale support is a guided, deselectable default; enrollment/exposure are explicit. Raw component module defaults remain opt-in.

Standalone execution is the normal headless arrangement. A sensitive native controller requires its exact policy gate; protected local Code uses the managed worker boundary. Claude Code SSH and Cowork local/cloud behavior are separately qualified. Physical presentation and optional autonomous virtual desktops are different capabilities.

Read [strategy](docs/product/strategy.md), [instance types](docs/product/instance-types.md), [Coder interfaces](docs/product/coder-options.md), [deployment architecture](docs/product/architecture.md), [access/security](docs/product/access-and-security.md), [computer use](docs/product/computer-use.md) and [lifecycle](docs/product/lifecycle.md).

The [generated preset and component tables](docs/product/component-presets.md) use the installer's reviewed data and describe initial selections and placement.

### Native Coder and kiosk choices

The Coder menu makes Codex via an external ChatGPT Desktop SSH connection explicit, including macOS controlling a standalone Parallels guest. No Desktop or nested worker is required in that guest. Native chat/cloud Kiosk requests no local agent execution; activation requires verified effective controls for each selected client/platform/account. Protected local Code explicitly selects the managed worker and still needs its own exact-route/no-fallback evidence. The purpose-first wizard and generated configuration are implemented; [native and integration qualification](docs/implementation-status.md) remains separate.

## Existing source arrangements and supported hardware scope

The installer starts with purpose, then application, component exclusions, presentation, execution resources and access. Existing headless, X11/Openbox and Wayland/labwc machinery remains. Native Desktop compatibility is specific to the selected application and its qualification record.

Retain generic x86-64 UEFI/BIOS, existing Intel Mac preservation profiles and generic AArch64 UEFI arrangements, including suitable VMs. This is not bare-metal Apple Silicon, 32-bit ARM or board-specific boot-image support. Consult [hardware acceptance](docs/intel-mac-acceptance.md) and [Parallels](docs/parallels.md). A VM without exposed KVM can be a standalone host even when native worker/provider-VM routes are unavailable.

The existing direct QEMU/KVM [managed worker](docs/worker/controller-model.md) has persistent home, disposable root, dedicated SSH identities and host-enforced policy. Preserve its [operations](docs/worker/operations.md), [scoped Git workflow](docs/worker/git-workflow.md), [client-routing checks](docs/worker/client-routing.md) and [qualification status](docs/worker/implementation-status.md). A VM does not reduce the provider-side authority of a credential placed inside it.


## Installation and maintenance

The installer accepts prepared storage; it does not partition, erase, resize or
repair disks. Target and external boot-backup must be separate disks, neither
containing the live installer. USB installation therefore needs three distinct
disks; an attached read-only optical ISO can serve as the live medium instead.
Virtual disks provide guest-device separation, not independent physical backups.

An applying installation requires an explicit `--release r-N`. The installer
authenticates that immutable release, binds its core identity and exact dependency
lock, evaluates the machine configuration and verifies an external boot backup.
It then builds in the prepared target's Nix store with disk-backed build space,
validates the resulting generation and installs its bootloader. One live-media
session completes setup; there is no intermediate plain-NixOS installation.
Read [installation](docs/installation.md), including its failure phases, before use.

Maintenance defaults to daily **18:00 local time**, up to 15 minutes of jitter, and
catch-up after missed windows. Changed updates are staged, announced and followed
by reboot after a ten-minute grace period. An active graphical session or agent job
is not a veto. Low or uncertain battery power defers reboot. Failed scheduled
staging gets a bounded hourly retry budget. Conservative generation retention and
store cleanup run only without a pending boot/recovery operation.
See [maintenance and recovery](docs/maintenance.md) for exact behavior and limits,
and [resource behavior](docs/resources.md) for background scheduling, zram and
application restart policy. Build parallelism remains at the upstream defaults.

## Development and release gate

Start with [development](docs/development.md): `just setup`, then `just verify`.
[Finite preparation and repair sessions](docs/repair-loop.md) make expensive
verification and its source/oracle identity explicit. A source checkout without a
genuine `flake.lock` is a bootstrap candidate, not an installable release. Initial bootstrap resolves the lock with Nix. Scheduled maintenance verifies
the candidate before its bounded lock-only or empty commit; it never formats or
changes arbitrary source.

Source publication is not production release approval. Both architectures require
native Rust/Nix gates, coverage, mutation and vulnerability checks, plus full
installation, recovery, authenticated-release and application acceptance. The
[verification guide](docs/verification.md#publication-and-acceptance) lists the
implemented gates and outstanding acceptance that block promotion. Do not
deploy production machines before those gates and disposable-VM acceptance pass.

The protected source branch is **`master`**. Routine dependency releases do not
commit to it: read-only builders compose tested pins, and isolated publication jobs
attest a manifest and publish immutable release assets. The installed client verifies
release and build attestations before candidate Nix evaluation. There is no private
release key, daily manual approval, installed GitHub token or mutable-branch update
fallback. A genuine bootstrap lock is committed. Actual repository/owner IDs in
`release/policy.json` still need provisioning; the default zero IDs fail closed. See
[release authentication](docs/release-authentication.md),
[governance](docs/governance.md) and
[verification](docs/verification.md).

Routine releases extend a canonical hash-linked manifest history; the mutable GitHub
latest label is only an installed-client discovery hint. The first release is
reserved as `r-1`, and an installed client's acceptance floor cannot be reset by
rolling back a system generation. Source protocol changes require explicit review.

Releases run on a fixed daily GitHub Actions schedule, with inputless manual
recovery. Weekly [bootstrap maintenance](docs/automation.md) verifies both native
architectures before committing only the bootstrap lock or an empty keepalive to
master. It uses the ephemeral repository token. The independent
[read-only health probe](infra/release-monitor/README.md) observes both workflows
and release freshness. Provision and test external alert delivery before enabling
unattended release operation.

## Documentation

[Architecture](docs/architecture.md) · [Local configuration and packages](docs/configuration.md)
· [Applications](docs/applications.md) · [Security](SECURITY.md)
· [Contributing](CONTRIBUTING.md)

## License

Assbox project code is licensed **GPL-3.0-or-later**. See [LICENSE](LICENSE) and
[NOTICE](NOTICE). NixOS, applications, firmware and other dependencies retain their
own licenses. Selecting a proprietary application is explicit and does not relicense
that application under Assbox's license.
