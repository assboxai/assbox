# SPDX-License-Identifier: GPL-3.0-or-later
{
  config,
  lib,
  pkgs,
  ...
}:
let
  cfg = config.assbox;
  # The authenticated default kernel is its own release artifact. Keep its
  # derivation independent from application/library overlays so an unrelated
  # security point release does not force every appliance to acquire a new
  # kernel. A normal-priority administrator selection still overrides this.
  basePkgs = import pkgs.path {
    system = pkgs.stdenv.hostPlatform.system;
    config = pkgs.config;
    overlays = [ ];
  };
  assboxDeviceModuleDeny = config._module.args.assboxDeviceModuleDeny or true;
  devicePolicyNetworkUnit =
    config._module.args.assboxDevicePolicyNetworkUnit or "NetworkManager.service";
  useNetworkManagerPolicy = devicePolicyNetworkUnit == "NetworkManager.service";
  allRadiosDisabled = !cfg.devices.wifi.enable && !cfg.devices.bluetooth.enable;
  anyRadioDisabled = !cfg.devices.wifi.enable || !cfg.devices.bluetooth.enable;
  disabledModules = import ../nix/device-denylist.nix {
    inherit lib;
    wifi = cfg.devices.wifi.enable;
    bluetooth = cfg.devices.bluetooth.enable;
    audio = cfg.devices.audio.enable;
    camera = cfg.devices.camera.enable;
  };
  deniedModules = if assboxDeviceModuleDeny then disabledModules else [ ];
  blockDisabledRadios =
    if allRadiosDisabled then
      "${pkgs.util-linux}/bin/rfkill block all"
    else
      lib.concatStringsSep "\n" (
        lib.optional (!cfg.devices.wifi.enable) "${pkgs.util-linux}/bin/rfkill block wlan"
        ++ lib.optional (!cfg.devices.bluetooth.enable) "${pkgs.util-linux}/bin/rfkill block bluetooth"
      );
  devicePolicyCheck = pkgs.writeShellScript "assbox-device-policy-check" ''
    set -eu
    fail() {
      echo "Assbox disabled-device policy failed: $*" >&2
      exit 1
    }

    ${config.systemd.package}/bin/udevadm settle --timeout=30 \
      || fail "udev did not settle"
    ${lib.optionalString anyRadioDisabled ''
      if test -c /dev/rfkill; then
        ${blockDisabledRadios}
      fi
    ''}

    for module in ${lib.escapeShellArgs deniedModules}; do
      normalized=$(printf '%s' "$module" | ${pkgs.gnused}/bin/sed 's/-/_/g')
      if ${pkgs.gnugrep}/bin/grep -q "^$normalized " /proc/modules; then
        fail "denied kernel module is loaded: $module"
      fi
    done

    ${lib.optionalString (!cfg.devices.wifi.enable) ''
      for interface in /sys/class/net/*; do
        test -e "$interface" || continue
        if test -d "$interface/wireless" \
          || test "$(cat "$interface/type")" = 801; then
          fail "wireless network interface initialized: $interface"
        fi
      done
    ''}
    ${lib.optionalString allRadiosDisabled ''
      for radio in /sys/class/rfkill/rfkill*; do
        test -e "$radio" || continue
        if test "$(cat "$radio/soft")" != 1 \
          && test "$(cat "$radio/hard")" != 1; then
          fail "radio is not blocked: $radio"
        fi
      done
      for device in \
        /sys/class/bluetooth/* \
        /sys/class/ieee802154/* \
        /sys/class/nfc/* \
        /sys/class/uwb/* \
        /sys/class/wwan/*; do
        test ! -e "$device" || fail "wireless device initialized: $device"
      done
    ''}
    ${lib.optionalString (!cfg.devices.bluetooth.enable && !allRadiosDisabled) ''
      for device in /sys/class/bluetooth/*; do
        test ! -e "$device" || fail "Bluetooth device initialized: $device"
      done
      for radio in /sys/class/rfkill/rfkill*; do
        test -e "$radio" || continue
        test "$(cat "$radio/type")" != bluetooth \
          || test "$(cat "$radio/soft")" = 1 \
          || test "$(cat "$radio/hard")" = 1 \
          || fail "Bluetooth radio is not blocked: $radio"
      done
    ''}
    ${lib.optionalString (!cfg.devices.audio.enable) ''
      for device in /sys/class/sound/* /dev/snd/*; do
        test ! -e "$device" || fail "sound device initialized: $device"
      done
    ''}
    ${lib.optionalString (!cfg.devices.camera.enable) ''
      for device in /sys/class/video4linux/*; do
        test ! -e "$device" || fail "camera device initialized: $device"
      done
    ''}
  '';
in
{
  config = lib.mkIf cfg.enable {
    boot.kernelPackages = lib.mkOverride 900 basePkgs.linuxPackages;
    # A seat controller can receive writable input descriptors from logind.
    # Legacy in-kernel radio hotkeys would bypass the rfkill device permissions.
    boot.kernelPatches = [
      {
        name = "assbox-administrative-radio-control";
        patch = null;
        structuredExtraConfig.RFKILL_INPUT = lib.mkForce lib.kernel.no;
      }
    ];
    # Deny disabled device classes before their drivers can initialize. The
    # kernel parameter covers early/initrd loading; modprobe policy covers the
    # installed system. rfkill and device permissions below remain a backstop
    # for built-in, unrecognized and hot-plugged hardware.
    boot.blacklistedKernelModules = deniedModules;
    boot.kernelParams =
      lib.optional (deniedModules != [ ]) "module_blacklist=${lib.concatStringsSep "," deniedModules}"
      ++ lib.optional anyRadioDisabled "rfkill.default_state=0";
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
        + lib.optionalString allRadiosDisabled ''
          ACTION=="add", SUBSYSTEM=="rfkill", RUN+="${pkgs.util-linux}/bin/rfkill block all", TAG+="systemd", ENV{SYSTEMD_WANTS}+="assbox-radio-hotplug.service"
        ''
        + lib.optionalString (!allRadiosDisabled && !cfg.devices.wifi.enable) ''
          ACTION=="add", SUBSYSTEM=="rfkill", ATTR{type}=="wlan", RUN+="${pkgs.util-linux}/bin/rfkill block wlan", TAG+="systemd", ENV{SYSTEMD_WANTS}+="assbox-radio-hotplug.service"
        ''
        + lib.optionalString (!allRadiosDisabled && !cfg.devices.bluetooth.enable) ''
          ACTION=="add", SUBSYSTEM=="rfkill", ATTR{type}=="bluetooth", RUN+="${pkgs.util-linux}/bin/rfkill block bluetooth", TAG+="systemd", ENV{SYSTEMD_WANTS}+="assbox-radio-hotplug.service"
        ''
      ))
    ];
    networking.networkmanager.unmanaged = lib.mkIf useNetworkManagerPolicy (
      lib.optional (!cfg.devices.wifi.enable) "type:wifi"
    );
    # NetworkManager restores its own saved radio preference at startup, even
    # for unmanaged interfaces. Apply the configured selection after that restore
    # on every daemon start, including transitions back from disabled to enabled.
    systemd.services.NetworkManager = lib.mkIf useNetworkManagerPolicy {
      postStart = ''
        ${pkgs.networkmanager}/bin/nmcli radio wifi ${if cfg.devices.wifi.enable then "on" else "off"}
      ''
      + lib.optionalString anyRadioDisabled ''
        # Machines without radios may not have loaded rfkill at all. Hotplug is
        # covered by the add rules; absence must not break Ethernet startup.
        if test -c /dev/rfkill; then
          ${blockDisabledRadios}
        fi
      '';
    };
    systemd.services.assbox-device-policy-check =
      lib.mkIf (assboxDeviceModuleDeny && disabledModules != [ ])
        {
          description = "Verify the Assbox disabled-device boundary before networking";
          requiredBy = [ devicePolicyNetworkUnit ];
          before = [
            devicePolicyNetworkUnit
            "network-pre.target"
          ];
          after = [ "systemd-udev-settle.service" ];
          requires = [ "systemd-udev-settle.service" ];
          serviceConfig = {
            Type = "oneshot";
            RemainAfterExit = true;
            ExecStart = devicePolicyCheck;
          };
        };
    # The immediate udev action closes the hotplug window. Reassert the policy
    # after the selected network service as well. NetworkManager can restore a
    # saved preference; networkd needs only the rfkill backstop.
    systemd.services.assbox-radio-hotplug = lib.mkIf anyRadioDisabled {
      description = "Reapply the Assbox disabled-radio policy after radio hotplug";
      requires = [ devicePolicyNetworkUnit ];
      after = [ devicePolicyNetworkUnit ];
      serviceConfig.Type = "oneshot";
      script = ''
        ${lib.optionalString useNetworkManagerPolicy "${pkgs.networkmanager}/bin/nmcli radio wifi ${
          if cfg.devices.wifi.enable then "on" else "off"
        }"}
        ${blockDisabledRadios}
      '';
    };
    # New disabled radios remain blocked if an otherwise unrecognized or built-in
    # driver registers an rfkill device despite the early module denylist.
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
