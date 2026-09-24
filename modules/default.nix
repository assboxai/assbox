# SPDX-License-Identifier: GPL-3.0-or-later
{ ... }:
{
  imports = [
    ./options.nix
    ./base.nix
    ./access.nix
    ./devices.nix
    ./boot.nix
    ./platform.nix
    ./presentation.nix
    ./components.nix
    ./controller.nix
    ./applications.nix
    ./remotes.nix
    ./editors.nix
    ./maintenance.nix
    ./resources.nix
    ./audit.nix
    ./generation.nix
    ./worker
  ];
}
