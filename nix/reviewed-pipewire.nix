# SPDX-License-Identifier: GPL-3.0-or-later
{ pkgs }:
let
  ffmpeg-headless = import ./reviewed-ffmpeg.nix {
    inherit pkgs;
    ffmpeg = pkgs.ffmpeg-headless;
  };
in
pkgs.pipewire.override { inherit ffmpeg-headless; }
