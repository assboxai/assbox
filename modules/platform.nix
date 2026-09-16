# SPDX-License-Identifier: GPL-3.0-or-later
{
  config,
  lib,
  pkgs,
  ...
}:
let
  cfg = config.assbox;
  apple = pkgs.stdenv.hostPlatform.system == "x86_64-linux" && cfg.platform != "generic";
  knownMacbook =
    apple
    && builtins.elem cfg.platform [
      "macbookpro11-1"
      "macbookpro12-1"
    ];
in
{
  config = lib.mkIf cfg.enable (
    lib.mkMerge [
      (lib.mkIf apple {
        boot.kernelModules = [ "applesmc" ];
        hardware.cpu.intel.updateMicrocode = lib.mkDefault true;
        services.mbpfan.enable = true;
      })
      (lib.mkIf knownMacbook {
        boot.initrd.kernelModules = [ "i915" ];
        services.libinput.enable = lib.mkIf (cfg.presentation != "headless") true;
      })
    ]
  );
}
