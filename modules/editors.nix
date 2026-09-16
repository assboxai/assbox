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
  launch = id: builtins.elem id cfg.session.autostart;
  gui = {
    claude-desktop = "${assboxApplications.claude-desktop.claude-desktop}/bin/claude-desktop";
    vscode = "${pkgs.vscode}/bin/code";
    zed = "${pkgs.zed-editor}/bin/zeditor";
    emacs = "${pkgs.emacs}/bin/emacs";
  };
in
{
  options.assbox.components.emacs.variant = lib.mkOption {
    type = lib.types.enum [
      "terminal"
      "gui"
    ];
    default = "terminal";
    description = "Optional Emacs graphical build; no daemon starts implicitly.";
  };
  config = lib.mkIf cfg.enable {
    assertions = [
      {
        assertion =
          !(enabled "vscode-remote-host" || enabled "zed-remote-host") || cfg.network.ssh.agent.enable;
        message = "SSH editor hosts require explicit agent SSH access.";
      }
      {
        assertion =
          !enabled "emacs" || cfg.components.emacs.variant != "gui" || cfg.presentation != "headless";
        message = "Graphical Emacs requires a headed presentation.";
      }
      {
        assertion = !launch "emacs" || cfg.components.emacs.variant == "gui";
        message = "Emacs autostart requires the graphical variant.";
      }
    ];
    # Client-managed VS Code servers are generic Linux binaries. Enable this
    # loader only on explicitly selected hosts; it provides ABI compatibility,
    # not isolation or permission to run privileged code.
    programs.nix-ld = lib.mkIf (enabled "vscode-remote-host" || enabled "vscode-tunnel") {
      enable = true;
      libraries = [
        pkgs.stdenv.cc.cc
        pkgs.zlib
        pkgs.openssl
        pkgs.curl
      ];
    };
    systemd.user.services = lib.mapAttrs' (
      id: executable:
      lib.nameValuePair "assbox-${id}" {
        description = "Assbox ${id} graphical launcher";
        wantedBy = [ "graphical-session.target" ];
        partOf = [ "graphical-session.target" ];
        after = [ "graphical-session.target" ];
        unitConfig = {
          ConditionUser = "agent";
          StartLimitIntervalSec = 0; # Backoff limits retries without permanently stranding the unit.
        };
        serviceConfig = {
          ExecStart = executable;
          ExitType = "cgroup"; # GUI launchers may hand off to a child process.
          WorkingDirectory = "%h";
          Restart = "on-failure";
          RestartSec = 20;
          RestartSteps = 5;
          RestartMaxDelaySec = 300;
          TimeoutStopSec = 60;
          KillMode = "control-group";
          UMask = "0077";
          NoNewPrivileges = true;
          StandardOutput = "null";
          StandardError = "null";
        };
      }
    ) (lib.filterAttrs (id: _: launch id) gui);
  };
}
