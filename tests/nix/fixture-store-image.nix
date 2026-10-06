# SPDX-License-Identifier: GPL-3.0-or-later
# Stream the complete offline closure directly into its EROFS image. The pinned
# tool needs a widened signed metadata offset once file data exceeds 2 GiB.
{ lib, pkgs, ... }:
let
  erofs = pkgs.erofs-utils.overrideAttrs (old: {
    patches = (old.patches or [ ]) ++ [ ../../nix/patches/erofs-large-streaming-offset.patch ];
  });
in
{
  virtualisation.host.pkgs = lib.mkForce (
    pkgs
    // {
      erofs-utils = pkgs.symlinkJoin {
        name = "assbox-fixture-streaming-erofs-utils";
        paths = [ erofs ];
        nativeBuildInputs = [ pkgs.makeWrapper ];
        postBuild = ''
          wrapProgram "$out/bin/mkfs.erofs" --add-flags "--sort=none -E^inline_data"
        '';
      };
    }
  );
}
