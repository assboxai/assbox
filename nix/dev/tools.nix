# SPDX-License-Identifier: GPL-3.0-or-later
{ pkgs }:
with pkgs;
[
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
]
