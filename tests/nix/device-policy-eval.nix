# SPDX-License-Identifier: GPL-3.0-or-later
# Evaluate the real device policy without constructing a NixOS system or packages.
{
  libPath,
  wifi,
  bluetooth ? false,
  audio ? false,
  camera ? false,
}:
let
  lib = import libPath;
  result = lib.evalModules {
    specialArgs.pkgs = {
      # devices.nix deliberately resolves its default kernel from a clean
      # Nixpkgs import. Model the standard package-set identity while keeping
      # every userspace package used by this fixture inert.
      path = libPath + "/..";
      config = { };
      stdenv.hostPlatform.system = builtins.currentSystem;
      util-linux = "/inert/util-linux";
      networkmanager = "/inert/networkmanager";
      systemd = "/inert/systemd";
      gnugrep = "/inert/gnugrep";
      gnused = "/inert/gnused";
      writeTextDir = path: text: { inherit path text; };
      writeShellScript = _name: text: text;
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
          devices = {
            wifi.enable = wifi;
            bluetooth.enable = bluetooth;
            audio.enable = audio;
            camera.enable = camera;
          };
        };
        config.systemd.package = "/inert/systemd";
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
  radioHotplug = result.config.systemd.services."assbox-radio-hotplug" or null;
  devicePolicyCheck = result.config.systemd.services."assbox-device-policy-check" or null;
  radioInput = kernelConfig.config.settings.RFKILL_INPUT;
  unmanaged = result.config.networking.networkmanager.unmanaged;
  bluetoothEnabled = result.config.hardware.bluetooth.enable;
  pipewireEnabled = result.config.services.pipewire.enable;
  blacklistedKernelModules = result.config.boot.blacklistedKernelModules;
  kernelParams = result.config.boot.kernelParams;
}
