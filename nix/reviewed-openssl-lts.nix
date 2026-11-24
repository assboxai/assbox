# SPDX-License-Identifier: GPL-3.0-or-later
{ pkgs }:
let
  base = pkgs.openssl_3_5;
  version = "3.5.9";
in
assert builtins.elem base.version [
  "3.5.8"
  version
];
base.overrideAttrs (
  old:
  {
    patches = (old.patches or [ ]) ++ [
      ./patches/openssl/CVE-2026-107493.patch
      ./patches/openssl/CVE-2026-35190.patch
      ./patches/openssl/CVE-2026-124709.patch
    ];
  }
  // pkgs.lib.optionalAttrs (base.version == "3.5.8") {
    inherit version;
    # OpenSSL bootstraps ordinary fetchurl, which uses curl.
    src = pkgs.stdenv.fetchurlBoot {
      url = "https://github.com/openssl/openssl/releases/download/openssl-${version}/openssl-${version}.tar.gz";
      hash = "sha256-YD9WAuLu8A13+9Qp003NWCK7MBdXobyc2yTGcPHrhZo=";
    };
    meta = old.meta // {
      changelog = "https://github.com/openssl/openssl/blob/openssl-${version}/CHANGES.md";
    };
  }
)
