# SPDX-License-Identifier: GPL-3.0-or-later
{
  config,
  lib,
  pkgs,
  ...
}:
let
  cfg = config.assbox;
  loader = config.boot.loader;
  root = config.fileSystems."/" or { };
  esp = config.fileSystems."/boot/efi" or { };
  receipt = pkgs.writeText "assbox-boot-policy.json" (
    builtins.toJSON {
      schema = 2;
      binding = {
        architecture = if pkgs.stdenv.hostPlatform.system == "x86_64-linux" then "x86_64" else "aarch64";
        mode = cfg.boot.mode;
        inherit (cfg) platform;
        disk = cfg.boot.disk;
        rootDevice = root.device or "";
        espDevice = esp.device or "";
        loader = {
          rootFsType = root.fsType or "";
          espFsType = esp.fsType or "";
          systemdBoot = loader.systemd-boot.enable;
          grub = loader.grub.enable;
          grubEfi = loader.grub.efiSupport;
          grubDevice = loader.grub.device;
          grubDevices = loader.grub.devices;
          mirroredBoots = map (entry: {
            inherit (entry)
              path
              devices
              efiSysMountPoint
              efiBootloaderId
              ;
          }) loader.grub.mirroredBoots;
          efiCanTouch = loader.efi.canTouchEfiVariables;
          efiMount = loader.efi.efiSysMountPoint;
        };
      };
      policy.generations =
        if cfg.boot.mode == "uefi" then
          loader.systemd-boot.configurationLimit
        else
          loader.grub.configurationLimit;
    }
  );
in
{
  config = lib.mkIf cfg.enable {
    # The receipt travels with this generation, even after local source changes.
    system.systemBuilderCommands = ''
      ln -s ${receipt} "$out/assbox-boot-policy.json"
    '';
  };
}
