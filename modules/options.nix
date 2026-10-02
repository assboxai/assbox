# SPDX-License-Identifier: GPL-3.0-or-later
{ lib, ... }:
let
  inherit (lib) mkOption mkEnableOption types;
  flag =
    description:
    mkOption {
      type = types.bool;
      default = false;
      inherit description;
    };
in
{
  options.assbox = {
    enable = mkEnableOption "the Assbox appliance substrate";
    controller = {
      active = mkOption {
        type = types.bool;
        readOnly = true;
        internal = true;
        description = "Evaluated thin-controller policy; not an administrator bypass toggle.";
      };
      profile = mkOption {
        type = types.enum [
          "none"
          "generic"
          "chatgpt-desktop"
          "native-kiosk"
          "web-kiosk"
          "unqualified"
        ];
        readOnly = true;
        description = "Controller adapter selected from component capabilities.";
      };
    };
    selectedComponents = mkOption {
      type = types.listOf types.str;
      readOnly = true;
      internal = true;
      description = "Evaluated enabled component IDs.";
    };
    session.autostart = mkOption {
      type = types.listOf (
        types.enum [
          "chatgpt-desktop"
          "claude-desktop"
          "vscode"
          "zed"
          "chromium"
          "emacs"
          "opencode-attach"
          "openclaw-dashboard"
        ]
      );
      default = [ ];
      description = "Explicit launchers for the owned graphical session.";
    };
    editor.default = mkOption {
      type = types.enum [
        "nano"
        "vim"
        "emacs"
      ];
      default = "nano";
      description = "Console editor; the selected optional editor must be installed.";
    };
    presentation = mkOption {
      type = types.enum [
        "headless"
        "x11"
        "wayland"
      ];
      default = "headless";
      description = "Presentation is independent of application; ChatGPT requires X11.";
    };
    platform = mkOption {
      type = types.enum [
        "generic"
        "apple-intel"
        "macbookpro11-1"
        "macbookpro12-1"
      ];
      default = "generic";
      description = "An optional compatibility profile, not a host identity.";
    };
    acceptUnfree = flag "Machine-wide permission for unfree nixpkgs packages, including selected proprietary applications; retained when switching applications.";
    network = {
      discoverable = flag "Advertise the hostname using multicast DNS (Avahi) on the local network.";
    };
    display.scale = mkOption {
      type = types.ints.between 1 3;
      default = 1;
      description = "Integer display scale selected at installation; override after changing monitors.";
    };
    boot = {
      mode = mkOption {
        type = types.enum [
          "uefi"
          "bios-gpt"
          "bios-mbr"
          "apple-refind"
        ];
        default = "uefi";
        description = "Validated installation boot strategy.";
      };
      disk = mkOption {
        type = types.str;
        default = "";
        description = "Stable whole-disk by-id path for BIOS and Apple preservation checks.";
      };
      generations = mkOption {
        type = types.ints.between 2 32;
        default = 8;
        description = "Boot menu generation limit, changeable through an ordinary Assbox rebuild; this does not garbage-collect the store.";
      };
    };
    devices = {
      wifi.enable = flag "Enable Wi-Fi; installer recommends from the active network route.";
      audio.enable = flag "Enable audio output and microphone capture.";
      camera.enable = flag "Permit camera device access.";
      bluetooth.enable = flag "Enable Bluetooth.";
    };
    power.suspend.enable = flag "Allow suspend and hibernation; requires additional swap setup for hibernation.";
    updates = {
      enable = mkOption {
        type = types.bool;
        default = true;
        description = "Automatically stage and reboot into updated Assbox generations.";
      };
      calendar = mkOption {
        type = types.str;
        default = "*-*-* 18:00:00";
        description = "Systemd calendar in the configured local timezone.";
      };
      jitter = mkOption {
        type = types.str;
        default = "15m";
        description = "Maximum randomized scheduling delay.";
      };
      persistent = mkOption {
        type = types.bool;
        default = true;
        description = "Catch up missed maintenance windows after startup.";
      };
      rebootGraceSeconds = mkOption {
        type = types.ints.between 0 3600;
        default = 600;
        description = "Notification grace before maintenance reboot; activity cannot veto it.";
      };
      minimumBatteryPercent = mkOption {
        type = types.ints.between 0 100;
        default = 20;
        description = "Below this charge, or with uncertain battery power, reboot is retried. Positively confirmed AC permits reboot.";
      };
      maximumStageRetries = mkOption {
        type = types.ints.between 0 24;
        default = 3;
        description = "Hourly retries after a failed scheduled stage; the next daily window resets the budget.";
      };
      keepGenerations = mkOption {
        type = types.ints.between 2 64;
        default = 8;
        description = "Keep the newest system generations plus the running and selected generations; prune only when no reboot or recovery is pending.";
      };
      retryCalendar = mkOption {
        type = types.str;
        default = "hourly";
        description = "Retry power-deferred reboots and bounded failed staging attempts.";
      };
    };
    audit = mkOption {
      type = types.attrs;
      readOnly = true;
      internal = true;
      description = "Evaluation-derived security facts consumed by the CLI and CI.";
    };
  };
}
