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
  substrate ? false,
  instance ? { },
  poisonTailscale ? false,
}:
let
  lib = import libPath;
  pkg = name: {
    type = "derivation";
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
      "makeWrapper"
      "util-linux"
      "python3"
      "qemu"
      "virtiofsd"
      "tigervnc"
      "openbox"
      "st"
      "foot"
      "nftables"
      "pam"
      "gnutar"
      "tailscale"
    ] pkg
    // {
      ffmpeg = (pkg "ffmpeg") // {
        override =
          flags:
          assert
            flags == {
              withXcb = true;
              withXcbShm = true;
              withXcbxfixes = true;
              withXcbShape = true;
            };
          pkg "ffmpeg-x11";
      };
      tailscale =
        if poisonTailscale then throw "deselected Tailscale package was forced" else pkg "tailscale";
      callPackage = _: _: pkg "vscode-cli";
      runCommand =
        name: _: _:
        pkg name;
      writeShellScriptBin = name: _: pkg name;
      writeShellScript = name: text: (pkg name) // { scriptText = text; };
      writeText = name: text: (pkg name) // { scriptText = text; };
      stdenv.cc.cc = pkg "cc";
      stdenv.hostPlatform = {
        system = "x86_64-linux";
        isx86_64 = true;
      };
      OVMF.fd = pkg "firmware";
      xorg = lib.genAttrs [ "xorgserver" "xauth" ] pkg;
      xfce = lib.genAttrs [ "xfce4-session" "xfwm4" "xfce4-panel" "xfdesktop" ] pkg;
    };
  result = lib.evalModules {
    specialArgs = {
      inherit pkgs;
      assboxApplications = apps;
      assboxPackage = pkg "assbox";
    };
    modules =
      lib.optionals substrate [
        ../../modules/instances.nix
        ../../modules/network-policy.nix
        ../../modules/controller.nix
        ../../modules/kiosk-web.nix
        ../../modules/computer-use.nix
        ../../modules/serve.nix
        ../../modules/service-control.nix
        ../../modules/resources.nix
        ../../modules/state.nix
        ../../modules/applications.nix
      ]
      ++ [
        ../../modules/options.nix
        ../../modules/components.nix
        ../../modules/remotes.nix
        ../../modules/editors.nix
        ../../modules/access.nix
        ({ lib, ... }: {
          options =
            lib.recursiveUpdate
              (lib.optionalAttrs (!substrate) {
                assbox.nativePolicy.runtime = lib.mkOption {
                  type = lib.types.unspecified;
                  default = pkg "native-policy";
                };
                assbox.computerUse = lib.mkOption {
                  type = lib.types.attrs;
                  default = {
                    mode = "none";
                    runtime = pkg "computer-use";
                    memoryMaxMiB = 4096;
                  };
                };
              })
              {
                assbox.worker = lib.mkOption {
                  type = lib.types.attrs;
                  default = {
                    enable = false;
                    components = [ ];
                  };
                };
                environment.variables = lib.mkOption {
                  type = lib.types.attrs;
                  default = { };
                };
                nix = lib.mkOption {
                  type = lib.types.attrsOf lib.types.anything;
                  default = { };
                };
                security = lib.mkOption {
                  type = lib.types.attrsOf lib.types.anything;
                  default = { };
                };
                system = lib.mkOption {
                  type = lib.types.attrsOf lib.types.anything;
                  default = { };
                };
                zramSwap = lib.mkOption {
                  type = lib.types.attrsOf lib.types.anything;
                  default = { };
                };
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
          config.assbox = lib.recursiveUpdate (
            {
              enable = true;
              inherit acceptUnfree;
              components = selection;
              inherit network presentation;
              session.autostart = autostart;
            }
            // lib.optionalAttrs (!substrate) {
              controller = {
                active = false;
                profile = "none";
              };
            }
          ) instance;
          config.users.users.agent.uid = 1000;
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
  scriptModes = lib.mapAttrs (_: value: value.mode or "symlink") (
    lib.filterAttrs (
      name: _: lib.hasPrefix "assbox/onboarding/" name || lib.hasPrefix "assbox/diagnostics/" name
    ) result.config.environment.etc
  );
  substrate = lib.optionalAttrs substrate {
    controller = result.config.assbox.controller;
    native = builtins.fromJSON result.config.environment.etc."assbox/native-policy.json".text;
    services = builtins.fromJSON result.config.environment.etc."assbox/service-control.json".text;
    serve = builtins.fromJSON result.config.environment.etc."assbox/serve.json".source.scriptText;
    state = builtins.fromJSON result.config.environment.etc."assbox/state.json".text;
    nft = result.config.networking.nftables.tables or { };
    computerUse =
      if result.config.environment.etc ? "assbox/computer-use-tools.json" then
        builtins.fromJSON result.config.environment.etc."assbox/computer-use-tools.json".text
      else
        null;
  };
}
