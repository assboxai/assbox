# Prepared-storage installation

Read the [security model](../SECURITY.md) and [verification requirements](verification.md)
first. This document describes the installer contract, not a hardware certification.
Never use a source-only bootstrap candidate on valuable disks.

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
hostname/timezone, profile, application, presentation, device policy and an optional
admin SSH public key. Supplying a key enables key-only SSH; choosing console-only
disables sshd and its firewall port by default. Multicast discovery is separately
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
and builds the exact NixOS system in the live environment. It validates the built
generation's immutable architecture/boot/storage receipt against the install plan.
Only after this succeeds does it create and read back the external boot backup.
The archive includes partition-table/boot metadata and, where applicable, the ESP.
On ext4 recovery directories/files use 0700/0600; FAT/exFAT use restrictive mount
masks. Backup is remounted read-only for verification of every artifact and the
checksum manifest bytes.

Only then is the target mounted writable. The prepared configuration and private
credentials are copied, and `nixos-install --system` installs that exact prebuilt
system. It does not rebuild from a newly resolved flake after the boundary.
Identities and mount ownership are rechecked near consequential operations; final
table/firmware/ESP checks precede completion. Before the boundary, failures leave
the target unchanged; writes to live working state and the external backup are
separate from target writes.

## Live-store capacity

The full prebuild uses the live environment's Nix store, not the uncommitted target.
Stock ISO environments can have a RAM-backed writable store. A graphical/app closure
and uncached builds can therefore exceed a small VM's or old laptop's live memory.
This design does not claim a tested minimum RAM or storage budget. Allocate adequate
live-store capacity, inspect `findmnt -T /nix/store` and `df -h /nix/store`, and test
`none`/headless first. An out-of-space/build failure before the write boundary leaves
the target untouched.

Assbox does not yet provision a disk-backed scratch build store. Do not work around
this by mounting an empty disk over `/nix` or by making the selected target writable
behind the installer's back. A supported low-memory scratch-store path needs its
own isolation, capacity and recovery tests. This limitation must be resolved/tested
for memory-constrained hardware before advertising it as installation-ready.

## Intel Apple preservation

Create actual physical free partitions using macOS tools beforehand. Adding an APFS
volume is not the same operation. Linux partition tools must not resize or repair
APFS/HFS+/CoreStorage/Recovery/Boot Camp or replace the shared ESP. Retained partitions
are not mounted. The prerequisite is an ordinary file at `EFI/refind/refind_x64.efi` with an
x86-64 PE32+ EFI-application header, not a filename substring. Other rEFInd layouts
require explicit expert preparation; the installer does not relocate them. A header
check is a format/precondition check, not proof that firmware will boot it. The
existing loader is preserved, and Assbox's Apple loader
is confined to its own directory. EFI-variable writes are disabled and reported
firmware/unrelated ESP state is checked around boot operations.

This is Intel Mac support only. An AArch64 VM running on an Apple Silicon Mac uses
generic guest UEFI; it neither configures nor boots the host's Apple boot ecosystem.

## Failure and recovery limits

After target writes begin, installation is not a transaction across power loss.
Keep the external backup and live media, inspect the error and mounted devices, and
do not blindly retry or delete work state. Ambiguous partially installed roots are
refused; automatic install resume/restore is not provided. Owned-mount cleanup is
attempted even when post-mount observation fails, but if ownership cannot be proven
it reports manual inspection rather than unmounting an unknown replacement.

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
