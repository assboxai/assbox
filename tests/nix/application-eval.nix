# SPDX-License-Identifier: GPL-3.0-or-later
# Evaluate launcher policy with inert packages, without a NixOS system/build.
{
  libPath,
  presentation,
  autostart ? [ ],
  scale ? 1,
}:
let
  lib = import libPath;
  result = lib.evalModules {
    specialArgs = {
      pkgs = lib.genAttrs [ "foot" "xterm" "chromium" ] (name: "/inert/${name}") // {
        st.overrideAttrs = _: "/inert/st";
      };
      assboxApplications = {
        opencode.opencode = "/inert/opencode";
        openclaw.openclaw = "/inert/openclaw";
        chatgpt.chatgpt.override = _: "/inert/chatgpt";
      };
    };
    modules = [
      ../../modules/options.nix
      ../../modules/applications.nix
      {
        options =
          lib.genAttrs [ "systemd" "environment" ] (
            _:
            lib.mkOption {
              type = lib.types.attrsOf lib.types.anything;
              default = { };
            }
          )
          // {
            assbox.components = lib.mkOption { type = lib.types.attrsOf lib.types.anything; };
          };
        config.assbox = {
          enable = true;
          inherit presentation;
          display.scale = scale;
          session.autostart = autostart;
          components = {
            opencode-server.enable = true;
            openclaw-gateway.enable = false;
            chatgpt-desktop.enable = false;
          };
        };
      }
    ];
  };
in
{
  services = result.config.systemd.user.services;
  packages = result.config.environment.systemPackages;
}
