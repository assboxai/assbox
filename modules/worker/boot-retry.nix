# SPDX-License-Identifier: GPL-3.0-or-later
{
  config,
  lib,
  assboxPackage,
  ...
}:
{
  # Keep the ordinary boot timer one-shot. A separate retry re-enters the
  # authoritative engine without depending on mutable guest shell state.
  config = lib.mkIf (config.assbox.enable && config.assbox.workerBootPolicy.enabled) {
    systemd.services.assbox-worker-boot-retry = {
      enable = config.systemd.services.assbox-boot-check.enable;
      description = "Retry unaccepted Assbox worker boots";
      after = [ "network.target" ];
      unitConfig.ConditionPathExists = "/etc/nixos/flake.lock";
      serviceConfig = {
        Type = "oneshot";
        ExecStart = "${assboxPackage}/bin/assbox internal boot-check --retry";
        TimeoutStartSec = "4h";
        UMask = "0077";
        Slice = "assbox.slice";
        CPUAccounting = true;
        IOAccounting = true;
        MemoryAccounting = true;
      };
    };
    systemd.timers.assbox-worker-boot-retry = {
      enable = config.systemd.services.assbox-worker-boot-retry.enable;
      wantedBy = [ "timers.target" ];
      timerConfig = {
        OnBootSec = "3min";
        OnUnitInactiveSec = "5min";
        AccuracySec = "15s";
      };
    };
  };
}
