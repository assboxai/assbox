# SPDX-License-Identifier: GPL-3.0-or-later
{ pkgs }:
let
  brotliVersion = "1.2.1";
in
if pkgs.brotli.version == "1.2.0" then
  pkgs.brotli.overrideAttrs (_old: {
    version = brotliVersion;
    src = pkgs.fetchFromGitHub {
      owner = "google";
      repo = "brotli";
      tag = "v${brotliVersion}";
      hash = "sha256-llY72cYffDv0ugsH0p89xIPEbElV4L8u7U/Fe8hT3gI=";
    };
  })
else
  pkgs.brotli
