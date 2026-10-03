# SPDX-License-Identifier: GPL-3.0-or-later
# Synthetic evaluation/build fixture. These identifiers do not describe a real machine.
{
  config,
  lib,
  pkgs,
  ...
}:
{
  assbox.enable = true;
  networking.hostName = "assbox-ci";
  time.timeZone = "Etc/UTC";
  assbox.boot.disk = "/dev/disk/by-id/assbox-ci-disk";
  boot.initrd.availableKernelModules = [
    "virtio_pci"
    "virtio_blk"
    "virtio_scsi"
    "sd_mod"
    "sr_mod"
  ]
  ++ lib.optionals (pkgs.stdenv.hostPlatform.system == "x86_64-linux") [ "ahci" ];
  fileSystems."/" = {
    device = "/dev/disk/by-label/ASSBOX_CI_ROOT";
    fsType = "ext4";
  };
  fileSystems."/boot/efi" =
    lib.mkIf
      (builtins.elem config.assbox.boot.mode [
        "uefi"
        "apple-refind"
      ])
      {
        device = "/dev/disk/by-label/ASSBOX_CI_ESP";
        fsType = "vfat";
      };
  swapDevices = [ ];
  system.stateVersion = "26.05";
}
