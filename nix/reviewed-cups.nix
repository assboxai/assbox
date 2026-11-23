# SPDX-License-Identifier: GPL-3.0-or-later
{ pkgs }:
let
  cupsVersion = "2.4.20";
  gnutls = import ./reviewed-gnutls.nix { inherit pkgs; };
in
if pkgs.stdenv.hostPlatform.isLinux && pkgs.cups.version == "2.4.19" then
  (pkgs.cups.override { inherit gnutls; }).overrideAttrs (old: {
    version = cupsVersion;
    src = pkgs.fetchurl {
      url = "https://github.com/OpenPrinting/cups/releases/download/v${cupsVersion}/cups-${cupsVersion}-source.tar.gz";
      hash = "sha256-q02c1/PlgGAJHSsklyIj1kAWdfEcSbZav09u8x3qIv8=";
    };
    patches = (old.patches or [ ]) ++ [
      ./patches/cups-cve-2026-107885.patch
      ./patches/cups-cve-2026-107655.patch
    ];
  })
else
  pkgs.cups
