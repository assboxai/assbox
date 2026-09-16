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
  enabled = id: cfg.components.${id}.enable;
  ids = [
    "claude-code-remote"
    "cursor-worker"
    "openclaw-node"
    "happy-remote"
    "vscode-tunnel"
  ];
  cli = pkgs.callPackage ../nix/vscode-cli.nix { };
  command = {
    claude-code-remote = [
      "${assboxApplications.claude-code.claude-code}/bin/claude"
      "remote-control"
      "--name"
      cfg.components.claude-code-remote.name
    ];
    cursor-worker = [
      "${assboxApplications.cursor.cursor-agent}/bin/cursor-agent"
      "worker"
      "--name"
      cfg.components.cursor-worker.name
    ]
    ++ lib.optionals cfg.components.cursor-worker.computerUse.enable [
      "--computer-use"
      "--display"
      cfg.components.cursor-worker.computerUse.display
    ]
    ++ [ "start" ];
    openclaw-node = [
      "${assboxApplications.openclaw.openclaw}/bin/openclaw"
      "node"
      "run"
      "--host"
      cfg.components.openclaw-node.gatewayHost
      "--port"
      (toString cfg.components.openclaw-node.gatewayPort)
    ]
    ++ lib.optional cfg.components.openclaw-node.tls "--tls";
    happy-remote = [
      "${assboxApplications.happy.happy-coder}/bin/happy"
      "daemon"
      "start-sync"
    ];
    vscode-tunnel = [
      "${cli}/bin/assbox-vscode"
      "tunnel"
      "--name"
      cfg.components.vscode-tunnel.name
      "--accept-server-license-terms"
    ];
  };
  setupCommands = {
    claude-code-remote = ''
      echo 'Sign in with /login and accept trust for this project; exit Claude when finished.'
      ${assboxApplications.claude-code.claude-code}/bin/claude
      echo 'Accept the one-time Remote confirmation and perform pairing. Stop with Ctrl-C when finished.'
      ${lib.escapeShellArgs command.claude-code-remote} || test "$?" -eq 130
    '';
    cursor-worker = "${assboxApplications.cursor.cursor-agent}/bin/cursor-agent login";
    openclaw-node = ''
      echo 'Configure pairing with your trusted Gateway using OpenClaw before continuing. Do not install its daemon.'
      echo 'A remote Gateway requires TLS; credentials belong only in the agent home.'
      ${assboxApplications.openclaw.openclaw}/bin/openclaw config set nodeHost.workerRuns.enabled ${lib.boolToString cfg.components.openclaw-node.sessionHosting.enable}
      echo 'Start the node interactively to approve its device on the Gateway; stop with Ctrl-C when finished.'
      ${lib.escapeShellArgs command.openclaw-node} || test "$?" -eq 130
    '';
    happy-remote = ''
      echo 'Happy includes the Claude SDK and a companion terminal process; configure only your selected backends in the client.'
      echo 'Stop any manually started Happy daemon before transferring supervision to Assbox.'
      ${assboxApplications.happy.happy-coder}/bin/happy auth login
    '';
    vscode-tunnel = ''
      echo 'The tunnel runs Microsoft client-managed server code. Starting it accepts the VS Code server license.'
      ${cli}/bin/assbox-vscode tunnel user login
    '';
  };
  graphical = id: id == "cursor-worker" && cfg.components.cursor-worker.computerUse.enable;
  marker =
    id:
    ".config/assbox/onboarded/${id}-${
      builtins.substring 0 20 (
        builtins.hashString "sha256" (builtins.toJSON { settings = cfg.components.${id}; })
      )
    }";
  onboard =
    id:
    pkgs.writeShellScript "assbox-onboard-${id}" ''
      set -eu
      test "$(${pkgs.coreutils}/bin/id -un)" = agent
      umask 077
      export HOME=/home/agent
      export PATH=/run/current-system/sw/bin:/run/wrappers/bin
      exec 9>"$XDG_RUNTIME_DIR/assbox-${id}.lock"
      ${pkgs.util-linux}/bin/flock -n 9 || { echo 'Onboarding or diagnostics already owns this service.' >&2; exit 1; }
      ${pkgs.systemd}/bin/systemctl --user stop assbox-${id}.service
      mkdir -p ${lib.escapeShellArg cfg.components.${id}.workingDirectory}
      cd ${lib.escapeShellArg cfg.components.${id}.workingDirectory}
      ( exec 9>&-; ${setupCommands.${id}} )
      printf 'Setup complete and ready to start the Assbox service? Type yes: '
      read -r answer
      test "$answer" = yes
      mkdir -p "$HOME/.config/assbox/onboarded"
      touch "$HOME/${marker id}"
      ${pkgs.systemd}/bin/systemctl --user reset-failed assbox-${id}.service || true
      ${pkgs.systemd}/bin/systemctl --user restart assbox-${id}.service
      echo 'Service start requested. This is not evidence of a successful provider task.'
    '';
  diagnostic =
    id:
    pkgs.writeShellScript "assbox-diagnostic-${id}" (
      builtins.replaceStrings
        [
          "@id@"
          "@flock@"
          "@mkdir@"
          "@chmod@"
          "@mktemp@"
          "@head@"
          "@systemctl@"
          "@systemd-run@"
          "@unit@"
          "@graphical@"
          "@workdir@"
          "@command@"
        ]
        [
          "${pkgs.coreutils}/bin/id"
          "${pkgs.util-linux}/bin/flock"
          "${pkgs.coreutils}/bin/mkdir"
          "${pkgs.coreutils}/bin/chmod"
          "${pkgs.coreutils}/bin/mktemp"
          "${pkgs.coreutils}/bin/head"
          "${pkgs.systemd}/bin/systemctl"
          "${pkgs.systemd}/bin/systemd-run"
          "assbox-${id}"
          (lib.boolToString (graphical id))
          (lib.escapeShellArg cfg.components.${id}.workingDirectory)
          (lib.escapeShellArgs command.${id})
        ]
        (builtins.readFile ./diagnostics/remote.sh)
    );
in
{
  options.assbox.components =
    lib.recursiveUpdate
      (lib.genAttrs ids (_: {
        workingDirectory = lib.mkOption {
          type = lib.types.strMatching "/home/agent/[a-zA-Z0-9_./-]+";
          default = "/home/agent/projects";
          description = "Agent-owned working directory; onboarding creates it if needed.";
        };
        name = lib.mkOption {
          type = lib.types.strMatching "[a-zA-Z0-9_-]{1,40}";
          default = "assbox";
          description = "Public remote machine/session name.";
        };
      }))
      {
        cursor-worker.computerUse = {
          enable = lib.mkEnableOption "Cursor access to the existing Assbox X11 display";
          display = lib.mkOption {
            type = lib.types.strMatching ":[0-9]+(\\.[0-9]+)?";
            default = ":0";
            description = "Explicit X11 display; no virtual-desktop fallback.";
          };
        };
        openclaw-node = {
          gatewayHost = lib.mkOption {
            type = lib.types.strMatching "[a-zA-Z0-9.:-]+";
            default = "127.0.0.1";
            description = "Paired trusted Gateway host.";
          };
          gatewayPort = lib.mkOption {
            type = lib.types.port;
            default = 18789;
            description = "Gateway port.";
          };
          tls = lib.mkOption {
            type = lib.types.bool;
            default = true;
            description = "Require TLS; may be disabled only for loopback Gateway connections.";
          };
          sessionHosting.enable = lib.mkEnableOption "execution of Gateway-provisioned OpenClaw worker artifacts";
        };
        happy-remote.backends = lib.mkOption {
          type = lib.types.listOf (
            lib.types.enum [
              "claude-code"
              "codex"
            ]
          );
          default = [ ];
          description = "Explicitly installed backends for Happy; this is dependency disclosure, not a security allowlist.";
        };
      };
  config = lib.mkIf cfg.enable {
    assertions = [
      {
        assertion =
          !enabled "cursor-worker"
          || !cfg.components.cursor-worker.computerUse.enable
          || cfg.presentation == "x11";
        message = "Cursor computer use requires the existing X11 session.";
      }
      {
        assertion =
          !enabled "openclaw-node"
          || cfg.components.openclaw-node.tls
          || builtins.elem cfg.components.openclaw-node.gatewayHost [
            "localhost"
            "127.0.0.1"
            "::1"
          ];
        message = "Remote OpenClaw Gateways require TLS.";
      }
      {
        assertion =
          !enabled "happy-remote"
          || (
            cfg.components.happy-remote.backends != [ ]
            && builtins.all enabled cfg.components.happy-remote.backends
          );
        message = "Happy requires an explicit nonempty installed backend selection.";
      }
    ]
    ++ map (id: {
      assertion =
        !enabled id || !(builtins.elem ".." (lib.splitString "/" cfg.components.${id}.workingDirectory));
      message = "${id} working directory cannot traverse outside the agent home.";
    }) ids;
    environment.systemPackages =
      lib.optionals (enabled "cursor-worker" && cfg.components.cursor-worker.computerUse.enable)
        [
          pkgs.xdotool
          pkgs.ffmpeg
          pkgs.xwininfo
          pkgs.xrandr
          pkgs.xset
          pkgs.dbus
        ];
    environment.etc = lib.listToAttrs (
      lib.concatMap (id: [
        (lib.nameValuePair "assbox/onboarding/${id}" {
          source = onboard id;
          mode = "0755";
        })
        (lib.nameValuePair "assbox/diagnostics/${id}" {
          source = diagnostic id;
          mode = "0755";
        })
      ]) (builtins.filter enabled ids)
    );
    systemd.user.services = lib.listToAttrs (
      map (
        id:
        lib.nameValuePair "assbox-${id}" {
          description = "Assbox ${id}";
          wantedBy = [ (if graphical id then "graphical-session.target" else "default.target") ];
          partOf = lib.optional (graphical id) "graphical-session.target";
          after = lib.optional (graphical id) "graphical-session.target";
          unitConfig = {
            ConditionUser = "agent";
            ConditionPathExists = "%h/${marker id}";
            StartLimitIntervalSec = 0; # Backoff limits retries without permanently stranding the unit.
          };
          serviceConfig = {
            ExecStart = lib.escapeShellArgs command.${id};
            WorkingDirectory = cfg.components.${id}.workingDirectory;
            Environment = "PATH=/run/current-system/sw/bin:/run/wrappers/bin";
            Restart = "always"; # A supervised server should also recover from a clean unexpected exit.
            RestartSec = 20;
            RestartSteps = 5;
            RestartMaxDelaySec = 300;
            TimeoutStopSec = 60;
            KillMode = "control-group";
            UMask = "0077";
            NoNewPrivileges = true;
            # Pairing URLs and provider tokens must not enter ordinary journal output.
            StandardOutput = "null";
            StandardError = "null";
          };
        }
      ) (builtins.filter enabled ids)
    );
  };
}
