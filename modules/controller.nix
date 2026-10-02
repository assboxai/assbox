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
  catalog = builtins.fromJSON (builtins.readFile ../catalog/components.json);
  selected = builtins.filter (row: cfg.components.${row.id}.enable) catalog;
  native = builtins.filter (id: cfg.components.${id}.enable) [
    "chatgpt-desktop"
    "claude-desktop"
  ];
  active = cfg.enable && (cfg.worker.enable || native != [ ] || cfg.kiosk.webApps != [ ]);
  runtime = pkgs.writeShellScriptBin "assbox-native-policy" ''
    exec ${pkgs.python3}/bin/python3 ${../scripts/native/policy.py} "$@"
  '';
  raw = {
    chatgpt-desktop = assboxApplications.chatgpt.chatgpt;
    claude-desktop = assboxApplications.claude-desktop.claude-desktop;
  };
  command = {
    chatgpt-desktop = "chatgpt";
    claude-desktop = "claude-desktop";
  };
  contractType = lib.types.submodule {
    options = {
      id = lib.mkOption { type = lib.types.strMatching "[a-zA-Z0-9_.-]+"; };
      qualification = lib.mkOption {
        type = lib.types.path;
        description = "Reviewed exact-client/platform/account enforcement evidence.";
      };
      probe = lib.mkOption {
        type = lib.types.path;
        description = "Immutable bounded effective-policy probe, never an execution-owned marker.";
      };
      accountScopeDigest = lib.mkOption {
        type = lib.types.strMatching "[0-9a-f]{64}";
        description = "Non-secret digest of the qualified account, workspace and entitlement scope.";
      };
    };
  };
in
{
  options.assbox = {
    controller = {
      active = lib.mkOption { default = active; };
      profile = lib.mkOption {
        default =
          if !cfg.enable then
            "none"
          else if native != [ ] then
            "native-kiosk"
          else if cfg.kiosk.webApps != [ ] then
            "web-kiosk"
          else if active then
            "generic"
          else
            "none";
      };
    };
    kiosk = {
      localExecution = lib.mkOption {
        type = lib.types.enum [
          "none"
          "managed-worker"
        ];
        default = "none";
        description = "Requested native policy; activation separately requires verified effective controls.";
      };
      webApps = lib.mkOption {
        type = lib.types.listOf (
          lib.types.enum [
            "chatgpt"
            "claude"
          ]
        );
        default = [ ];
      };
      cloud.enable = lib.mkEnableOption "explicit cloud task/data capability";
      claudeLocalCowork = lib.mkEnableOption "an entitled, independently qualified local provider VM";
      claudeLocalCoworkPrerequisites = lib.mkOption {
        type = lib.types.listOf lib.types.package;
        default = [
          pkgs.qemu
          pkgs.virtiofsd
        ]
        ++ lib.optional pkgs.stdenv.hostPlatform.isx86_64 pkgs.OVMF.fd;
        description = "Pinned provider VM prerequisites; override with the exact qualified architecture-specific firmware/helper closure. No implicit device groups.";
      };
      claudeLocalCoworkContract = lib.mkOption {
        type = lib.types.nullOr contractType;
        default = null;
      };
    };
    nativePolicy = {
      contracts = lib.mkOption {
        type = lib.types.attrsOf contractType;
        default = { };
        description = "Exact native release contracts; absence leaves the selected client inactive.";
      };
      maximumAgeSeconds = lib.mkOption {
        type = lib.types.ints.between 20 120;
        default = 45;
      };
      runtime = lib.mkOption {
        type = lib.types.package;
        internal = true;
        readOnly = true;
      };
    };
  };
  config = lib.mkIf cfg.enable {
    assbox.nativePolicy.runtime = runtime;
    assertions = [
      {
        assertion = !active || builtins.all (row: row.controllerAllowed) selected;
        message = "Move execution components away from the sensitive controller into the worker or a standalone instance.";
      }
      {
        assertion = cfg.kiosk.localExecution != "managed-worker" || cfg.worker.enable;
        message = "Protected local Code requires the explicitly configured Assbox worker.";
      }
      {
        assertion =
          cfg.kiosk.localExecution != "managed-worker"
          || !cfg.components.chatgpt-desktop.enable
          || builtins.elem "codex" cfg.worker.components;
        message = "Protected ChatGPT Code requires worker Codex.";
      }
      {
        assertion =
          cfg.kiosk.localExecution != "managed-worker"
          || !cfg.components.claude-desktop.enable
          || builtins.elem "claude-code" cfg.worker.components;
        message = "Protected Claude Code requires worker Claude Code.";
      }
      {
        assertion =
          !cfg.kiosk.claudeLocalCowork
          || (cfg.components.claude-desktop.enable && cfg.kiosk.claudeLocalCoworkContract != null);
        message = "Local Cowork requires its own entitled build, provider VM contract and qualification.";
      }
      {
        assertion = builtins.all (
          id:
          builtins.elem id [
            "chatgpt-desktop"
            "claude-desktop"
          ]
        ) (builtins.attrNames cfg.nativePolicy.contracts);
        message = "Unknown native client policy contract.";
      }
    ];
    nix.settings.allowed-users = lib.mkIf active [ "root" ];
    environment.systemPackages =
      lib.optional (native != [ ]) runtime
      ++ lib.optionals cfg.kiosk.claudeLocalCowork cfg.kiosk.claudeLocalCoworkPrerequisites;
    environment.etc."assbox/native-policy.json".text = builtins.toJSON {
      inherit (cfg.nativePolicy) maximumAgeSeconds;
      apps = lib.genAttrs native (id: {
        client = "${raw.${id}}/bin/${command.${id}}";
        platform = pkgs.stdenv.hostPlatform.system;
        mode = cfg.kiosk.localExecution;
        contract = cfg.nativePolicy.contracts.${id} or null;
        cloud = cfg.kiosk.cloud.enable;
        localCowork = id == "claude-desktop" && cfg.kiosk.claudeLocalCowork;
        providerVmContract = if id == "claude-desktop" then cfg.kiosk.claudeLocalCoworkContract else null;
      });
    };
    systemd.services.assbox-native-policy = lib.mkIf (native != [ ]) {
      description = "Observe effective native kiosk authority";
      wantedBy = [ "multi-user.target" ];
      before = [ "display-manager.service" ];
      serviceConfig = {
        Type = "oneshot";
        ExecStart = "${runtime}/bin/assbox-native-policy refresh";
        UMask = "0022";
      };
    };
    systemd.timers.assbox-native-policy = lib.mkIf (native != [ ]) {
      wantedBy = [ "timers.target" ];
      timerConfig = {
        OnBootSec = "5s";
        OnUnitActiveSec = "15s";
        AccuracySec = "1s";
      };
    };
  };
}
