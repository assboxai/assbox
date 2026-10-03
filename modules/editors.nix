# SPDX-License-Identifier: GPL-3.0-or-later
{
  config,
  lib,
  pkgs,
  ...
}:
let
  cfg = config.assbox;
  enabled = id: cfg.components.${id}.enable;
  launch = id: builtins.elem id cfg.session.autostart;
  gui = {
    chromium = "${pkgs.chromium}/bin/chromium --no-default-browser-check";
    vscode = "${import ../nix/vscode-gui.nix { inherit pkgs; }}/bin/assbox-vscode-gui";
    # The CLI detaches; even its --foreground mode discards the child's status.
    # This is the upstream Nix-wrapped application, including its runtime PATH.
    zed = "${pkgs.zed-editor}/libexec/zed-editor";
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
    # Desktop extensions and language servers can be generic GNU/Linux binaries,
    # including on remote project hosts. Zed's musl remote server itself does not
    # need this loader. This supplies ABI compatibility, not isolation or privilege.
    programs.nix-ld =
      lib.mkIf
        (builtins.any enabled [
          "vscode"
          "zed"
          "vscode-remote-host"
          "zed-remote-host"
          "vscode-tunnel"
        ])
        {
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
          ConditionPathExists = "!%h/.config/assbox/disabled/${id}";
          StartLimitIntervalSec = 0; # Backoff limits retries without permanently stranding the unit.
        };
        serviceConfig = {
          ExecStart = executable;
          # Each entry point stays foreground and preserves the app exit status.
          # A crash stops leftover children before restart; normal close stays closed.
          ExitType = "main";
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
