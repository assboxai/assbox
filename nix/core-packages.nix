# SPDX-License-Identifier: GPL-3.0-or-later
{ lib, pkgs }:
let
  # Match the pinned NixOS core profile while selecting the reviewed GNU
  # patch derivation. Keep the stdenv's build-time tool unchanged.
  packages = with pkgs; [
    acl
    attr
    bashInteractive
    bzip2
    coreutils-full
    cpio
    curl
    diffutils
    findutils
    gawk
    getent
    getconf
    gnugrep
    assboxPatchedPatch
    gnused
    gnutar
    gzip
    xz
    less
    libcap
    ncurses
    netcat
    mkpasswd
    procps
    su
    time
    util-linux
    which
    zstd
  ];
in
map (
  package: lib.setPrio ((package.meta.priority or lib.meta.defaultPriority) + 3) package
) packages
++ [ pkgs.stdenv.cc.libc ]
