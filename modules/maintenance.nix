# SPDX-License-Identifier: GPL-3.0-or-later
{
  config,
  lib,
  assboxPackage,
  ...
}:
let
  cfg = config.assbox;
  binary = "${assboxPackage}/bin/assbox";
  job = description: command: {
    inherit description;
    after = [ "network-online.target" ];
    wants = [ "network-online.target" ];
    unitConfig.ConditionPathExists = "/etc/nixos/flake.lock";
    serviceConfig = {
      Type = "oneshot";
      ExecStart = "${binary} ${command}";
      TimeoutStartSec = "4h";
      UMask = "0077";
      Slice = "assbox.slice";
      CPUAccounting = true;
      IOAccounting = true;
      MemoryAccounting = true;
    };
  };
in
{
  config = lib.mkIf cfg.enable {
    systemd.services.assbox-maintenance = lib.mkIf cfg.updates.enable (
      job "Build, stage and reboot into an updated Assbox" "internal maintenance"
    );
    systemd.services.assbox-reboot-retry = lib.mkIf cfg.updates.enable (
      job "Retry failed staging or a power-deferred Assbox reboot" "internal maintenance --retry"
    );
    systemd.timers.assbox-maintenance = lib.mkIf cfg.updates.enable {
      wantedBy = [ "timers.target" ];
      timerConfig = {
        OnCalendar = cfg.updates.calendar;
        RandomizedDelaySec = cfg.updates.jitter;
        Persistent = cfg.updates.persistent;
      };
    };
    systemd.timers.assbox-reboot-retry = lib.mkIf cfg.updates.enable {
      wantedBy = [ "timers.target" ];
      timerConfig = {
        OnCalendar = cfg.updates.retryCalendar;
        Persistent = true;
        RandomizedDelaySec = "5m";
      };
    };
    systemd.services.assbox-boot-check = {
      description = "Check the running Assbox generation after boot";
      after = [ "network.target" ];
      serviceConfig = {
        Type = "oneshot";
        ExecStart = "${binary} internal boot-check";
      };
    };
    # Live activation starts active targets and their inactive dependencies again.
    # A boot timer stays elapsed, even if the check failed, so a switch cannot
    # rerun the check while the parent Assbox operation holds its lock.
    systemd.timers.assbox-boot-check = {
      enable = config.systemd.services.assbox-boot-check.enable;
      wantedBy = [ "timers.target" ];
      timerConfig = {
        OnBootSec = "1s";
        RemainAfterElapse = true;
      };
    };
  };
}
