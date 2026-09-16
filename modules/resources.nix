# SPDX-License-Identifier: GPL-3.0-or-later
{ config, lib, ... }:
{
  config = lib.mkIf config.assbox.enable {
    # Compress cold anonymous pages in RAM. These are the standard NixOS zram
    # defaults: zstd, a logical size of 50% of RAM, allocated only as used.
    zramSwap.enable = true;

    # A root slice competes with system.slice and user.slice. Weights matter only
    # under contention; idle CPUs and available I/O remain fully usable by Nix.
    systemd.slices.assbox = {
      description = "Assbox background builds and maintenance";
      sliceConfig = {
        CPUWeight = 20;
        IOWeight = 20;
        CPUAccounting = true;
        IOAccounting = true;
        MemoryAccounting = true;
      };
    };
    # Build workers are children of the daemon, not of the client that asks Nix
    # for a build, so the daemon must share the background slice.
    systemd.services.nix-daemon.serviceConfig = {
      Slice = "assbox.slice";
      CPUAccounting = true;
      IOAccounting = true;
      MemoryAccounting = true;
    };
  };
}
