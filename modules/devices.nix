# SPDX-License-Identifier: GPL-3.0-or-later
{
  config,
  lib,
  pkgs,
  ...
}:
let
  cfg = config.assbox;
in
{
  config = lib.mkIf cfg.enable {
    # A seat controller can receive writable input descriptors from logind.
    # Legacy in-kernel radio hotkeys would bypass the rfkill device permissions.
    boot.kernelPatches = [
      {
        name = "assbox-administrative-radio-control";
        patch = null;
        structuredExtraConfig.RFKILL_INPUT = lib.mkForce lib.kernel.no;
      }
    ];
    hardware.bluetooth.enable = cfg.devices.bluetooth.enable;
    services.pipewire = {
      enable = cfg.devices.audio.enable;
      alsa.enable = cfg.devices.audio.enable;
      pulse.enable = cfg.devices.audio.enable;
    };
    # Leave USB input, networking and admin-controlled storage available. Do not
    # grant the workload raw block devices, serial adapters, cameras or sound by
    # accident through an active-seat ACL.
    services.udev.packages = [
      (pkgs.writeTextDir "lib/udev/rules.d/72-assbox-policy.rules" (
        ''
          # Radio switches are administrative even for the active desktop user.
          SUBSYSTEM=="misc", KERNEL=="rfkill", TAG-="uaccess", OWNER="root", GROUP="root", MODE="0600"
          SUBSYSTEM=="block", TAG-="uaccess", OWNER="root", GROUP="disk", MODE="0660"
          SUBSYSTEM=="tty", KERNEL=="ttyUSB*", TAG-="uaccess", OWNER="root", GROUP="dialout", MODE="0660"
          SUBSYSTEM=="tty", KERNEL=="ttyACM*", TAG-="uaccess", OWNER="root", GROUP="dialout", MODE="0660"
        ''
        + lib.optionalString (!cfg.devices.camera.enable) ''
          SUBSYSTEM=="video4linux", TAG-="uaccess", OWNER="root", GROUP="root", MODE="0600"
        ''
        + lib.optionalString (!cfg.devices.audio.enable) ''
          SUBSYSTEM=="sound", TAG-="uaccess", OWNER="root", GROUP="root", MODE="0600"
        ''
        + lib.optionalString (!cfg.devices.wifi.enable) ''
          ACTION=="add", SUBSYSTEM=="rfkill", ATTR{type}=="wlan", RUN+="${pkgs.util-linux}/bin/rfkill block wlan", TAG+="systemd", ENV{SYSTEMD_WANTS}+="assbox-radio-hotplug.service"
        ''
      ))
    ];
    networking.networkmanager.unmanaged = lib.optional (!cfg.devices.wifi.enable) "type:wifi";
    # NetworkManager restores its own saved radio preference at startup, even
    # for unmanaged interfaces. Apply the configured selection after that restore
    # on every daemon start, including transitions back from disabled to enabled.
    systemd.services.NetworkManager.postStart = ''
      ${pkgs.networkmanager}/bin/nmcli radio wifi ${if cfg.devices.wifi.enable then "on" else "off"}
    ''
    + lib.optionalString (!cfg.devices.wifi.enable) ''
      # Machines without radios may not have loaded rfkill at all. Hotplug is
      # covered by the add rule; absence must not break Ethernet startup.
      if test -c /dev/rfkill; then
        ${pkgs.util-linux}/bin/rfkill block wlan
      fi
    '';
    # The immediate udev action closes the hotplug window. Reassert the policy
    # after NetworkManager as well, because its device discovery can restore a
    # saved enabled preference after the udev RUN command has completed.
    systemd.services.assbox-radio-hotplug = lib.mkIf (!cfg.devices.wifi.enable) {
      description = "Reapply the Assbox disabled Wi-Fi policy after radio hotplug";
      requires = [ "NetworkManager.service" ];
      after = [ "NetworkManager.service" ];
      serviceConfig.Type = "oneshot";
      script = ''
        ${pkgs.networkmanager}/bin/nmcli radio wifi off
        ${pkgs.util-linux}/bin/rfkill block wlan
      '';
    };
    # New Wi-Fi radios remain blocked; drivers stay available.
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
