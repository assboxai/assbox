# SPDX-License-Identifier: GPL-3.0-or-later
{
  config,
  lib,
  pkgs,
  assboxApplications,
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
  terminal =
    if cfg.presentation == "wayland" then "${pkgs.foot}/bin/foot" else "${pkgs.xterm}/bin/xterm -e";
  chatgpt = apps.chatgpt.override {
    commandLineArgs = "--ozone-platform=x11 --password-store=basic --force-device-scale-factor=${toString cfg.display.scale}";
  };
in
{
  config = lib.mkIf cfg.enable (
    lib.mkMerge [
      (lib.mkIf (launch "openclaw-dashboard") {
        environment.systemPackages = [ pkgs.chromium ];
      })
      (lib.mkIf (enabled "chatgpt-desktop") {
        environment.systemPackages = [
          chatgpt
        ];
        systemd.user.services.assbox-chatgpt = lib.mkIf (launch "chatgpt-desktop") {
          description = "ChatGPT Linux graphical application";
          wantedBy = [ "graphical-session.target" ];
          partOf = [ "graphical-session.target" ];
          after = [ "graphical-session.target" ];
          unitConfig.ConditionUser = "agent";
          serviceConfig = common // {
            ExecStart = "${chatgpt}/bin/chatgpt";
            ExitType = "main";
          };
        };
      })
      (lib.mkIf (enabled "opencode-server") {
        environment.systemPackages = [ apps.opencode ];
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
            ConditionPathExists = "%h/.config/assbox/opencode.env";
          };
          serviceConfig = common // {
            ExitType = "main";
            EnvironmentFile = "%h/.config/assbox/opencode.env";
            ExecStart = "${terminal} ${apps.opencode}/bin/opencode attach http://127.0.0.1:4096";
            WorkingDirectory = "%h";
          };
        };
        systemd.user.services.assbox-opencode = {
          description = "OpenCode loopback service";
          wantedBy = [ "default.target" ];
          unitConfig = {
            ConditionUser = "agent";
            ConditionPathExists = "%h/.config/assbox/opencode.env";
          };
          serviceConfig = common // {
            EnvironmentFile = "%h/.config/assbox/opencode.env";
            ExecStart = "${apps.opencode}/bin/opencode serve --hostname 127.0.0.1 --port 4096";
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
            ConditionPathExists = "%h/.openclaw/openclaw.json";
          };
          serviceConfig = common // {
            ExitType = "main";
            # The fixed public loopback URL has no token, password or secret fragment.
            ExecStart = "${pkgs.chromium}/bin/chromium --app=http://127.0.0.1:18789/";
            WorkingDirectory = "%h";
          };
        };
        systemd.user.services.assbox-openclaw = {
          description = "OpenClaw loopback gateway";
          wantedBy = [ "default.target" ];
          unitConfig = {
            ConditionUser = "agent";
            ConditionPathExists = "%h/.openclaw/openclaw.json";
          };
          serviceConfig = common // {
            ExecStart = "${apps.openclaw}/bin/openclaw gateway run --bind loopback --port 18789";
            WorkingDirectory = "%h";
          };
        };
      })
    ]
  );
}
