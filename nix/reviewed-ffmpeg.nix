# SPDX-License-Identifier: GPL-3.0-or-later
{ pkgs, ffmpeg }:
let
  version = "9.1";
  gnutls = import ./reviewed-gnutls.nix { inherit pkgs; };
in
if pkgs.stdenv.hostPlatform.isLinux && ffmpeg.version == "9.0.1" then
  (ffmpeg.override { inherit gnutls; }).overrideAttrs (old: {
    inherit version;
    src = pkgs.fetchurl {
      url = "https://ffmpeg.org/releases/ffmpeg-${version}.tar.xz";
      hash = "sha256-Gk05SuY9GQpSbNBS60QVwVa1xeLfN++rQafeC4/eJDM=";
    };
    # The OpenGL output device and its configure flag were removed in 9.1.
    configureFlags = builtins.filter (flag: flag != "--disable-opengl") old.configureFlags;
    # FFmpeg 9.1 includes this backport.
    patches = builtins.filter (
      patch:
      !pkgs.lib.hasSuffix "0001-swscale-loongarch-fix-buffer-underflow-in-yuv2plane1.patch" (
        toString patch
      )
    ) (old.patches or [ ]);
  })
else
  ffmpeg
