# AArch64 development and acceptance in Parallels

This is a test procedure, not a claim of completed Parallels certification.
The guest is a generic AArch64 UEFI machine; the Apple Silicon host's bare-metal
boot chain and hardware drivers are out of scope.

## Guest preparation

Use the current minimal **64-bit ARM/AArch64** image from the
[official NixOS downloads](https://nixos.org/download/), not the x86-64 image and not
a board-specific SD-card image. Parallels documents installing ARM Linux from an
ARM ISO in its [Linux installation guidance](https://kb.parallels.com/en/128445).
That general capability is not vendor certification of this Assbox configuration.

Create a disposable ARM Linux VM with UEFI firmware and an attached read-only ISO.
Add distinct virtual disks for the installation target and external boot backup.
Use normal virtual storage/network devices recognized by the stock live image.
Do not pass through a host physical disk. Disable unnecessary host-folder sharing
and never expose host credentials for an installer test. A host snapshot is useful
for test reset, not a substitute for independent backups.

Provide enough target disk space for packages, build intermediates and retained
generations; see [build capacity](installation.md#build-capacity). The full build
uses that disk. Authentication/evaluation and the running compiler still need RAM;
no tested minimum is claimed.
The backup needs space for complete ESP/boot metadata, not merely the partition
list. Distinct guest disks may still share one physical host disk.

Boot the ISO and inspect, without writing:

```sh
uname -m                       # Must report aarch64
test -d /sys/firmware/efi        # Must succeed
findmnt /iso
lsblk -o NAME,TYPE,SIZE,RO,FSTYPE,MOUNTPOINTS
```

An attached ISO normally appears as a read-only `rom` device, but use observed
paths, not assumed `/dev/sr0`, `/dev/sda` or `/dev/vda` names. The installer also
accepts a clearly identified local installer disk. Ambiguous loop/network sources
are refused. If storage or networking is not recognized by the stock live image,
stop and investigate rather than claiming the generic profile supports it.

Prepare the disposable target as GPT with exactly one empty FAT ESP and one empty
ext4 root; prepare a backup partition on the other virtual disk. Formatting is a
separate administrator operation, not an Assbox command. Unmount every partition
of both disks. Record the layout before invoking the installer.

## Bootstrap and install

First resolve/review the project's real lock and pass native build/verification
checks in an AArch64 Linux environment. The package and dev shell select
`aarch64-linux` automatically. The current release gate also requires the full
end-to-end tests described in [verification](verification.md).

Use the reviewed native executable and installation procedure in
[installation](installation.md#native-binary-and-source-identity). Run plan-only
first. Choose `generic`, `none`, `headless`, and the intended local timezone/SSH
public key. With explicit authorization, run `--apply` against the disposable VM.
Record the immutable source identity, built system path, commands and real results.
No host hardware configuration is committed to the public repository.

Disconnect the installation ISO before the acceptance boot and select the installed
virtual target disk. Do not mistake a successful reboot into the live ISO for a
successful installation.

## Acceptance sequence

Start with `none`/headless: verify target boot, console/admin login, key-based SSH
when enabled (and no TCP/22 listener for console-only),
networking, architecture, hostname and an ordinary `/etc/nixos` flake. Check
`assbox status`, then package add/remove, rebuild, staged update, reboot and retained
generation selection. Exercise failed builds and the documented recovery paths on
snapshots. Never equate a plan-only pass with a successful installation.

Next test OpenCode/headless and OpenClaw/headless, including real provider login and
authenticated client tasks. Test `none`/Wayland and `none`/X11 separately before
headed applications. Validate virtual GPU behavior, terminal input, display scale,
automatic session startup, shutdown and restart. ChatGPT/X11 comes last, with actual
Linux Remote authentication and an end-to-end task. A package evaluating on ARM is
not evidence its graphical runtime works in this VM.

Parallels Tools, shared-folder integration and automatic display resizing are not
configured by Assbox. Record missing guest-driver/integration features as test
results, not as evidence about bare-metal Apple Silicon support. Keep host and guest
updates/backups independently managed.

CI's ARM storage VM can use software emulation when nested acceleration is absent.
It tests generic QEMU behavior, not Parallels graphics, firmware or product-specific
integration. Both test environments have distinct acceptance value.
