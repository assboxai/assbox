# SPDX-License-Identifier: GPL-3.0-or-later
{
  config,
  lib,
  pkgs,
  ...
}:
let
  cfg = config.assbox;
  helper = pkgs.writeShellScript "assbox-service-control" ''
    exec ${pkgs.python3}/bin/python3 ${../scripts/access/service.py} "$@"
  '';
  remoteIds = [
    "happier-daemon"
    "hermes-gateway"
    "hermes-dashboard"
    "claude-code-remote"
    "cursor-worker"
    "openclaw-node"
    "vscode-tunnel"
    "codex-relay"
    "antigravity-remote"
    "chatgpt-desktop"
    "claude-desktop"
  ];
  gui = builtins.filter (id: builtins.elem id cfg.session.autostart) [
    "chromium"
    "vscode"
    "zed"
    "emacs"
  ];
  webApps = cfg.kiosk.webApps or [ ];
  units =
    lib.genAttrs
      (builtins.filter (
        id:
        cfg.components.${id}.enable
        && (
          !(builtins.elem id [
            "codex-relay"
            "antigravity-remote"
          ])
          || cfg.components.${id}.foregroundCommand != [ ]
        )
      ) remoteIds)
      (id: [
        "${
          if
            builtins.elem id [
              "chatgpt-desktop"
              "claude-desktop"
            ]
          then
            id
          else
            "assbox-${id}"
        }.service"
      ])
    // lib.optionalAttrs cfg.components.openclaw-gateway.enable {
      openclaw-gateway =
        lib.optional (builtins.elem "openclaw-dashboard" cfg.session.autostart) "assbox-openclaw-ui.service"
        ++ [ "assbox-openclaw.service" ];
    }
    // lib.optionalAttrs cfg.components.opencode-server.enable {
      opencode-server =
        lib.optional (builtins.elem "opencode-attach" cfg.session.autostart) "assbox-opencode-ui.service"
        ++ [ "assbox-opencode.service" ];
    }
    // lib.genAttrs gui (id: [ "assbox-${id}.service" ])
    // lib.optionalAttrs (webApps != [ ]) {
      chromium =
        lib.optional (builtins.elem "chromium" gui) "assbox-chromium.service"
        ++ map (site: "assbox-web-${site}.service") webApps;
    };
in
{
  options.assbox.serviceControl.serve = lib.mkOption {
    type = lib.types.nullOr lib.types.str;
    default = null;
    internal = true;
  };
  config = lib.mkIf cfg.enable {
    environment.etc."assbox/service-helper".source = helper;
    environment.etc."assbox/service-control.json".text = builtins.toJSON {
      inherit units;
      inherit (cfg.serviceControl) serve;
      runuser = "${pkgs.util-linux}/bin/runuser";
      python = "${pkgs.python3}/bin/python3";
      systemctl = "${pkgs.systemd}/bin/systemctl";
    };
  };
}
