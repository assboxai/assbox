# SPDX-License-Identifier: GPL-3.0-or-later
{
  libPath,
  selection ? { },
  network ? { },
  presentation ? "headless",
  autostart ? [ ],
  acceptUnfree ? true,
  unfreePackages ? [ ],
  packageRevision ? "",
}:
let
  lib = import libPath;
  pkg = name: {
    outPath = "/nix/store/test-${name}${
      lib.optionalString (packageRevision != "") "-${packageRevision}"
    }";
    meta.license.free = !(builtins.elem name unfreePackages);
    __toString = self: self.outPath;
    override = _: pkg name;
    overrideAttrs = _: pkg name;
  };
  catalog = builtins.fromJSON (builtins.readFile ../../catalog/components.json);
  families = lib.unique (map (r: r.family) catalog);
  apps = lib.genAttrs families (
    f:
    lib.listToAttrs (
      map (r: lib.nameValuePair r.package (pkg r.package)) (
        builtins.filter (r: r.family == f && r.package != "") catalog
      )
    )
  );
  pkgs =
    lib.genAttrs [
      "chromium"
      "xdg-utils"
      "vim"
      "emacs"
      "emacs-nox"
      "vscode"
      "zed-editor"
      "xdotool"
      "ffmpeg"
      "xwininfo"
      "xrandr"
      "xset"
      "dbus"
      "zlib"
      "openssl"
      "curl"
      "systemd"
      "coreutils"
      "util-linux"
    ] pkg
    // {
      callPackage = _: _: pkg "vscode-cli";
      runCommand =
        name: _: _:
        pkg name;
      writeShellScript = name: text: (pkg name) // { scriptText = text; };
      stdenv.cc.cc = pkg "cc";
    };
  result = lib.evalModules {
    specialArgs = {
      inherit pkgs;
      assboxApplications = apps;
    };
    modules = [
      ../../modules/options.nix
      ../../modules/components.nix
      ../../modules/remotes.nix
      ../../modules/editors.nix
      ../../modules/access.nix
      ({ lib, ... }: {
        options = {
          assertions = lib.mkOption {
            type = lib.types.listOf lib.types.unspecified;
            default = [ ];
          };
          environment.systemPackages = lib.mkOption {
            type = lib.types.listOf lib.types.unspecified;
            default = [ ];
          };
          environment.etc = lib.mkOption {
            type = lib.types.attrsOf lib.types.anything;
            default = { };
          };
          systemd = lib.mkOption {
            type = lib.types.attrsOf lib.types.anything;
            default = { };
          };
          programs = lib.mkOption {
            type = lib.types.attrsOf lib.types.anything;
            default = { };
          };
          xdg = lib.mkOption {
            type = lib.types.attrsOf lib.types.anything;
            default = { };
          };
          services = lib.mkOption {
            type = lib.types.attrsOf lib.types.anything;
            default = { };
          };
          users = lib.mkOption {
            type = lib.types.attrsOf lib.types.anything;
            default = { };
          };
          networking = lib.mkOption {
            type = lib.types.attrsOf lib.types.anything;
            default = { };
          };
        };
        config.assbox = {
          enable = true;
          inherit acceptUnfree;
          components = selection;
          inherit network presentation;
          session.autostart = autostart;
        };
      })
    ];
  };
in
{
  selected = result.config.assbox.selectedComponents;
  runtimeDependencies = result.config.assbox.componentRuntimeDependencies;
  sshEnabled = result.config.services.openssh.enable;
  identities = result.config.assbox.componentPackagePaths;
  failures = map (a: a.message) (builtins.filter (a: !a.assertion) result.config.assertions);
  services = result.config.systemd;
  programs = result.config.programs;
  xdg = result.config.xdg;
  packages = map toString (result.config.environment.systemPackages or [ ]);
  scripts = lib.mapAttrs (_: value: value.source.scriptText) (
    lib.filterAttrs (
      name: _: lib.hasPrefix "assbox/onboarding/" name || lib.hasPrefix "assbox/diagnostics/" name
    ) result.config.environment.etc
  );
}
