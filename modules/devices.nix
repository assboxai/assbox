# SPDX-License-Identifier: GPL-3.0-or-later
{ config, lib, pkgs, ... }:
let cfg = config.assbox;
in
{
  config = lib.mkIf cfg.enable {
    hardware.bluetooth.enable = cfg.devices.bluetooth.enable;
    services.pipewire = {
      enable = cfg.devices.audio.enable;
      alsa.enable = cfg.devices.audio.enable;
      pulse.enable = cfg.devices.audio.enable;
    };
    # Leave USB input, networking and admin-controlled storage available. Do not
    # grant the workload raw block devices, serial adapters, cameras or sound by
    # accident through an active-seat ACL.
    services.udev.packages = [ (pkgs.writeTextDir "lib/udev/rules.d/72-assbox-policy.rules" (''
      SUBSYSTEM=="block", TAG-="uaccess", OWNER="root", GROUP="disk", MODE="0660"
      SUBSYSTEM=="tty", KERNEL=="ttyUSB*", TAG-="uaccess", OWNER="root", GROUP="dialout", MODE="0660"
      SUBSYSTEM=="tty", KERNEL=="ttyACM*", TAG-="uaccess", OWNER="root", GROUP="dialout", MODE="0660"
    '' + lib.optionalString (!cfg.devices.camera.enable) ''
      SUBSYSTEM=="video4linux", TAG-="uaccess", OWNER="root", GROUP="root", MODE="0600"
    '' + lib.optionalString (!cfg.devices.audio.enable) ''
      SUBSYSTEM=="sound", TAG-="uaccess", OWNER="root", GROUP="root", MODE="0600"
    '' + lib.optionalString (!cfg.devices.wifi.enable) ''
      ACTION=="add", SUBSYSTEM=="rfkill", ATTR{type}=="wlan", RUN+="${pkgs.util-linux}/bin/rfkill block wlan"
    '')) ];
    networking.networkmanager.unmanaged = lib.optional (!cfg.devices.wifi.enable) "type:wifi";
    systemd.services.assbox-radio-policy = lib.mkIf (!cfg.devices.wifi.enable) {
      description = "Apply the selected disabled Wi-Fi policy";
      wantedBy = [ "multi-user.target" ];
      after = [ "systemd-udev-trigger.service" ];
      serviceConfig = { Type = "oneshot"; RemainAfterExit = true; ExecStart = "${pkgs.util-linux}/bin/rfkill block wlan"; };
    };
    # New Wi-Fi radios are blocked by the udev rule; drivers remain available.
    systemd.targets.sleep.enable = cfg.power.suspend.enable;
    systemd.targets.suspend.enable = cfg.power.suspend.enable;
    systemd.targets.hibernate.enable = cfg.power.suspend.enable;
    systemd.targets.hybrid-sleep.enable = cfg.power.suspend.enable;
    systemd.targets.suspend-then-hibernate.enable = cfg.power.suspend.enable;
    services.logind.settings.Login = lib.mkIf (!cfg.power.suspend.enable) {
      HandleLidSwitch = "ignore";
      HandleLidSwitchExternalPower = "ignore";
      HandleLidSwitchDocked = "ignore";
      HandleSuspendKey = "ignore";
      HandleHibernateKey = "ignore";
      IdleAction = "ignore";
    };
  };
}
