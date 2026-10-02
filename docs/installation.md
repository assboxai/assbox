# Prepared-storage installation

> **Instance selection:** The wizard starts with Assistant, Coder, Kiosk or Custom. Native Kiosk with None requests no local execution and stays inactive until each app is qualified. Protected Code explicitly uses the [managed worker](worker/controller-model.md). External Mac Desktop SSH uses a standalone VM; no inner worker is required.

Read the [security model](../SECURITY.md) and [verification requirements](verification.md)
first. This document describes the installer contract, not a hardware certification.
Never use a source-only bootstrap candidate on valuable disks.

## End-user sequence

1. Back up existing data. Prepare the supported empty Linux partition(s) and a
   separate backup disk. On Intel Macs, do the partition preparation from macOS
   and install/test rEFInd first.
2. Boot matching-architecture NixOS live media and establish networking. Obtain
   the trusted native Assbox executable and select an authenticated release as
   described below. There is no separate minimal-NixOS installation step.
3. Run the Assbox wizard, select the prepared root/ESP/backup, choose the machine
   settings and inspect the plan. Applying the plan asks for the exact disk
   confirmation and administrator credentials.
4. Leave the live session running while Assbox verifies the backup, builds on the
   target disk and installs the bootloader. Follow an explicit retry prompt only
   after correcting a build problem; interruptions have the limits described below.
5. Disconnect the live medium and boot the installed disk (through rEFInd on an
   Intel Mac). Log in as administrator and complete application onboarding.

The same flow applies to every supported machine. It produces an ordinary
`/etc/nixos` configuration ready for normal NixOS administration; a copied Git
checkout and a second setup wizard are not required.

## Arrangement and access choices

The purpose-first wizard resolves explicit host and worker selections. Native None requests no local execution and stays staged until exact policy qualification. Protected Code explicitly selects a worker and its required coding tools. External Desktop SSH uses a standalone instance.


Components and presentation remain independent. Select `codex,chromium` with
X11/Openbox or Wayland/labwc for a standalone coding machine with a manual browser.
Select `chromium` in autostart only if it should open automatically. Headless
Chromium selection is refused. Additional standalone tools use ordinary nixpkgs
attributes, such as `htop,python3Packages.requests`, and populate the existing
`assbox-packages.nix` file. They are not permitted on a thin controller.

Happier pairing and each provider login are separate owner steps after installation. Agent selections do not create a backend security allowlist or import other accounts.


A managed worker presents recommended RAM/CPU and **automatic persistent disk
capacity** as a group; customize only when needed. Automatic sizing builds the
provisional system/image first, measures the target disk, reserves controller
recovery space and the full writable root, then builds and publishes the concrete
configuration. The provisional system is never activated. The displayed plan
therefore cannot promise an exact capacity before the build. The durable target
installation record preserves the requested and final configuration digests.
See [storage and network choices](worker/operations.md#capacity-and-network-policy).

Workload SSH uses the unprivileged `agent` account and does not require VS Code or
Zed. Administrator SSH uses `admin`. Both share one listener/exposure policy:
Tailscale requires enrollment from the installed console; LAN requires explicit
interfaces and offers optional source CIDRs. With no source restrictions, all
sources reaching those interfaces can attempt key authentication. The wizard shows
live-media addresses as observations, not permanent installed addresses.

After boot, `/etc/assbox/connection-guide.txt` records the installation choices,
host-key verification procedure, SSH alias template and remote Codex setup.
Verify the installed address and host fingerprint at the trusted console before
connecting. The guide reflects installation-time choices; update it alongside
later manual access changes. See the [Parallels walkthrough](parallels.md) for
macOS control and its distinct qualification gates.

## Supported shapes

The native executable and running kernel must agree: `x86_64` or `aarch64`.
AArch64 requires generic UEFI and GPT. x86-64 additionally supports BIOS/GPT,
BIOS/MBR and the separate Intel Apple/rEFInd profile. Unsupported architectures,
ARM BIOS and ARM Intel-Apple selections fail before installation writes.

Use trusted matching-architecture NixOS live installation media. `/iso` must resolve
to an ordinary local disk/partition, or a read-only optical ISO9660/UDF block device.
A loop-backed ISO, network root or mapped/ambiguous source is not supported.
An optical medium does not need a fictitious physical parent disk.

The target and backup must be distinct whole disks, neither containing the installer.
Every partition on both must be unmounted and free of active holders. The selected
root is an empty ext4 partition. Backup may be ext4, FAT or exFAT. Duplicate filesystem
UUIDs/PARTUUIDs, read-only targets and hybrid partition tables are refused.

| Boot strategy | Prepared target |
| --- | --- |
| Generic UEFI, either architecture | GPT; one empty ext4 root and one empty FAT ESP, no other partitions |
| BIOS/GPT, x86-64 | ext4 root and one unformatted BIOS Boot Partition of at least 1 MiB |
| BIOS/MBR, x86-64 | one primary Linux ext4 partition starting at or after 1 MiB |
| Intel Apple/rEFInd | GPT; empty ext4 root; existing FAT ESP/rEFInd; retained partitions untouched |

BIOS and Intel Apple installation require an unambiguous whole-disk `/dev/disk/by-id`
identity. UEFI may bind filesystems by UUID when the virtual disk lacks a stable
by-id name. These are layout rules, not capacity recommendations: provide enough
root space for installed packages, retained generations, builds and application data.
ESP capacity must accommodate the configured boot-menu generations.

The installer never creates a partition table, erases a filesystem, shrinks a volume
or repairs filesystem damage. Prepare storage separately and inspect it before
selecting anything. Do not use the generic dedicated-disk path for arbitrary
existing-OS dual boot.

## Native binary and source identity

First establish a trusted native verifier from an explicitly reviewed core commit
and its genuine lock, after the actual release gates pass. This initial verifier
is a bootstrap trust anchor; do not evaluate a moving branch and call the result
authenticated. Follow the [verification contract](verification.md) before treating
a release as installation-approved.

On matching-architecture NixOS live media, with a trusted `assbox` executable already
available, verify a real release tag into a new root-owned directory:

```sh
# Select an actual authenticated release; a tag alone is not a signature.
: "${RELEASE:?Set RELEASE to an actual published r-N tag}"
sudo assbox release verify "$RELEASE" /var/lib/assbox-verified-install
source=$(sudo cat /var/lib/assbox-verified-install/verified-source-path)
nix build --no-update-lock-file --no-write-lock-file "path:$source#assbox"
sudo ./result/bin/assbox install --release "$RELEASE"
# A separate invocation authorizes writes, after reviewing the plan:
sudo ./result/bin/assbox install --release "$RELEASE" --apply
```

The verified source path is a Nix-store path, not an arbitrary downloaded script.
Verification does not install anything or establish a machine's replay watermark.
Installation repeats verification and requires its binary's embedded core commit to
match the manifest. Applying installation always requires an explicit release tag;
only an installed machine with durable replay state may use `latest` for discovery.
An unversioned development binary, unprovisioned trust IDs, unsynchronized clock or
expired release cannot apply.

The wizard is plan-only without `--apply`. It requests prepared partitions,
hostname/timezone, profile, arrangement, components, presentation, explicit autostart
and device policy. Standalone installations can add validated nixpkgs package
attributes and independently enable workload SSH. Administrator and workload
public keys are separate choices. Supplying either enables key-only SSH with
explicit Tailscale or LAN exposure; supplying neither leaves sshd disabled. Multicast discovery is separately
configurable and defaults off. An exact whole-disk confirmation is required before
proceeding. Credentials are obtained separately, never inserted in Nix source or
command arguments.

The release tarball and lock are authenticated before Nix metadata/evaluation. The
machine's ordinary flake pins the exact immutable release asset with its NAR hash;
there is no moving branch or `--source` bypass. Future Assbox updates authenticate
a new immutable release before changing that pin. Direct NixOS administration is
still available for separately trusted custom sources, outside this automatic
release policy. See [release authentication](release-authentication.md).

## Before the first target write

All selected filesystems receive unmounted, non-repairing checks: `e2fsck -f -n`,
`fsck.fat -n`, or `fsck.exfat -n`. Missing tools, nonzero results and existing mounts
stop installation. Root is then inspected read-only with journal replay disabled;
the ESP is also inspected read-only. Existing root contents are refused.

The installer generates the complete local configuration under
`/run/assbox-install/machine`, carries the one resolved lock, evaluates policy,
and snapshots the exact configuration bytes. It then creates and reads back the
external boot backup.
The archive includes partition-table/boot metadata and, where applicable, the ESP.
On ext4 recovery directories/files use 0700/0600; FAT/exFAT use restrictive mount
masks. Backup is remounted read-only for verification of every artifact and the
checksum manifest bytes.

Administrator/network credentials are collected before target writes and never
enter Nix source. A separate `<backup-name>-install-intent.json` is written and
read back beside the immutable backup archive. It identifies the operation,
selected storage, release manifest, configuration digest and backup name.

## Building and boot activation

Only then is the target root mounted writable. Assbox records `target-writes` in
`/.assbox-install.json`, copies the prepared configuration and private credentials,
then records `building`. Nix uses the target's `/nix/store` and
`/var/tmp/assbox-build`; it can reuse trusted paths from the live store. The ESP
remains read-only. Logs are private files under `/var/log/assbox-install` on the
target, and the live terminal prints their paths and the transient service name.

Before activation, Assbox rechecks storage identities, owned mounts, configuration
bytes, release freshness and the built generation's immutable architecture/boot/
storage receipt. Receipt lookup uses the target store. It records `activating`
before making the ESP writable and invoking standard `nixos-install --system`
with that exact closure. There is no second flake resolution or second OS build.
Final partition-table, firmware, ESP and backup checks precede `complete`.

## Build capacity

The full system and build intermediates live on the target disk, so they need not
fit in a live ISO's RAM-backed writable store. Authentication, source acquisition
and evaluation still use live state, and compilers still need working memory.
Provide adequate root space for builds, packages, generations and application data;
there is no measured minimum RAM/storage claim. Start hardware acceptance with
`none`/headless before testing the desired application.

Assbox does not cap build concurrency, raise agent priorities or protect agents
from the OOM killer. Installed-system resource behavior uses upstream build
parallelism, relative background weights and zram; see [resources](resources.md).
Disk-backed builds reduce live-store pressure without guaranteeing that every
workload will fit in RAM or preventing all OOM failures.

## Intel Apple preservation

The guided installer accepts the observed models `MacBookPro11,1` and
`MacBookPro12,1`, using their matching profiles. It refuses other Apple models,
including T2 Macs, and refuses selecting a generic or different Mac profile to
bypass that decision. The `apple-intel` NixOS module option remains available for
separately reviewed expert configurations; it is not a guided-install support claim.
See the [Intel Mac acceptance guide](intel-mac-acceptance.md).

Before planning, the wizard displays the observed model, PCI network IDs and live
wireless drivers. Requested Wi-Fi requires a wireless interface bound to an in-tree
driver; `wl` and out-of-tree modules do not qualify. A BCM4360 adapter is reported
even when no driver is bound. Use Ethernet with Wi-Fi disabled, or establish a
supported external Wi-Fi adapter on the live medium and restart planning. The
installer does not add an insecure-driver exception. Having a live interface is a
prerequisite, not proof of target-kernel, access-point or provider compatibility.
Model, network-device and driver observations are rechecked alongside storage before
writes; unplugging or changing adapters invalidates the plan. After target writes,
follow the recovery procedure before attempting another installation. No SSID, password or
MAC address is part of this hardware observation.

Create actual physical free partitions using macOS tools beforehand. Adding an APFS
volume is not the same operation. Linux partition tools must not resize or repair
APFS/HFS+/CoreStorage/Recovery/Boot Camp or replace the shared ESP. Retained partitions
are not mounted. The prerequisite is an ordinary file at `EFI/refind/refind_x64.efi` with an
x86-64 PE32+ EFI-application header, not a filename substring. Other rEFInd layouts
require explicit expert preparation; the installer does not relocate them. A header
check is a format/precondition check, not proof that firmware will boot it. The
existing loader is preserved, and Assbox's Apple loader
is confined to `EFI/Assbox` on the ESP (with GRUB support files on the Linux root).
EFI-variable writes are disabled and reported
firmware/unrelated ESP state is checked around boot operations.

Boot the live medium from rEFInd, complete the same wizard, then use rEFInd to
select the Assbox loader. Confirm both Assbox and the existing macOS installation
boot before retiring rescue media. Firmware discovery and device drivers still
require acceptance on the specific supported machine.
The shared-ESP checks detect unexpected changes; they cannot make loader writes
atomic or restore an interrupted boot operation automatically. Installation from
live media does not change the installed runtime privilege or update policy.

This is Intel Mac support only. An AArch64 VM running on an Apple Silicon Mac uses
generic guest UEFI; it neither configures nor boots the host's Apple boot ecosystem.

## Failure and recovery limits

| Last boundary | What a failure means |
| --- | --- |
| Before target writes | Target bytes remain unchanged; live work and external backup files may exist. |
| `target-writes` or `building` | Linux root may be incomplete; Assbox has not activated a bootloader. |
| `activating` | Boot files/profile may be partially changed; inspect from rescue media. |
| `complete` | Installation and its final checks finished; actual disk boot and application acceptance are still required. |

A failed build offers an explicit retry only in the same live process. Correct the
network/space problem and answer `y` to retry the same release and configuration.
Changes to configuration, device identity, mount ownership or release validity
refuse retry. Noninteractive runs do not retry. Activation failures never trigger
an automatic build/activation retry.

Ctrl-C, termination and hangup cancel the installer. It stops and reaps owned
build/install cgroups before releasing mounts. If systemd cannot confirm that a
writer stopped, the installer retains ownership and reports the problem. SIGKILL,
power loss or disappearing hardware can bypass cleanup; inspect before acting.
Owned-mount cleanup refuses to unmount a replacement it cannot identify.

After a process restart, any installation record or other unexpected root content
is refused, including malformed records. Neither deleting a record nor copying an
old intent back authorizes resume. Preserve the external backup, target record,
configuration and logs for inspection. If the root is damaged or a record is
missing, treat its phase as uncertain. See [installation recovery](install-recovery.md)
for an inspection procedure. Restarting from an empty root is an explicit storage
preparation decision, never an automatic Assbox repair or rollback.

`assbox recover` handles installed-machine management journals, not initial disk
restoration. Boot backups do not include all personal data. A virtual backup disk
inside the same host is useful for testing but is not independent disaster recovery.
After success, disconnect the ISO/live media, boot the selected disk and complete
[hardware/application acceptance](verification.md). Keep independent backups.

## Prepared-root contents and disk confirmation

An empty root can contain only `lost+found`, and only when that entry is an empty,
ordinary root-owned/root-group directory on the same filesystem, without writable
group/other or special permission bits. Recovered files inside it, symlinks, regular
files with that name, unexpected ownership and extra root entries are refused.
The installer neither removes nor repairs those contents. Inspect and back up the
data, then prepare an actually empty filesystem before trying again.

The disk list and final plan show whole-disk model, serial, exact byte capacity,
current device number and `/dev/disk/by-id` identity when available. Root and ESP
are displayed under their target disk, and the backup disk is labeled separately.
Missing device metadata is shown as unavailable, never invented. Control characters
in device-supplied text are escaped instead of being sent to the terminal.
The final typed phrase names the whole target disk's by-id identity, or its device
path/number/capacity when none exists, plus the chosen hostname. This human check
supplements identity re-observation; it is not a cryptographic hardware identity.
