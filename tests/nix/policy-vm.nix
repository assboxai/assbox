# SPDX-License-Identifier: GPL-3.0-or-later
# Disposable Linux integration only. Does not emulate Mac firmware or boot macOS.
{ pkgs, module }:
let
  arm = pkgs.stdenv.hostPlatform.system == "aarch64-linux";
  iso = pkgs.runCommand "assbox-optical-test.iso" { nativeBuildInputs = [ pkgs.xorriso ]; } ''
    mkdir contents
    printf 'disposable non-bootable optical fixture\n' > contents/fixture
    xorriso -as mkisofs -quiet -V ASSBOX_TEST_MEDIA -o "$out" contents
  '';
in
pkgs.testers.runNixOSTest {
  # Assbox configures unfree consent and redistributable firmware per machine.
  node.pkgsReadOnly = false;
  name = "assbox-policy-and-storage-adapters";
  requiredFeatures.kvm = !arm;
  nodes.machine = { lib, ... }: {
    imports = [ module ];
    assbox.enable = true;
    assbox.updates.enable = false;
    assbox.presentation = "headless";
    assbox.components = { };
    boot.loader.systemd-boot.enable = lib.mkForce arm;
    boot.loader.grub.enable = lib.mkForce false;
    systemd.services.assbox-boot-check.enable = lib.mkForce false;
    # The test driver provides console access; production accounts remain locked.
    users.allowNoPasswordLogin = true;
    users.users.root.hashedPasswordFile = lib.mkForce null;
    users.users.admin.hashedPasswordFile = lib.mkForce null;
    users.users.admin.hashedPassword = lib.mkForce "!";
    virtualisation = {
      memorySize = 2048;
      emptyDiskImages = [
        512
        512
        64
      ];
      useEFIBoot = arm;
      useBootLoader = arm;
      diskSize = 8192;
      qemu.forceAccel = pkgs.lib.mkForce (!arm);
      qemu.options = [
        "-device virtio-scsi-pci,id=assbox-scsi"
        "-drive if=none,id=assbox-iso,media=cdrom,readonly=on,format=raw,file=${iso}"
        "-device scsi-cd,bus=assbox-scsi.0,drive=assbox-iso"
      ];
    };
    environment.systemPackages = with pkgs; [
      jq
      util-linux
      e2fsprogs
      dosfstools
      exfatprogs
      gptfdisk
    ];
    system.stateVersion = "26.05";
  };
  testScript = ''
    import json
    import shlex

    machine.start()
    machine.wait_for_unit("multi-user.target")
    machine.wait_for_unit("NetworkManager.service")
    machine.succeed("assbox --version")
    machine.succeed("command -v just rg perl python3 bash sed awk curl")
    machine.fail("test -e /etc/justfile")
    machine.fail("systemctl is-enabled display-manager.service")
    machine.fail("systemctl is-enabled udisks2.service")
    machine.succeed("test $(id -Gn agent | tr ' ' '\\n' | grep -Ec '^(wheel|disk|input|docker|networkmanager)$') -eq 0")
    machine.succeed("test $(stat -c %a /var/lib/assbox) = 700")
    runtime = json.loads(machine.succeed("cat /etc/assbox/runtime.json"))
    assert runtime["selectedComponents"] == []
    assert runtime["presentation"] == "headless"
    assert runtime["updates"]["calendar"] == "*-*-* 18:00:00"

    # Real filesystem tools on disposable loop images; checks must not alter bytes.
    for filesystem, make, check in [
        ("ext4", "mkfs.ext4 -F", "e2fsck -f -n"),
        ("vfat", "mkfs.fat", "fsck.fat -n"),
        ("exfat", "mkfs.exfat", "fsck.exfat -n"),
    ]:
        image = "/tmp/assbox-" + filesystem + ".img"
        machine.succeed("truncate -s 64M " + image)
        machine.succeed(make + " " + image)
        before = machine.succeed("sha256sum " + image).split()[0]
        machine.succeed(check + " " + image)
        assert machine.succeed("sha256sum " + image).split()[0] == before
        machine.succeed("mkdir -p /mnt/fs-check; mount -o loop " + image + " /mnt/fs-check")
        machine.succeed("printf retained > /mnt/fs-check/sentinel; sync; umount /mnt/fs-check")
        machine.succeed("mount -o loop,ro " + image + " /mnt/fs-check")
        machine.succeed("grep retained /mnt/fs-check/sentinel")
        machine.fail("touch /mnt/fs-check/forbidden")
        machine.succeed("umount /mnt/fs-check")

    architecture = machine.succeed("uname -m").strip()
    assert architecture == "${if arm then "aarch64" else "x86_64"}"
    uefi = machine.succeed("if test -d /sys/firmware/efi; then echo yes; else echo no; fi").strip() == "yes"
    assert uefi == ${if arm then "True" else "False"}

    # The live-media mounts below are synthetic, not the medium that booted the
    # VM. Optical tests exercise the actual rom/ISO9660 Linux block-device shape.
    if uefi:
        machine.succeed("printf 'label: gpt\\nsize=128M,type=U\\ntype=L\\n' | sfdisk /dev/vdb")
        root, esp = "/dev/vdb2", "/dev/vdb1"
        machine.succeed("udevadm settle; mkfs.fat -F32 " + esp)
    else:
        machine.succeed("printf 'label: dos\\nstart=2048,type=83\\n' | sfdisk /dev/vdb")
        root, esp = "/dev/vdb1", None
    machine.succeed("printf 'label: gpt\\ntype=L\\n' | sfdisk /dev/vdc")
    machine.succeed("udevadm settle; mkfs.ext4 -F " + root + "; mkfs.exfat /dev/vdc1")
    machine.succeed("mkfs.ext4 -F /dev/vdd; mkdir -p /iso")
    machine.succeed("mkdir -p /dev/disk/by-id; ln -s /dev/vdb /dev/disk/by-id/assbox-vm-target")
    before = machine.succeed("sha256sum /dev/vdb /dev/vdc")
    answers = [root] + ([esp] if esp else []) + ["/dev/vdc1", "assbox-vm", "UTC", "generic",
                   "custom", "none", "n", "n", "headless", "n", "internet", "none", "y",
                   "n", "n", "n", "n", "n", "n", "none", "n", "none"]
    text = "\n".join(answers) + "\n"
    machine.succeed("printf %s " + shlex.quote(text) + " > /tmp/assbox-answers")
    for source, kind in [("/dev/vdd", "Disk"), ("/dev/sr0", "Optical")]:
        machine.succeed("mount -o ro " + source + " /iso")
        hardware = machine.succeed("assbox internal hardware")
        assert kind in hardware
        machine.succeed("script -q -e -c 'assbox install' /tmp/assbox-plan.log < /tmp/assbox-answers")
        machine.succeed("grep 'Plan only' /tmp/assbox-plan.log")
        assert machine.succeed("sha256sum /dev/vdb /dev/vdc") == before
        machine.succeed("umount /iso")
  '';
}
