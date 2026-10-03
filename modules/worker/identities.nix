# SPDX-License-Identifier: GPL-3.0-or-later
# Persistent ownership identities, not worker enablement or login accounts.
{
  config,
  lib,
  pkgs,
  ...
}:
{
  # Admission happens BEFORE candidate activation. Keep these names/UIDs/GIDs
  # resolvable while a worker is disabled so retained disks and keys can be
  # checked without guessing an owner or rewriting existing ownership.
  config = lib.mkIf config.assbox.enable {
    users.groups.assbox-vmm = { };
    users.users.assbox-vmm = {
      isSystemUser = true;
      group = "assbox-vmm";
      extraGroups = lib.optional config.assbox.worker.enable "kvm";
      home = "/var/empty";
      createHome = false;
      hashedPassword = "!";
      shell = "${pkgs.shadow}/bin/nologin";
    };
    users.groups.assbox-health-probe = { };
    users.users.assbox-health-probe = {
      isSystemUser = true;
      group = "assbox-health-probe";
      home = "/var/empty";
      createHome = false;
      hashedPassword = "!";
      shell = "${pkgs.shadow}/bin/nologin";
    };
  };
}
