# SPDX-License-Identifier: GPL-3.0-or-later
{
  pkgs,
  module,
  assbox,
  inputs,
}:
import ./installed-vm.nix {
  inherit
    pkgs
    module
    assbox
    inputs
    ;
  mode = "uefi";
  scenario = "activation";
}
