# SPDX-License-Identifier: GPL-3.0-or-later
{
  config,
  lib,
  pkgs,
  assboxApplications,
  assboxPackage,
  ...
}:
let
  cfg = config.assbox;
  apps = {
    chatgpt = assboxApplications.chatgpt.chatgpt;
    opencode = assboxApplications.opencode.opencode;
    openclaw = assboxApplications.openclaw.openclaw;
  };
  enabled = id: cfg.components.${id}.enable;
  launch = id: builtins.elem id cfg.session.autostart;
  common = {
    Restart = "on-failure";
    RestartSec = 5;
    RestartSteps = 5;
    RestartMaxDelaySec = 60;
    CPUAccounting = true;
    IOAccounting = true;
    MemoryAccounting = true;
    TimeoutStopSec = 60;
    KillMode = "control-group";
    UMask = "0077";
    StandardOutput = "null";
    StandardError = "null";
    NoNewPrivileges = true;
    Environment = "PATH=/run/current-system/sw/bin:/run/wrappers/bin";
  };
  x11Terminal = import ../nix/st.nix { inherit (pkgs) st; };
  terminal =
    if cfg.presentation == "wayland" then
      "${pkgs.foot}/bin/foot"
    else
      # xterm exits successfully even when its child crashes. st reports child
      # failure, while an ordinary window-manager close still exits successfully.
      "${x11Terminal}/bin/st -c AssboxOpenCode -f monospace:pixelsize=${
        toString (12 * cfg.display.scale)
      } -e";

in
{
  config = lib.mkIf cfg.enable (
    lib.mkMerge [
      {
        systemd.user.services =
          lib.genAttrs
            (builtins.filter (id: enabled id) [
              "chatgpt-desktop"
              "claude-desktop"
            ])
            (id: {
              description = "Assbox qualified native ${id}";
              wantedBy = lib.optional (launch id) "graphical-session.target";
              partOf = [ "graphical-session.target" ];
              after = [ "graphical-session.target" ];
              unitConfig = {
                ConditionUser = "agent";
                ConditionPathExists = "!%h/.config/assbox/disabled/${id}";
              };
              serviceConfig = common // {
                Restart = "no";
                ExecStart = "${cfg.nativePolicy.runtime}/bin/assbox-native-policy launch ${id}";
              };
            });
      }

      (lib.mkIf (launch "openclaw-dashboard") {
        environment.systemPackages = [ pkgs.chromium ];
      })
      (lib.mkIf (enabled "opencode-server") {
        environment.systemPackages = [
          apps.opencode
        ]
        # Include st's propagated terminfo as well as its executable.
        ++ lib.optional (launch "opencode-attach" && cfg.presentation == "x11") x11Terminal;
        systemd.user.services.assbox-opencode-ui = lib.mkIf (launch "opencode-attach") {
          description = "OpenCode terminal frontend attached to the managed service";
          wantedBy = [ "graphical-session.target" ];
          partOf = [ "graphical-session.target" ];
          after = [
            "graphical-session.target"
            "assbox-opencode.service"
          ];
          wants = [ "assbox-opencode.service" ];
          unitConfig = {
            ConditionUser = "agent";
            ConditionPathExists = [
              "%h/.config/assbox/opencode.env"
              "!%h/.config/assbox/disabled/opencode-server"
            ];
          };
          serviceConfig = common // {
            ExitType = "main";
            ExecStart = "${terminal} ${assboxPackage}/bin/assbox internal opencode attach";
            WorkingDirectory = "%h";
          };
        };
        systemd.user.services.assbox-opencode = {
          description = "OpenCode loopback service";
          wantedBy = [ "default.target" ];
          unitConfig = {
            ConditionUser = "agent";
            ConditionPathExists = [
              "%h/.config/assbox/opencode.env"
              "!%h/.config/assbox/disabled/opencode-server"
            ];
          };
          serviceConfig = common // {
            ExecStart = "${assboxPackage}/bin/assbox internal opencode serve";
            WorkingDirectory = "%h";
          };
        };
      })
      (lib.mkIf (enabled "openclaw-gateway") {
        environment.systemPackages = [
          apps.openclaw
        ];
        systemd.user.services.assbox-openclaw-ui = lib.mkIf (launch "openclaw-dashboard") {
          description = "OpenClaw local Control UI; authenticate in the browser";
          wantedBy = [ "graphical-session.target" ];
          partOf = [ "graphical-session.target" ];
          after = [
            "graphical-session.target"
            "assbox-openclaw.service"
          ];
          wants = [ "assbox-openclaw.service" ];
          unitConfig = {
            ConditionUser = "agent";
            ConditionPathExists = [
              "%h/.openclaw/openclaw.json"
              "!%h/.config/assbox/disabled/openclaw-gateway"
            ];
          };
          serviceConfig = common // {
            ExitType = "main";
            # The fixed public loopback URL has no token, password or secret fragment.
            # A separate persistent profile keeps Chromium from handing the window
            # to an ordinary browser outside this service's cgroup.
            ExecStart = "${pkgs.chromium}/bin/chromium --user-data-dir=%h/.local/share/assbox/openclaw-browser --app=http://127.0.0.1:18789/";
            WorkingDirectory = "%h";
          };
        };
        systemd.user.services.assbox-openclaw = {
          description = "OpenClaw loopback gateway";
          wantedBy = [ "default.target" ];
          unitConfig = {
            ConditionUser = "agent";
            ConditionPathExists = [
              "%h/.openclaw/openclaw.json"
              "!%h/.config/assbox/disabled/openclaw-gateway"
            ];
          };
          serviceConfig = common // {
            # OpenClaw exits successfully when handing a requested restart to
            # systemd. Explicit service stops still suppress automatic restart.
            Restart = "always";
            ExecStart = "${apps.openclaw}/bin/openclaw gateway run --bind loopback --port 18789";
            WorkingDirectory = "%h";
          };
        };
      })
    ]
  );
}
