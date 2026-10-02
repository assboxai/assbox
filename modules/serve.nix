# SPDX-License-Identifier: GPL-3.0-or-later
{
  config,
  lib,
  pkgs,
  ...
}:
let
  cfg = config.assbox;
  mappings = cfg.network.tailscale.serveMappings;
  runtime = pkgs.writeShellScriptBin "assbox-serve" ''
    exec ${pkgs.python3}/bin/python3 ${../scripts/access/serve.py} "$@"
  '';
  policy = pkgs.writeText "assbox-serve.json" (
    builtins.toJSON {
      inherit mappings;
      tailscale = if cfg.network.tailscale.enable then "${pkgs.tailscale}/bin/tailscale" else null;
    }
  );
in
{
  options.assbox.network.tailscale.serveMappings = lib.mkOption {
    type = lib.types.listOf (
      lib.types.submodule {
        options = {
          component = lib.mkOption {
            type = lib.types.enum [
              "hermes-dashboard"
              "openclaw-gateway"
              "opencode-server"
            ];
          };
          publicUrl = lib.mkOption {
            type = lib.types.strMatching "https://[a-zA-Z0-9.-]+(:[0-9]+)?(/[a-zA-Z0-9._/-]*)?";
          };
          port = lib.mkOption { type = lib.types.port; };
        };
      }
    );
    default = [ ];
    description = "Explicit owner-approved private HTTPS dashboard paths; enrollment, grants and application authentication remain separate.";
  };
  config = lib.mkIf cfg.enable {
    assertions = [
      {
        assertion = mappings == [ ] || cfg.network.tailscale.enable;
        message = "Private dashboard Serve requires Tailscale support and separate owner enrollment.";
      }
      {
        assertion = builtins.all (m: cfg.components.${m.component}.enable) mappings;
        message = "A Serve mapping may publish only its explicitly selected dashboard.";
      }
      {
        assertion = builtins.all (
          m:
          (m.component != "openclaw-gateway" || m.port == 18789)
          && (m.component != "opencode-server" || m.port == 4096)
        ) mappings;
        message = "Serve mappings must use the selected dashboard's managed loopback port.";
      }
      {
        assertion = builtins.all (
          m:
          m.component != "hermes-dashboard"
          || (
            m.publicUrl == cfg.components.hermes-dashboard.publicUrl
            && m.port == cfg.components.hermes-dashboard.port
            && cfg.components.hermes-dashboard.accessProfile == "authenticated"
          )
        ) mappings;
        message = "Hermes Serve must match its exact authenticated public URL and backend port.";
      }
    ];
    environment.etc."assbox/serve.json".source = policy;
    assbox.serviceControl.serve = "${runtime}/bin/assbox-serve";
    # Activation withdraws the old owned paths before user services are replaced.
    system.activationScripts.assbox-serve-withdraw = {
      deps = [ "etc" ];
      text = ''
        if test -s /var/lib/assbox-serve/owned.json; then
          ${runtime}/bin/assbox-serve withdraw ${policy}
        fi
      '';
    };
    systemd.services.assbox-serve = lib.mkIf cfg.network.tailscale.enable {
      description = "Reconcile explicitly approved private dashboard paths";
      after = [ "tailscaled.service" ];
      serviceConfig = {
        Type = "oneshot";
        ExecStart = "${runtime}/bin/assbox-serve reconcile ${policy}";
        UMask = "0077";
        TimeoutStartSec = "90s";
        SuccessExitStatus = [ 78 ];
      };
    };
    systemd.timers.assbox-serve = lib.mkIf cfg.network.tailscale.enable {
      wantedBy = [ "timers.target" ];
      timerConfig = {
        OnBootSec = "30s";
        OnUnitInactiveSec = "30s";
      };
    };
    systemd.services.tailscaled.serviceConfig.ExecStopPre = lib.mkIf cfg.network.tailscale.enable [
      "${runtime}/bin/assbox-serve withdraw ${policy}"
    ];
  };
}
