# SPDX-License-Identifier: GPL-3.0-or-later
{ ... }:
{
  imports = [
    ./instances.nix
    ./network-policy.nix
    ./options.nix
    ./base.nix
    ./access.nix
    ./serve.nix
    ./service-control.nix
    ./devices.nix
    ./boot.nix
    ./platform.nix
    ./presentation.nix
    ./components.nix
    ./computer-use.nix
    ./kiosk-web.nix
    ./controller.nix
    ./applications.nix
    ./remotes.nix
    ./editors.nix
    ./maintenance.nix
    ./resources.nix
    ./state.nix
    ./audit.nix
    ./generation.nix
    ./worker
  ];
}
