# SPDX-License-Identifier: GPL-3.0-or-later
{
  config,
  lib,
  pkgs,
  ...
}:
let
  cfg = config.assbox;
  apple = pkgs.stdenv.hostPlatform.system == "x86_64-linux" && cfg.boot.mode == "apple-refind";
  bios = pkgs.stdenv.hostPlatform.system == "x86_64-linux" && lib.hasPrefix "bios-" cfg.boot.mode;
in
{
  config = lib.mkIf cfg.enable (
    lib.mkMerge [
      {
        assertions = [
          {
            assertion =
              pkgs.stdenv.hostPlatform.system != "aarch64-linux"
              || (cfg.platform == "generic" && cfg.boot.mode == "uefi");
            message = "AArch64 requires generic UEFI/GPT; no BIOS, Intel Apple or board-specific boot backend is supported.";
          }
          {
            assertion = !(apple || bios) || lib.hasPrefix "/dev/disk/by-id/" cfg.boot.disk;
            message = "BIOS/Apple boot requires a stable whole-disk by-id binding.";
          }
          {
            assertion = (cfg.platform != "generic") == apple;
            message = "Intel Apple preservation profiles require the Apple rEFInd boot strategy.";
          }
        ];
        boot.loader.timeout = 8;
        boot.loader.efi.efiSysMountPoint = "/boot/efi";
        boot.loader.efi.canTouchEfiVariables = !apple && !bios;
      }
      (lib.mkIf (cfg.boot.mode == "uefi") {
        boot.loader.systemd-boot.enable = true;
        boot.loader.systemd-boot.configurationLimit = cfg.boot.generations;
        boot.loader.grub.enable = false;
      })
      (lib.mkIf bios {
        boot.loader.systemd-boot.enable = false;
        boot.loader.grub = {
          enable = true;
          device = cfg.boot.disk;
          efiSupport = false;
          useOSProber = false;
          configurationLimit = cfg.boot.generations;
        };
      })
      (lib.mkIf apple {
        boot.loader.systemd-boot.enable = false;
        boot.loader.grub = {
          enable = true;
          efiSupport = true;
          efiInstallAsRemovable = false;
          useOSProber = false;
          copyKernels = false;
          configurationLimit = cfg.boot.generations;
          mirroredBoots = [
            {
              path = "/boot";
              devices = [ "nodev" ];
              efiSysMountPoint = "/boot/efi";
              efiBootloaderId = "Assbox";
            }
          ];
        };
      })
    ]
  );
}
