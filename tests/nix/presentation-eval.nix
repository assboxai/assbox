# SPDX-License-Identifier: GPL-3.0-or-later
# Real presentation policy with inert packages; full NixOS integration is in VMs.
{
  libPath,
  presentation,
  portalDefault ? null,
}:
let
  lib = import libPath;
  # Reuse the actual upstream option definitions from the supplied Nixpkgs tree.
  # Importing options alone does not evaluate NixOS or construct portal packages.
  portalOptions =
    (import (libPath + "/../nixos/modules/config/xdg/portal.nix") {
      inherit lib;
      config = { };
      pkgs = { };
    }).options.xdg.portal;
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
        options =
          lib.genAttrs [ "services" "systemd" "environment" "programs" ] (
            _:
            lib.mkOption {
              type = lib.types.attrsOf lib.types.anything;
              default = { };
            }
          )
          // {
            xdg.portal = {
              inherit (portalOptions) enable config;
              # Only packages are inert; preserve the backend option's coercion.
              extraPortals = lib.mkOption {
                type = lib.types.listOf lib.types.str;
                default = [ ];
              };
            };
          };
        config = {
          assbox = {
            enable = true;
            inherit presentation;
          };
          # The pinned greetd module supplies this normal-priority value. Keep
          # it here so forgetting the explicit override fails even the inert gate.
          systemd.services = lib.mkIf (presentation == "wayland") {
            greetd.serviceConfig.Restart = "on-success";
          };
          xdg.portal.config = lib.mkIf (portalDefault != null) {
            ${if presentation == "x11" then "openbox" else "labwc"}.default = lib.mkForce portalDefault;
          };
        };
      }
    ];
  };
  matrix = import ./matrix.nix {
    pkgs = { inherit lib; };
    fixture = _: throw "The lightweight portal gate must not construct a NixOS fixture";
  };
in
{
  inherit (result.config) xdg services systemd;
  portalPolicy =
    presentation == "headless"
    || matrix.portalBackendsMatch presentation result.config.xdg.portal.config;
}
