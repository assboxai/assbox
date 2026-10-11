# SPDX-License-Identifier: GPL-3.0-or-later
{
  config,
  lib,
  pkgs,
  ...
}:
let
  cfg = config.assbox;
  apple =
    pkgs.stdenv.hostPlatform.system == "x86_64-linux"
    && builtins.elem cfg.boot.mode [
      "apple-refind"
      "apple-efi"
    ];
  directApple = apple && cfg.boot.mode == "apple-efi";
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
            message = "Intel Apple profiles require an Apple EFI boot strategy.";
          }
          {
            assertion =
              !directApple
              || (
                builtins.elem cfg.platform [
                  "macbookpro11-1"
                  "macbookpro12-1"
                ]
                && config.boot.loader.grub.efiInstallAsRemovable
                && !config.boot.loader.efi.canTouchEfiVariables
              );
            message = "Direct Apple EFI requires a supported Intel Mac and the fallback loader without EFI variable writes.";
          }
        ];
        boot.loader.timeout = 8;
        boot.loader.efi.efiSysMountPoint = "/boot/efi";
        boot.loader.efi.canTouchEfiVariables = !apple && !bios;
        # An external x86 root must remain bootable across the machine's USB
        # ports, including legacy USB 1/2 controllers and USB 3/UAS bridges.
        # Dependency modules are included by the normal NixOS initrd builder.
        boot.initrd.availableKernelModules = lib.optionals pkgs.stdenv.hostPlatform.isx86_64 [
          "uhci_hcd"
          "ohci_pci"
          "ehci_pci"
          "xhci_pci"
          "usb_storage"
          "uas"
          "sd_mod"
        ];
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
          efiInstallAsRemovable = directApple;
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
