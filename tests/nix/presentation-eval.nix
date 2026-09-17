# SPDX-License-Identifier: GPL-3.0-or-later
# Real presentation policy with inert packages; full NixOS integration is in VMs.
{ libPath, presentation }:
let
  lib = import libPath;
  pkgs =
    lib.genAttrs [
      "systemd"
      "xset"
      "openbox"
      "labwc"
      "wlr-randr"
      "jq"
      "swayidle"
      "wlopm"
      "foot"
      "xterm"
      "xdg-desktop-portal-gtk"
    ] (name: "/inert/${name}")
    // {
      writeShellScript = name: _: "/inert/${name}";
    };
  result = lib.evalModules {
    specialArgs = { inherit pkgs; };
    modules = [
      ../../modules/options.nix
      ../../modules/presentation.nix
      {
        options = lib.genAttrs [ "services" "systemd" "environment" "programs" "xdg" ] (
          _:
          lib.mkOption {
            type = lib.types.attrsOf lib.types.anything;
            default = { };
          }
        );
        config.assbox = {
          enable = true;
          inherit presentation;
        };
      }
    ];
  };
in
{
  inherit (result.config) xdg services systemd;
}
