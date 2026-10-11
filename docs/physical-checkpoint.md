# Physical x86 checkpoint

The physical checkpoint is one hybrid x86-64 live image for early hardware and
application testing. It boots as a legacy BIOS disk or as UEFI USB media, includes
the Assbox CLI, Codex and Happier, and does not modify internal storage. It is a
development artifact, not an authenticated `r-N` installer or an update source.
The included Assbox binary has a bounded diagnostic tool closure; install, update,
rebuild and recovery operations are deliberately unavailable in this image.

The image enforces the wired-only test boundary from the start of the Linux boot.
Wi-Fi, Bluetooth and the other radio classes are blocked; wireless, sound,
microphone and camera kernel modules are denied; wired networking cannot start until
the device-policy check succeeds. SSH, sudo and polkit are disabled; root is locked
and the upstream installer account is absent. The local console auto-logs into an
unprivileged `agent`. The live session reaches its readiness marker only after it
finds a wired Ethernet interface and confirms that no denied device initialized:

```console
$ systemctl status assbox-device-policy-check.service
$ systemctl status assbox-physical-checkpoint-readiness.service
$ cat /run/assbox-checkpoint/readiness.json
```

A successful status applies after the Linux kernel has taken control. Firmware can
power or initialize radio, microphone or camera hardware before that point. When
the prohibition must also cover firmware and the boot menu, disable the devices in
firmware or with a hardware switch, or physically disconnect/remove the applicable
hardware. Software in the live image cannot attest to that earlier interval.

Connect the Ethernet cable before boot. Readiness also requires carrier on at
least one wired interface; an unplugged adapter does not satisfy the gate. Do not
attach USB radio, audio-capture or camera devices during the session.

## Artifact qualification

The source exposes the image as `packages.x86_64-linux.physical-checkpoint-iso`.
Its check builds the exact image. A second KVM check boots those same bytes through
both paths used by the target machines: a hybrid legacy BIOS disk and UEFI firmware
with USB mass storage. Both guests must reach the serial readiness marker.

```sh
nix build .#checks.x86_64-linux.physical-checkpoint-boot
```

Published checkpoint releases use an immutable `-dev` prerelease. Verify the
release's recorded SHA-256 and its GitHub Sigstore build-provenance bundle before
writing the ISO. The prerelease must identify the exact core commit, lock digest,
workflow commit, build architecture, image digest, BIOS result and UEFI result.
Those checks qualify the published bytes for live testing only.

## Target machines

The legacy PC must have an x86-64 CPU and boots the image directly from its firmware
USB menu. Disable any built-in radio in firmware or by its physical switch before
inserting the medium.

The PC's eventual Assbox installation will reside entirely on an external USB
drive. That installed drive is separate from both the live installation medium and
the required boot-backup disk. Before qualifying installation, verify its stable
whole-disk `/dev/disk/by-id` identity, the USB controller and storage drivers in the
installed initrd, and a cold BIOS boot after removing the live medium. Capture the
internal disk's identity and partition layout before and after installation and
confirm that it was not selected or changed. Live USB boot alone does not qualify
booting an installed external USB root; that remains a separate installer gate.

MacBookPro11,1 uses its UEFI path. [Apple's hardware specification](https://support.apple.com/en-us/111946)
lists its Wi-Fi, Bluetooth, dual microphones and FaceTime HD camera, and offers
Ethernet through an adapter rather than a built-in port. Use a supported
Thunderbolt-to-Ethernet or USB-to-Ethernet adapter and connect the cable before
boot. Qualify the same signed ISO twice: first hold Option at power-on and select
the EFI USB entry directly, then boot that USB entry through the installed rEFInd.
Capture the readiness JSON and boot result separately for each path; one path does
not stand in for the other. The image itself does not depend on rEFInd and neither
run touches macOS or its recovery data. If the pre-Linux interval is within the
device threat boundary, disconnect the internal wireless and microphone hardware
before both boots because Apple firmware and rEFInd do not provide Assbox's kernel
policy. Apply the same physical rule to the camera if it is in scope.

Installed-system acceptance must also qualify the MacBookPro11,1 through both
direct Apple EFI and rEFInd, with separate boot results. The guided installer
offers direct EFI for a dedicated target with an empty ESP and rEFInd preservation
for an existing shared target. Both installed routes still require qualification. A successful
direct boot of this live ISO does not complete that installed-system requirement.

Once the readiness file reports `passed: true`, run `assbox`, `codex --version`,
and `happier --version`. Provider authentication in the live session is ephemeral;
do not treat it as an installed-state or update test. Save the source revision,
machine model, PCI/USB Ethernet identity, readiness JSON and any failures outside
the source tree.

Do not erase either machine from this checkpoint. Disk installation remains gated
on a separately authenticated `r-N` release, prepared target/backup storage and the
normal installer acceptance path.
