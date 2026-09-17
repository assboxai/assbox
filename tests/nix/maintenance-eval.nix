# SPDX-License-Identifier: GPL-3.0-or-later
# Evaluate the real boot-check lifecycle without a NixOS system or packages.
{
  libPath,
  bootCheckEnabled ? true,
}:
let
  lib = import libPath;
  result = lib.evalModules {
    specialArgs.assboxPackage = "/inert/assbox";
    modules = [
      ../../modules/options.nix
      ../../modules/maintenance.nix
      {
        options.systemd = lib.mkOption { type = lib.types.attrsOf lib.types.anything; };
        config = {
          assbox.enable = true;
          systemd.services.assbox-boot-check.enable = bootCheckEnabled;
        };
      }
    ];
  };
in
result.config.systemd
