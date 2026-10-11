# SPDX-License-Identifier: GPL-3.0-or-later
{
  pkgs,
  module,
  assbox,
  inputs,
}:
let
  case =
    mode: sectorSize:
    import ./installed-vm.nix {
      inherit
        pkgs
        module
        assbox
        inputs
        mode
        sectorSize
        ;
      scenario = "install";
    };
  cases = {
    uefi-512 = case "uefi" 512;
    uefi-4096 = case "uefi" 4096;
  }
  // pkgs.lib.optionalAttrs pkgs.stdenv.hostPlatform.isx86_64 {
    bios-gpt-512 = case "bios-gpt" 512;
    bios-mbr-512 = case "bios-mbr" 512;
    apple-refind-512 = case "apple-refind" 512;
    apple-efi-11-1-512 = import ./installed-vm.nix {
      inherit
        pkgs
        module
        assbox
        inputs
        ;
      mode = "apple-efi";
      macbookModel = "MacBookPro11,1";
      scenario = "install";
      caseScript = ../fixtures/laptop_installed_cases.py;
    };
    apple-refind-11-1-512 = import ./installed-vm.nix {
      inherit
        pkgs
        module
        assbox
        inputs
        ;
      mode = "apple-refind";
      macbookModel = "MacBookPro11,1";
      scenario = "install";
      caseScript = ../fixtures/laptop_installed_cases.py;
    };
    bios-gpt-usb-512 = import ./installed-vm.nix {
      inherit
        pkgs
        module
        assbox
        inputs
        ;
      mode = "bios-gpt";
      targetTransport = "usb";
      scenario = "install";
      caseScript = ../fixtures/laptop_installed_cases.py;
    };
  };
in
{
  inherit cases;
  matrix = pkgs.linkFarm "assbox-install-boot-matrix" (
    pkgs.lib.mapAttrsToList (name: path: { inherit name path; }) cases
  );
}
