# SPDX-License-Identifier: GPL-3.0-or-later
{
  pkgs,
  module,
  assbox,
  inputs,
}:
let
  modes = [
    "uefi"
  ]
  ++ pkgs.lib.optionals pkgs.stdenv.hostPlatform.isx86_64 [
    "bios-gpt"
    "bios-mbr"
    "apple-refind"
  ];
in
pkgs.linkFarm "assbox-install-boot-matrix" (
  map (mode: {
    name = mode;
    path = import ./installed-vm.nix {
      inherit
        pkgs
        module
        assbox
        inputs
        mode
        ;
      scenario = "install";
    };
  }) modes
  ++ [
    {
      name = "uefi-4kn";
      path = import ./installed-vm.nix {
        inherit
          pkgs
          module
          assbox
          inputs
          ;
        mode = "uefi";
        scenario = "install";
        sectorSize = 4096;
      };
    }
  ]
)
