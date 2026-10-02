# SPDX-License-Identifier: GPL-3.0-or-later
{
  config,
  lib,
  pkgs,
  ...
}:
let
  cfg = config.assbox.computerUse;
  active = config.assbox.enable && cfg.mode != "none";
  desktop = cfg.mode == "virtual-desktop";
  runtime = pkgs.writeShellScriptBin "assbox-computer-use-runtime" ''
    exec ${pkgs.python3}/bin/python3 ${../scripts/computer-use/desktop.py} "$@"
  '';
  # Interactive invocations need the same bounds as supervised providers. Keep
  # the internal entry point in the provider unit's existing control group.
  launcher = pkgs.writeShellScriptBin "assbox-computer-use" ''
    exec ${pkgs.systemd}/bin/systemd-run --user --scope --quiet --collect \
      --property=MemoryMax=${toString cfg.memoryMaxMiB}M \
      --property=CPUWeight=${toString config.assbox.resources.agentCPUWeight} \
      --property=CPUAccounting=yes --property=MemoryAccounting=yes \
      ${runtime}/bin/assbox-computer-use-runtime "$@"
  '';
  browser = pkgs.writeShellScriptBin "assbox-browser" ''
    exec ${launcher}/bin/assbox-computer-use chromium -- "$@"
  '';
in
{
  options.assbox.computerUse = {
    mode = lib.mkOption {
      type = lib.types.enum [
        "none"
        "browser"
        "virtual-desktop"
      ];
      default = "none";
      description = "Optional execution-side resources; physical presentation is independent.";
    };
    runtime = lib.mkOption {
      type = lib.types.package;
      readOnly = true;
      internal = true;
    };
    memoryMaxMiB = lib.mkOption {
      type = lib.types.ints.between 512 16384;
      default = 4096;
    };
    providerRuntime = lib.mkOption {
      type = lib.types.nullOr lib.types.package;
      default = null;
      description = "Optional independently pinned CUA helper required by the selected provider; no lazy package-manager installation.";
    };
  };
  config = lib.mkIf config.assbox.enable {
    assbox.computerUse.runtime = runtime;
    assertions = [
      {
        assertion = !active || !config.assbox.controller.active;
        message = "Autonomous computer-use resources belong on standalone execution or in the managed guest, never on the sensitive controller.";
      }
    ];
    environment.systemPackages =
      lib.optionals active (
        [
          launcher
          browser
          pkgs.chromium
        ]
        ++ lib.optional (cfg.providerRuntime != null) cfg.providerRuntime
      )
      ++ lib.optionals desktop [
        pkgs.xorg.xorgserver
        pkgs.xorg.xauth
        pkgs.tigervnc
        pkgs.xfce.xfce4-session
        pkgs.xfce.xfwm4
        pkgs.xfce.xfce4-panel
        pkgs.xfce.xfdesktop
        pkgs.dbus
        pkgs.xdotool
        pkgs.ffmpeg
        pkgs.openbox
      ];
    # References in /etc also enter the system closure. CLI-only and browser
    # instances must not acquire a desktop stack through this manifest.
    environment.etc."assbox/computer-use-tools.json" = lib.mkIf active {
      text = builtins.toJSON (
        {
          modes = [
            "browser"
            "chromium"
          ]
          ++ lib.optionals desktop [
            "provider"
            "display"
          ];
          browser = "${pkgs.chromium}/bin/chromium";
        }
        // lib.optionalAttrs desktop {
          xvfb = "${pkgs.xorg.xorgserver}/bin/Xvfb";
          xauth = "${pkgs.xorg.xauth}/bin/xauth";
          dbus = "${pkgs.dbus}/bin/dbus-daemon";
          wm = "${pkgs.openbox}/bin/openbox";
        }
      );
    };
    environment.variables = lib.optionalAttrs active { HERMES_DISABLE_LAZY_INSTALLS = "1"; };
  };
}
