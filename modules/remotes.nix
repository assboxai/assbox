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
    "codex-relay"
    "claude-code-remote"
    "cursor-worker"
    "openclaw-node"
    "happier-daemon"
    "hermes-gateway"
    "hermes-dashboard"
    "antigravity-remote"
    "vscode-tunnel"
  ];
  cli = pkgs.callPackage ../nix/vscode-cli.nix { };
  command = {
    codex-relay = cfg.components.codex-relay.foregroundCommand;
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
    happier-daemon = [
      "${assboxApplications.happier.happier}/bin/happier"
      "daemon"
      "start-sync"
      "--takeover"
    ];
    hermes-gateway = [
      "${assboxApplications.hermes.hermes-agent}/bin/hermes"
      "gateway"
    ];
    hermes-dashboard = [
      "${assboxApplications.hermes.hermes-agent}/bin/hermes"
      "dashboard"
      "--host"
      "127.0.0.1"
      "--port"
      (toString cfg.components.hermes-dashboard.port)
      "--no-open"
      "--isolated"
    ];
    antigravity-remote = cfg.components.antigravity-remote.foregroundCommand;
    vscode-tunnel = [
      "${cli}/bin/assbox-vscode"
      "tunnel"
      "--name"
      cfg.components.vscode-tunnel.name
      "--accept-server-license-terms"
    ];
  };
  setupCommands = {
    codex-relay = ''
      test ${lib.escapeShellArg (builtins.toJSON command.codex-relay)} != "[]" || { echo "Direct Codex relay is experimental; configure and qualify its pinned foreground contract first." >&2; exit 78; }
      ${assboxApplications.codex.codex}/bin/codex login --device-auth
    '';
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
    happier-daemon = ''
      ${assboxApplications.happier.happier}/bin/happier auth login --no-open --method web
      ${assboxApplications.happier.happier}/bin/happier daemon stop
      echo "Happier pairing complete; provider authentication remains independent."
    '';
    hermes-gateway = "${assboxApplications.hermes.hermes-agent}/bin/hermes setup";
    hermes-dashboard = ''
      ${assboxApplications.hermes.hermes-agent}/bin/hermes setup
      echo "Configure native dashboard password/OIDC before using recommended private HTTPS."
      ${assboxApplications.hermes.hermes-agent}/bin/hermes dashboard register
    '';
    antigravity-remote = ''
      test ${lib.escapeShellArg (builtins.toJSON command.antigravity-remote)} != "[]" || { echo "Configure a reviewed pinned foreground runtime; do not run the upstream service installer." >&2; exit 78; }
      ${assboxApplications.antigravity.antigravity-cli}/bin/agy
    '';
    vscode-tunnel = ''
      echo 'The tunnel runs Microsoft client-managed server code. Starting it accepts the VS Code server license.'
      ${cli}/bin/assbox-vscode tunnel user login
    '';
  };
  graphical = _: false;
  environmentFor =
    id:
    (lib.optionalAttrs (id == "happier-daemon") {
      HAPPIER_HOME_DIR = cfg.components.happier-daemon.home;
      HAPPIER_SERVER_URL = cfg.components.happier-daemon.serverUrl;
      HAPPIER_WEBAPP_URL = cfg.components.happier-daemon.webappUrl;
      HAPPIER_ENCRYPTION_REQUIREMENT = "require_e2ee";
      HAPPIER_DAEMON_STARTUP_SOURCE = "background-service";
      HAPPIER_DAEMON_SERVICE_LABEL = "assbox-happier-daemon.service";
      HAPPIER_DAEMON_SERVICE_TARGET_MODE = "default-following";
      HAPPIER_NO_BROWSER_OPEN = "1";
    })
    // (lib.optionalAttrs (id == "happier-daemon") (
      lib.listToAttrs (
        lib.concatMap
          (
            entry:
            lib.optional (enabled entry.id) (
              lib.nameValuePair entry.env "${
                assboxApplications.${entry.family}.${entry.package}
              }/bin/${entry.command}"
            )
          )
          [
            {
              id = "codex";
              env = "HAPPIER_CODEX_PATH";
              family = "codex";
              package = "codex";
              command = "codex";
            }
            {
              id = "claude-code";
              env = "HAPPIER_CLAUDE_PATH";
              family = "claude-code";
              package = "claude-code";
              command = "claude";
            }
            {
              id = "cursor-agent";
              env = "HAPPIER_CURSOR_PATH";
              family = "cursor";
              package = "cursor-agent";
              command = "cursor-agent";
            }
            {
              id = "grok";
              env = "HAPPIER_GROK_PATH";
              family = "grok";
              package = "grok";
              command = "grok";
            }
            {
              id = "opencode";
              env = "HAPPIER_OPENCODE_PATH";
              family = "opencode";
              package = "opencode";
              command = "opencode";
            }
            {
              id = "antigravity-cli";
              env = "HAPPIER_ANTIGRAVITY_PATH";
              family = "antigravity";
              package = "antigravity-cli";
              command = "agy";
            }
          ]
      )
    ))
    // (lib.optionalAttrs
      (builtins.elem id [
        "hermes-gateway"
        "hermes-dashboard"
      ])
      {
        HERMES_HOME = cfg.components.hermes-gateway.home;
        HERMES_DISABLE_LAZY_INSTALLS = "1";
      }
    )
    // (lib.optionalAttrs (
      id == "hermes-dashboard" && cfg.components.hermes-dashboard.accessProfile == "authenticated"
    ) { HERMES_DASHBOARD_PUBLIC_URL = cfg.components.hermes-dashboard.publicUrl; });
  available =
    id:
    !(builtins.elem id [
      "antigravity-remote"
      "codex-relay"
    ])
    || command.${id} != [ ];
  publicHttpsUrl =
    url:
    let
      match = builtins.match "https://([a-zA-Z0-9.-]+)(:([0-9]+))?(/[a-zA-Z0-9._:/-]*)?" url;
      host = if match == null then "" else lib.removeSuffix "." (lib.toLower (builtins.elemAt match 0));
      port = if match == null then null else builtins.elemAt match 2;
      parts = lib.splitString "." host;
      numeric = builtins.all (p: builtins.match "[0-9]+" p != null) parts;
    in
    match != null
    && (port == null || (builtins.match "[1-9][0-9]{0,4}" port != null && lib.toInt port <= 65535))
    && builtins.length parts >= 2
    && host != "localhost"
    && !(lib.hasSuffix ".localhost" host)
    && builtins.all (p: builtins.match "[a-z0-9]([a-z0-9-]*[a-z0-9])?" p != null) parts
    && (
      if numeric then
        builtins.length parts == 4
        && !(builtins.elem (builtins.head parts) [
          "0"
          "127"
        ])
        && builtins.all (p: builtins.match "(0|[1-9][0-9]{0,2})" p != null && lib.toInt p <= 255) parts
      else
        builtins.match "[a-z].*" (lib.last parts) != null
    );
  marker =
    id:
    ".config/assbox/onboarded/${id}-${
      builtins.substring 0 20 (
        builtins.hashString "sha256" (
          builtins.toJSON {
            settings = cfg.components.${id};
            argv = command.${id};
            environment = environmentFor id;
            computerUse = cfg.computerUse.mode;
          }
        )
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
      ${lib.concatMapStringsSep "\n" (
        key: "export ${key}=${lib.escapeShellArg (environmentFor id).${key}}"
      ) (builtins.attrNames (environmentFor id))}
      exec 9>"$XDG_RUNTIME_DIR/assbox-${id}.lock"
      ${pkgs.util-linux}/bin/flock -n 9 || { echo 'Onboarding or diagnostics already owns this service.' >&2; exit 1; }
      ${lib.optionalString (available id) "${pkgs.systemd}/bin/systemctl --user stop assbox-${id}.service"}
      mkdir -p ${lib.escapeShellArg cfg.components.${id}.workingDirectory}
      cd ${lib.escapeShellArg cfg.components.${id}.workingDirectory}
      ( exec 9>&-; ${setupCommands.${id}} )
      printf 'Setup complete and ready to start the Assbox service? Type yes: '
      read -r answer
      test "$answer" = yes
      mkdir -p "$HOME/.config/assbox/onboarded"
      rm -f "$HOME/.config/assbox/disabled/${id}"
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
          enable = lib.mkOption {
            type = lib.types.bool;
            default = cfg.computerUse.mode == "virtual-desktop";
            description = "Cursor access to its private provider-managed desktop.";
          };
          display = lib.mkOption {
            type = lib.types.strMatching ":[0-9]+(\\.[0-9]+)?";
            default = ":90";
            description = "Private execution display; the physical controller display is forbidden.";
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
        happier-daemon = {
          serverUrl = lib.mkOption {
            type = lib.types.strMatching "https://[a-zA-Z0-9._:/-]+";
            default = "https://api.happier.dev";
          };
          webappUrl = lib.mkOption {
            type = lib.types.strMatching "https://[a-zA-Z0-9._:/-]+";
            default = "https://app.happier.dev";
          };
          home = lib.mkOption {
            type = lib.types.strMatching "/home/agent/[a-zA-Z0-9_./-]+";
            default = "/home/agent/.happier";
          };
        };
        hermes-gateway.home = lib.mkOption {
          type = lib.types.strMatching "/home/agent/[a-zA-Z0-9_./-]+";
          default = "/home/agent/.hermes";
        };
        hermes-dashboard = {
          port = lib.mkOption {
            type = lib.types.port;
            default = 9119;
          };
          publicUrl = lib.mkOption {
            type = lib.types.str;
            default = "";
            description = "Exact non-loopback HTTPS URL, required for native dashboard auth behind a proxy.";
          };
          accessProfile = lib.mkOption {
            type = lib.types.enum [
              "authenticated"
              "tunnel-only"
            ];
            default = "authenticated";
          };
          consentTunnelOnly = lib.mkEnableOption "explicit Advanced tunnel-only access without native app auth";
        };
        codex-relay.foregroundCommand = lib.mkOption {
          type = lib.types.listOf lib.types.str;
          default = [ ];
          description = "Advanced exact pinned Codex relay foreground argv; empty stages an unavailable experiment.";
        };
        antigravity-remote.foregroundCommand = lib.mkOption {
          type = lib.types.listOf lib.types.str;
          default = [ ];
          description = "Reviewed immutable foreground argv from the selected vendor service contract, not agy remote-control start.";
        };

      };
  config = lib.mkIf cfg.enable {
    assertions = [
      {
        assertion =
          !enabled "cursor-worker"
          || !cfg.components.cursor-worker.computerUse.enable
          || (
            cfg.computerUse.mode == "virtual-desktop"
            && cfg.components.cursor-worker.computerUse.display != ":0"
          );
        message = "Cursor computer use requires the explicitly selected private virtual desktop.";
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
          !enabled "hermes-dashboard"
          || (
            if cfg.components.hermes-dashboard.accessProfile == "authenticated" then
              publicHttpsUrl cfg.components.hermes-dashboard.publicUrl
            else
              cfg.components.hermes-dashboard.consentTunnelOnly
          );
        message = "Hermes recommended dashboard requires a non-loopback HTTPS public URL; tunnel-only requires explicit consent.";
      }
      {
        assertion =
          !enabled "antigravity-remote"
          || command.antigravity-remote == [ ]
          || lib.hasPrefix "/nix/store/" (builtins.head command.antigravity-remote);
        message = "Antigravity foreground contract must use pinned Nix runtime code.";
      }
      {
        assertion = !enabled "codex-relay" || command.codex-relay == [ ] || !enabled "happier-daemon";
        message = "Direct Codex relay and Happier daemon coexistence is not qualified; explicitly retire one route before activating the other.";
      }
    ]
    ++ map (id: {
      assertion =
        !enabled id || command.${id} == [ ] || lib.hasPrefix "/nix/store/" (builtins.head command.${id});
      message = "${id} requires an immutable pinned foreground executable.";
    }) [ "codex-relay" ]
    ++ map (id: {
      assertion =
        !enabled id || !(builtins.elem ".." (lib.splitString "/" cfg.components.${id}.workingDirectory));
      message = "${id} working directory cannot traverse outside the agent home.";
    }) ids
    ++
      map
        (entry: {
          assertion =
            !(builtins.any enabled entry.ids)
            || builtins.all (part: part != "" && part != "." && part != "..") (
              lib.splitString "/" (lib.removePrefix "/home/agent/" entry.home)
            );
          message = "${entry.label} state home must be a normalized directory inside /home/agent.";
        })
        [
          {
            ids = [ "happier-daemon" ];
            label = "Happier";
            home = cfg.components.happier-daemon.home;
          }
          {
            ids = [
              "hermes-gateway"
              "hermes-dashboard"
            ];
            label = "Hermes";
            home = cfg.components.hermes-gateway.home;
          }
        ];
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
        })
        (lib.nameValuePair "assbox/diagnostics/${id}" {
          source = diagnostic id;
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
            ConditionPathExists = [
              "%h/${marker id}"
              "!%h/.config/assbox/disabled/${id}"
            ];
            StartLimitIntervalSec = 0; # Backoff limits retries without permanently stranding the unit.
          };
          environment = environmentFor id;
          serviceConfig = {
            ExecStart = lib.escapeShellArgs (
              (lib.optionals
                (
                  cfg.computerUse.mode == "virtual-desktop"
                  && builtins.elem id [
                    "cursor-worker"
                    "hermes-gateway"
                  ]
                )
                [
                  "${cfg.computerUse.runtime}/bin/assbox-computer-use-runtime"
                  (if id == "cursor-worker" then "provider" else "display")
                  "--"
                ]
              )
              ++ command.${id}
            );
            UnsetEnvironment = [
              "DISPLAY"
              "WAYLAND_DISPLAY"
              "XAUTHORITY"
              "DBUS_SESSION_BUS_ADDRESS"
              "AT_SPI_BUS_ADDRESS"
              "SSH_AUTH_SOCK"
            ];
            MemoryMax = lib.mkIf (
              cfg.computerUse.mode == "virtual-desktop"
            ) "${toString cfg.computerUse.memoryMaxMiB}M";
            WorkingDirectory = cfg.components.${id}.workingDirectory;
            Environment = "PATH=/run/current-system/sw/bin:/run/wrappers/bin";
            RestartPreventExitStatus = [
              64
              65
              77
              78
            ];
            # Remote providers are persistent servers. Recover both clean and
            # failed exits; explicit stops remain stopped, and the declared
            # permanent refusal statuses above still suppress restart.
            Restart = "always";
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
      ) (builtins.filter (id: enabled id && available id) ids)
    );
  };
}
