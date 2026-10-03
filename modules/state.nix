# SPDX-License-Identifier: GPL-3.0-or-later
{
  config,
  lib,
  pkgs,
  ...
}:
let
  cfg = config.assbox;
  state = cfg.state;
  selected = id: cfg.components.${id}.enable;
  webApps = cfg.kiosk.webApps or [ ];
  paths = lib.unique (
    [ ".config/assbox" ]
    ++ lib.optionals (selected "codex") [ ".codex" ]
    ++ lib.optionals (selected "claude-code") [
      ".claude"
      ".claude.json"
    ]
    ++ lib.optionals (selected "happier") [ ".happier" ]
    ++ lib.optionals (selected "happier-daemon") [
      (lib.removePrefix "/home/agent/" cfg.components.happier-daemon.home)
    ]
    ++ lib.optionals (selected "hermes") [ ".hermes" ]
    ++ lib.optionals (selected "hermes-gateway" || selected "hermes-dashboard") [
      (lib.removePrefix "/home/agent/" cfg.components.hermes-gateway.home)
    ]
    ++ lib.optionals (selected "openclaw") [ ".openclaw" ]
    ++ lib.optionals (selected "opencode") [
      ".config/opencode"
      ".local/share/opencode"
    ]
    ++ lib.optionals (selected "pi") [ ".pi" ]
    ++ lib.optionals (selected "omp") [ ".omp" ]
    ++ lib.optionals (selected "chatgpt-desktop") [ ".config/ChatGPT" ]
    ++ lib.optionals (selected "claude-desktop") [ ".config/Claude" ]
    ++ map (site: ".local/share/assbox/web-${site}") webApps
    ++ lib.optional (builtins.elem "openclaw-dashboard" cfg.session.autostart) ".local/share/assbox/openclaw-browser"
    ++ state.additionalPaths
  );
  units = [
    "assbox-opencode-ui.service"
    "assbox-openclaw-ui.service"
  ]
  ++
    map
      (
        id:
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
      )
      (
        builtins.filter selected [
          "happier-daemon"
          "hermes-gateway"
          "hermes-dashboard"
          "claude-code-remote"
          "cursor-worker"
          "codex-relay"
          "antigravity-remote"
          "vscode-tunnel"
          "openclaw-node"
          "chatgpt-desktop"
          "claude-desktop"
        ]
      )
  ++ lib.optional (selected "openclaw-gateway") "assbox-openclaw.service"
  ++ lib.optional (selected "opencode-server") "assbox-opencode.service"
  ++ map (site: "assbox-web-${site}.service") webApps
  ++ map (id: "assbox-${id}.service") (
    builtins.filter (id: builtins.elem id cfg.session.autostart) [
      "chromium"
      "vscode"
      "zed"
      "emacs"
    ]
  );
  helper = pkgs.writeShellScriptBin "assbox-state" ''
    exec ${pkgs.python3}/bin/python3 ${../scripts/state/snapshot.py} "$@"
  '';
in
{
  options.assbox.state = {
    backupBeforeUpdate = lib.mkEnableOption "an owner-approved mutable-state checkpoint before scheduled OS updates";
    directory = lib.mkOption {
      type = lib.types.strMatching "/[a-zA-Z0-9_./-]+";
      default = "/var/lib/assbox-state-backups";
    };
    maxArchiveMiB = lib.mkOption {
      type = lib.types.ints.between 128 1048576;
      default = 16384;
    };
    reserveMiB = lib.mkOption {
      type = lib.types.ints.between 512 65536;
      default = 2048;
    };
    retain = lib.mkOption {
      type = lib.types.ints.between 1 32;
      default = 3;
    };
    timeoutSeconds = lib.mkOption {
      type = lib.types.ints.between 60 7200;
      default = 900;
    };
    additionalPaths = lib.mkOption {
      type = lib.types.listOf (lib.types.strMatching "[a-zA-Z0-9_.-]+(/[a-zA-Z0-9_.-]+)*");
      default = [ ];
      description = "Explicit additional relative agent-home data paths; repositories are not included by default.";
    };
  };
  config = lib.mkIf cfg.enable {
    assertions = [
      {
        assertion = builtins.all (
          p: !(builtins.any (part: part == "." || part == "..") (lib.splitString "/" p))
        ) (paths ++ [ state.directory ]);
        message = "State paths cannot traverse outside their scoped root.";
      }
      {
        assertion = builtins.all (
          p: builtins.all (other: p == other || !(lib.hasPrefix "${p}/" other)) paths
        ) paths;
        message = "State checkpoint paths must not overlap; select the parent or its individual children.";
      }
    ];
    environment.systemPackages = [ helper ];
    environment.etc."assbox/state-helper".source = "${helper}/bin/assbox-state";
    environment.etc."assbox/state.json".text = builtins.toJSON {
      inherit paths units;
      inherit (state)
        directory
        retain
        timeoutSeconds
        maxArchiveMiB
        reserveMiB
        ;
      runuser = "${pkgs.util-linux}/bin/runuser";
      tar = "${pkgs.gnutar}/bin/tar";
      systemctl = "${pkgs.systemd}/bin/systemctl";
      loginctl = "${pkgs.systemd}/bin/loginctl";
    };
    systemd.services.assbox-maintenance.serviceConfig.ExecStartPre = lib.mkIf (
      cfg.updates.enable && state.backupBeforeUpdate
    ) [ "${helper}/bin/assbox-state backup" ];
  };
}
