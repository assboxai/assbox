# SPDX-License-Identifier: GPL-3.0-or-later
# Sign the real, locally built harness closure inside a disposable VM database.
{ pkgs, roots }:
{ lib, ... }:
{
  nix.settings.trusted-public-keys = lib.mkAfter [ (import ./fixture-cache-public-key.nix) ];
  systemd.services.assbox-disposable-fixture-signing = {
    requiredBy = [ "multi-user.target" ];
    before = [ "multi-user.target" ];
    requires = [ "nix-daemon.service" ];
    after = [ "nix-daemon.service" ];
    serviceConfig = {
      Type = "oneshot";
      RemainAfterExit = true;
      ExecStart = pkgs.writeShellScript "assbox-disposable-fixture-signing" ''
        set -eu
        ${pkgs.nix}/bin/nix store sign --recursive \
          --key-file ${../fixtures/nix-cache-test.key} \
          ${lib.escapeShellArgs (map toString roots)}
      '';
    };
  };
}
