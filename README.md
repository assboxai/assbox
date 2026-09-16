# Assbox

**Assbox is beta software.**

Assbox (Assistant Box) is an opinionated NixOS configuration and installer for an
assistant appliance, with or without a graphical session and with or without an
assistant application. It targets repurposed x86-64 PCs, including legacy BIOS
machines, and generic AArch64 UEFI machines or virtual machines. Intel Macs are a
compatibility profile, not the underlying architecture.

Project: [assbox.com](https://assbox.com) · [assboxai/assbox](https://github.com/assboxai/assbox)

## Ordinary NixOS, local machine configuration

The public flake exports `nixosModules.default` and native `assbox` executables for
`x86_64-linux` and `aarch64-linux`. The installer creates an ordinary `/etc/nixos`
flake, hardware discovery, storage binding, settings and a user-owned `local.nix`.
Machine identifiers and hardware profiles are not uploaded. Neither a fork nor
committing a machine profile upstream is required. The default hostname is
`assbox-` plus a random six-character suffix.

`assbox` provides convenient package management, validation, updates and recovery.
It does not replace NixOS or require a second configuration database. Direct NixOS
module edits and normal `nixos-rebuild --flake /etc/nixos#assbox` remain supported.
The base toolbox includes `just` as a normal package; Assbox has no Justfile or
administrative recipes.

## Hardware and boot targets

| Architecture | Firmware/storage | Profile |
| --- | --- | --- |
| x86-64 | UEFI/GPT | Generic dedicated disk |
| x86-64 | BIOS/GPT or BIOS/MBR | Generic dedicated disk |
| x86-64 | UEFI/GPT with existing rEFInd | Intel Apple preservation |
| AArch64 | UEFI/GPT | Generic dedicated disk, including an ARM VM |

A generic ARM target must boot ordinary AArch64 NixOS installation media and expose
supported Linux devices. This is not bare-metal Apple Silicon, 32-bit ARM, or
board-specific boot-image support. See the [Parallels test guide](docs/parallels.md)
for an ARM VM on an Apple Silicon host. Validate the guest devices and presentation
mode before relying on that installation. No cross-architecture override is provided.

## Applications and presentation

| Managed application | Headless | X11 | Wayland |
| --- | --- | --- | --- |
| None: terminal and managed NixOS only | Yes | Yes | Yes |
| OpenCode | Yes | Yes | Yes |
| OpenClaw, including Codex and OpenCode tools | Yes | Yes | Yes |
| ChatGPT Remote | No | Yes | Not currently supported |

These are configuration targets on both architectures, not certification of every
hardware/application combination. Exactly zero or one Assbox application profile is
selected. Extra tools do not create another managed application profile.

**ChatGPT Remote works on Linux and is the primary purpose of the ChatGPT profile.**
Assbox requires X11 for this application; a headless profile can be added when an
implementation can be supported and tested. Linux support is not a future feature.
The generic graphical alternatives are LightDM/Xorg/Openbox and
greetd/labwc/Wayland. Both include a terminal. Headed OpenCode opens its attached
terminal UI; headed OpenClaw opens its loopback Control UI after onboarding.

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

Start with [development](docs/development.md). A source checkout without a genuine
`flake.lock` is a bootstrap candidate, not an installable release. Initial bootstrap resolves the lock with Nix. Scheduled maintenance verifies
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
