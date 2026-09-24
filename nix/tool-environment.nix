# SPDX-License-Identifier: GPL-3.0-or-later
{ pkgs }:
let
  packages = with pkgs; [
    (callPackage ./anonymous-gh.nix { })
    curl
    cacert
    nix
    nixos-install-tools
    nixos-rebuild
    nixfmt
    git
    jq
    systemd
    util-linux
    coreutils
    findutils
    gnugrep
    gnused
    gnutar
    e2fsprogs
    dosfstools
    exfatprogs
    efibootmgr
    mkpasswd
    iproute2
    python3
    gptfdisk
    openssh
    nano
  ];
in
{
  inherit packages;
  path = pkgs.lib.makeBinPath packages;
}
