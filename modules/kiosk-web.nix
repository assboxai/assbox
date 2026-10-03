# SPDX-License-Identifier: GPL-3.0-or-later
{
  config,
  lib,
  pkgs,
  ...
}:
let
  cfg = config.assbox;
  sites = {
    chatgpt = "https://chatgpt.com/";
    claude = "https://claude.ai/";
  };
  launch =
    site:
    pkgs.writeShellScriptBin "assbox-web-${site}" ''
      test "$(${pkgs.coreutils}/bin/id -un)" = agent || exit 77
      test ! -e "$HOME/.config/assbox/disabled/chromium" || exit 77
      exec ${pkgs.chromium}/bin/chromium --user-data-dir="$HOME/.local/share/assbox/web-${site}" --app=${sites.${site}} "$@"
    '';
in
{
  config = lib.mkIf (cfg.enable && cfg.kiosk.webApps != [ ]) {
    assertions = [
      {
        assertion = cfg.components.chromium.enable && cfg.presentation != "headless";
        message = "Explicit web kiosk requires Chromium and physical presentation.";
      }
      {
        assertion = builtins.length cfg.kiosk.webApps == builtins.length (lib.unique cfg.kiosk.webApps);
        message = "Duplicate web kiosk site.";
      }
    ];
    environment.systemPackages = map launch cfg.kiosk.webApps;
    environment.etc."chromium/policies/managed/assbox-kiosk.json".text = builtins.toJSON {
      ExtensionInstallBlocklist = [ "*" ];
      DownloadRestrictions = 3;
      DeveloperToolsAvailability = 2;
      BrowserSignin = 0;
      PasswordManagerEnabled = false;
      DefaultPopupsSetting = 2;
      URLBlocklist = [ "file://*" ];
      AutoLaunchProtocolsFromOrigins = [ ];
    };
    systemd.user.services = lib.listToAttrs (
      map (
        site:
        lib.nameValuePair "assbox-web-${site}" {
          description = "Assbox ${site} web kiosk";
          wantedBy = [ "graphical-session.target" ];
          partOf = [ "graphical-session.target" ];
          after = [ "graphical-session.target" ];
          unitConfig = {
            ConditionUser = "agent";
            ConditionPathExists = "!%h/.config/assbox/disabled/chromium";
          };
          serviceConfig = {
            ExecStart = "${launch site}/bin/assbox-web-${site}";
            Restart = "on-failure";
            RestartSec = 10;
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
      ) cfg.kiosk.webApps
    );
  };
}
