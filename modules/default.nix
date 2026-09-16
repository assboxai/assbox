# SPDX-License-Identifier: GPL-3.0-or-later
{ ... }:
{
  imports = [
    ./options.nix
    ./base.nix
    ./devices.nix
    ./boot.nix
    ./platform.nix
    ./presentation.nix
    ./applications.nix
    ./maintenance.nix
    ./resources.nix
    ./audit.nix
    ./generation.nix
  ];
}
