# SPDX-License-Identifier: GPL-3.0-or-later
{ pkgs }:
let
  unboundVersion = "1.26.2";
  unbound = pkgs.unbound.overrideAttrs {
    version = unboundVersion;
    src = pkgs.fetchurl {
      url = "https://nlnetlabs.nl/downloads/unbound/unbound-${unboundVersion}.tar.gz";
      hash = "sha256-2O56pruz/xvn2eV2N9DQ7C8YJzqO//Ggr+LGZYWLlvc=";
    };
  };
in
if pkgs.stdenv.hostPlatform.isLinux && pkgs.unbound.version == "1.26.0" then
  pkgs.gnutls.override { inherit unbound; }
else
  pkgs.gnutls
