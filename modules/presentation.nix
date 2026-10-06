# SPDX-License-Identifier: GPL-3.0-or-later
{
  config,
  lib,
  pkgs,
  ...
}:
let
  cfg = config.assbox;
  graphicalUnits = lib.mapAttrsToList (name: _: "${name}.service") (
    lib.filterAttrs (
      name: unit:
      lib.hasPrefix "assbox-" name && builtins.elem "graphical-session.target" (unit.partOf or [ ])
    ) config.systemd.user.services
  );
  sessionSystemctl = pkgs.writeShellScript "assbox-session-systemctl" ''
    set -e
    if [[ $# -eq 4 && "$1" == --user && "$2" == stop \
      && "$3" == assbox-graphical-session.target && "$4" == graphical-session.target ]]; then
      ${pkgs.systemd}/bin/systemctl "$@"
      # The target is fully stopped. GUI processes can report an X-disconnect
      # error during logout; retire only this session's Assbox service state.
      # Crashes in an active session retain their restart policy and counters.
      ${lib.optionalString (graphicalUnits != [ ]) ''
        for unit in ${lib.escapeShellArgs graphicalUnits}; do
          if ${pkgs.systemd}/bin/systemctl --user is-failed --quiet "$unit"; then
            ${pkgs.systemd}/bin/systemctl --user reset-failed "$unit"
          fi
        done
      ''}
      exit 0
    fi
    exec ${pkgs.systemd}/bin/systemctl "$@"
  '';
  stopGraphicalSession = pkgs.writeShellScript "assbox-stop-graphical-session" ''
    set -eu
    runtime=/run/user/1000
    # A display-manager stop can terminate its entire control group before the
    # session shell's EXIT trap runs. If the lingering user manager is present,
    # enforce the same narrowly scoped graphical cleanup from the system unit.
    [[ -S "$runtime/bus" ]] || exit 0
    exec ${pkgs.util-linux}/bin/runuser -u agent -- \
      ${pkgs.coreutils}/bin/env \
        XDG_RUNTIME_DIR="$runtime" \
        DBUS_SESSION_BUS_ADDRESS="unix:path=$runtime/bus" \
        ${sessionSystemctl} --user stop \
          assbox-graphical-session.target graphical-session.target
  '';
  x11Session = pkgs.writeShellScript "assbox-x11-session" (
    builtins.replaceStrings
      [ "@systemctl@" "@xset@" "@openbox@" ]
      [ "${sessionSystemctl}" "${pkgs.xset}/bin/xset" "${pkgs.openbox}/bin/openbox-session" ]
      (builtins.readFile ./sessions/x11.sh)
  );
  session = pkgs.writeShellScript "assbox-wayland-session" (
    builtins.replaceStrings
      [ "@systemctl@" "@labwc@" ]
      [ "${sessionSystemctl}" "${pkgs.labwc}/bin/labwc" ]
      (builtins.readFile ./sessions/wayland.sh)
  );
  waylandReady = pkgs.writeShellScript "assbox-wayland-ready" (
    builtins.replaceStrings [ "@systemctl@" ] [ "${pkgs.systemd}/bin/systemctl" ] (
      builtins.readFile ./sessions/wayland-ready.sh
    )
  );
  waylandAutostart = pkgs.writeShellScript "assbox-wayland-autostart" ''
    ${waylandReady} || exit $?
    ${pkgs.wlr-randr}/bin/wlr-randr --json | ${pkgs.jq}/bin/jq -r '.[] | select(.enabled) | .name' |
      while IFS= read -r output; do
        ${pkgs.wlr-randr}/bin/wlr-randr --output "$output" --scale ${toString cfg.display.scale}
      done
    ${pkgs.swayidle}/bin/swayidle -w timeout 600 "${pkgs.wlopm}/bin/wlopm --off '*'" resume "${pkgs.wlopm}/bin/wlopm --on '*'" &
    ${pkgs.foot}/bin/foot &
  '';
in
{
  config = lib.mkIf cfg.enable (
    lib.mkMerge [
      (lib.mkIf (cfg.presentation != "headless") {
        # Native apps such as Zed use portals for file dialogs too. Minimal
        # window managers do not supply a desktop's implicit portal selection.
        xdg.portal.enable = true;
        # Use the normal Secret Service and first-use GNOME prompt. Never seed,
        # rewrite or unlock an existing collection with an Assbox-held password.
        services.gnome.gnome-keyring.enable = true;
        # Secret Service is D-Bus activated, so its first-use files inherit the
        # systemd transient unit's default umask. Patch the selector write itself
        # so its non-secret name cannot weaken the private keyring directory.
        nixpkgs.overlays = [
          (_final: previous: {
            gnome-keyring = previous.gnome-keyring.overrideAttrs (old: {
              patches = (old.patches or [ ]) ++ [
                ../nix/patches/gnome-keyring-private-default.patch
              ];
            });
          })
        ];
        xdg.portal.config.${
          if cfg.presentation == "x11" then "openbox" else "labwc"
        }."org.freedesktop.impl.portal.Secret" =
          [
            "gnome-keyring"
          ];
        # graphical-session.target is a passive systemd target; starting it directly
        # may be refused. A session-specific owner pulls it in and keeps it needed.
        systemd.user.targets.assbox-graphical-session = {
          description = "Assbox graphical session lifetime";
          bindsTo = [ "graphical-session.target" ];
          after = [ "graphical-session-pre.target" ];
        };
      })
      (lib.mkIf (cfg.presentation == "x11") {
        xdg.portal = {
          extraPortals = [ pkgs.xdg-desktop-portal-gtk ];
          config.openbox.default = [ "gtk" ];
        };
        services.xserver = {
          enable = true;
          dpi = 96 * cfg.display.scale;
          displayManager.lightdm = {
            enable = true;
            # LightDM otherwise returns to a password greeter after session/Xorg
            # failure. Without a greeter it exits, letting systemd repeat autologin.
            greeter.enable = false;
          };
          # Custom wrapper owns the session target instead of the stock Openbox
          # launcher, which does not have Assbox's application lifecycle contract.
          windowManager.session = [
            {
              name = "assbox-x11";
              start = ''
                ${x11Session} &
                waitPID=$!
              '';
            }
          ];
        };
        services.displayManager = {
          defaultSession = "none+assbox-x11";
          autoLogin = {
            enable = true;
            user = "agent";
          };
        };
        systemd.services.display-manager = {
          # Replace the upstream three-start lockout with bounded retry backoff.
          # An explicit systemctl stop still leaves the display manager stopped.
          startLimitIntervalSec = lib.mkForce 0;
          serviceConfig = {
            Restart = "always";
            RestartSec = lib.mkForce 5;
            RestartSteps = 5;
            RestartMaxDelaySec = 60;
            ExecStopPost = [ stopGraphicalSession ];
          };
        };
        services.xserver.displayManager.sessionCommands = ''
          # Tell the NixOS session wrapper not to create a second fake target owner.
          export XDG_SESSION_TYPE=x11
          export XDG_CURRENT_DESKTOP=openbox:X-NIXOS-SYSTEMD-AWARE
        '';
        environment.systemPackages = [
          pkgs.openbox
          pkgs.xterm
        ];
        environment.etc."xdg/openbox/autostart".text = ''
          ${pkgs.xterm}/bin/xterm &
        '';
      })
      (lib.mkIf (cfg.presentation == "wayland") {
        programs.labwc.enable = true;
        # labwc's NixOS module installs both backends, but its wlroots config
        # does not match our XDG_CURRENT_DESKTOP=labwc session.
        xdg.portal.config.labwc.default = [
          "wlr"
          "gtk"
        ];
        environment.sessionVariables.NIXOS_OZONE_WL = "1";
        programs.xwayland.enable = true;
        services.greetd = {
          enable = true;
          settings = {
            # Repeat the same explicit local autologin after logout/compositor exit.
            # A locked agent password must not strand the box behind a greeter.
            default_session = {
              command = session;
              user = "agent";
            };
          };
        };
        systemd.services.greetd = {
          # Upstream restarts only clean exits. Recover daemon crashes as well,
          # with the same bounded backoff and deliberate-stop behavior as X11.
          startLimitIntervalSec = lib.mkForce 0;
          serviceConfig = {
            Restart = lib.mkForce "always";
            RestartSec = lib.mkForce 5;
            RestartSteps = 5;
            RestartMaxDelaySec = 60;
            ExecStopPost = [ stopGraphicalSession ];
          };
        };
        environment.systemPackages = [
          pkgs.foot
          pkgs.wlr-randr
        ];
        environment.etc."xdg/labwc/autostart" = {
          source = waylandAutostart;
          mode = "0755";
        };
        environment.etc."xdg/labwc/rc.xml".text = ''
          <?xml version="1.0"?>
          <labwc_config>
            <keyboard><default/><keybind key="W-Return"><action name="Execute" command="${pkgs.foot}/bin/foot"/></keybind></keyboard>
            <mouse><default/></mouse>
          </labwc_config>
        '';
      })
    ]
  );
}
