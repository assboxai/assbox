# SPDX-License-Identifier: GPL-3.0-or-later
# The offline installer closure remains complete; compress its block image to
# avoid keeping a second uncompressed copy on the disposable runner.
{ lib, pkgs, ... }:
{
  virtualisation.host.pkgs = lib.mkForce (
    pkgs
    // {
      erofs-utils = pkgs.symlinkJoin {
        name = "assbox-fixture-erofs-utils";
        paths = [ pkgs.erofs-utils ];
        nativeBuildInputs = [ pkgs.makeWrapper ];
        postBuild = ''
          wrapProgram "$out/bin/mkfs.erofs" --add-flags -zlz4
        '';
      };
    }
  );
}
