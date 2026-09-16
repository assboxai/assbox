# SPDX-License-Identifier: GPL-3.0-or-later
{
  config,
  lib,
  pkgs,
  ...
}:
let
  cfg = config.assbox;
  x11Session = pkgs.writeShellScript "assbox-x11-session" (
    builtins.replaceStrings
      [ "@systemctl@" "@xset@" "@openbox@" ]
      [ "${pkgs.systemd}/bin/systemctl" "${pkgs.xset}/bin/xset" "${pkgs.openbox}/bin/openbox-session" ]
      (builtins.readFile ./sessions/x11.sh)
  );
  session = pkgs.writeShellScript "assbox-wayland-session" (
    builtins.replaceStrings
      [ "@systemctl@" "@labwc@" ]
      [ "${pkgs.systemd}/bin/systemctl" "${pkgs.labwc}/bin/labwc" ]
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
        # graphical-session.target is a passive systemd target; starting it directly
        # may be refused. A session-specific owner pulls it in and keeps it needed.
        systemd.user.targets.assbox-graphical-session = {
          description = "Assbox graphical session lifetime";
          bindsTo = [ "graphical-session.target" ];
          after = [ "graphical-session-pre.target" ];
        };
      })
      (lib.mkIf (cfg.presentation == "x11") {
        services.xserver = {
          enable = true;
          dpi = 96 * cfg.display.scale;
          displayManager.lightdm.enable = true;
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
