# SPDX-License-Identifier: GPL-3.0-or-later
# Evaluate the real device policy without constructing a NixOS system or packages.
{ libPath, wifi }:
let
  lib = import libPath;
  result = lib.evalModules {
    specialArgs.pkgs = {
      util-linux = "/inert/util-linux";
      networkmanager = "/inert/networkmanager";
      writeTextDir = path: text: { inherit path text; };
    };
    modules = [
      ../../modules/options.nix
      ../../modules/devices.nix
      {
        options = lib.genAttrs [ "services" "systemd" "hardware" "networking" "boot" ] (
          _:
          lib.mkOption {
            type = lib.types.attrsOf lib.types.anything;
            default = { };
          }
        );
        config.assbox = {
          enable = true;
          devices.wifi.enable = wifi;
        };
      }
    ];
  };
  kernelConfig = lib.evalModules {
    modules = [
      (libPath + "/../nixos/modules/system/boot/kernel_config.nix")
      { settings.RFKILL_INPUT = lib.kernel.yes; }
    ]
    ++ map (patch: { settings = patch.structuredExtraConfig; }) result.config.boot.kernelPatches;
  };
in
{
  rules = result.config.services.udev.packages;
  radioStartup = result.config.systemd.services.NetworkManager.postStart;
  radioInput = kernelConfig.config.settings.RFKILL_INPUT;
  unmanaged = result.config.networking.networkmanager.unmanaged;
}
