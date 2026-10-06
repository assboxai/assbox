# SPDX-License-Identifier: GPL-3.0-or-later
{ lib, pkgs }:
lib.getBin (
  pkgs.ffmpeg.override {
    withXcb = true;
    withXcbShm = true;
    withXcbxfixes = true;
    withXcbShape = true;
  }
)
