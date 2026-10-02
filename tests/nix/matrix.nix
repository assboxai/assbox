# SPDX-License-Identifier: GPL-3.0-or-later
{ fixture, pkgs }:
let
  lib = pkgs.lib;
  applications = [
    "none"
    "opencode"
    "openclaw"
  ];
  controllerWorker = {
    enable = true;
    stateGiB = 8;
    components = [ "codex" ];
    egress = "offline";
    nameservers = [ ];
  };
  presentations = [
    "headless"
    "x11"
    "wayland"
  ];
  generic = lib.listToAttrs (
    lib.concatMap (
      application:
      map (presentation: {
        name = "uefi-${application}-${presentation}";
        value = fixture {
          assbox = {
            inherit presentation;
            components = lib.optionalAttrs (application != "none") {
              ${application}.enable = true;
              ${if application == "opencode" then "opencode-server" else "openclaw-gateway"}.enable = true;
            };
            session.autostart = lib.optionals (presentation != "headless" && application != "none") [
              (if application == "opencode" then "opencode-attach" else "openclaw-dashboard")
            ];
            boot.mode = "uefi";
          };
        };
      }) presentations
    ) applications
  );
  localConfigurations =
    generic
    // {
      uefi-chatgpt-x11 = fixture {
        assbox = {
          components.chatgpt-desktop = {
            enable = true;
            allowMutableCode = true;
          };
          presentation = "x11";
          worker = controllerWorker;
          acceptUnfree = true;
        };
      };
    }
    // lib.optionalAttrs (pkgs.stdenv.hostPlatform.system == "x86_64-linux") {
      bios-gpt-none = fixture { assbox.boot.mode = "bios-gpt"; };
      bios-mbr-none = fixture { assbox.boot.mode = "bios-mbr"; };
      apple-11-1-chatgpt = fixture {
        assbox = {
          platform = "macbookpro11-1";
          boot.mode = "apple-refind";
          components.chatgpt-desktop = {
            enable = true;
            allowMutableCode = true;
          };
          presentation = "x11";
          worker = controllerWorker;
          acceptUnfree = true;
        };
      };
      apple-12-1-none = fixture {
        assbox = {
          platform = "macbookpro12-1";
          boot.mode = "apple-refind";
          presentation = "x11";
        };
      };
    };
  catalog = builtins.fromJSON (builtins.readFile ../../catalog/components.json);
  # Unqualified sensitive controllers have explicit rejection gates, not
  # successful host fixtures. Other standalone deployment profiles remain valid.
  available = builtins.filter (
    r: r.blocked == "" && (!r.requiresWorker || r.controllerAllowed)
  ) catalog;
  expand =
    ids:
    let
      next = lib.unique (
        ids
        ++ lib.concatMap (
          id: (lib.findFirst (r: r.id == id) (throw "Unknown test component") catalog).dependencies
        ) ids
      );
    in
    if builtins.length next == builtins.length ids then next else expand next;
  selectedFixture =
    ids: presentation:
    let
      selected = expand ids;
    in
    fixture {
      assbox = {
        inherit presentation;
        worker = lib.optionalAttrs (builtins.any (
          id: (lib.findFirst (r: r.id == id) (throw "missing component") catalog).requiresWorker
        ) selected) controllerWorker;
        acceptUnfree = true;
        components =
          lib.recursiveUpdate
            (lib.genAttrs selected (_: {
              enable = true;
              allowMutableCode = true;
            }))
            {
              openclaw-node.tls = false;
              hermes-dashboard.publicUrl = "https://assbox-ci.example.ts.net/";
            };
        network =
          lib.optionalAttrs
            (builtins.any (id: builtins.elem id selected) [
              "vscode-remote-host"
              "zed-remote-host"
            ])
            {
              tailscale.enable = true;
              ssh.agent = {
                enable = true;
                keys = [ "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIKTestFixtureOnlyNotARealKeyExample fixture" ];
              };
            };
      };
    };
  componentConfigurations =
    lib.listToAttrs (
      map (row: {
        name = "component-${row.id}";
        value = selectedFixture ([ row.id ]) (builtins.head row.presentations);
      }) available
    )
    // {
      chatgpt-multiagent = fixture {
        assbox = {
          presentation = "x11";
          acceptUnfree = true;
          components.chatgpt-desktop = {
            enable = true;
            allowMutableCode = true;
          };
          worker = controllerWorker // {
            components = [
              "codex"
              "claude-code"
              "grok"
              "antigravity-cli"
              "cursor-agent"
              "opencode"
              "pi"
              "omp"
            ];
          };
        };
      };
      mixed-cli = selectedFixture (map (r: r.id) (
        builtins.filter (r: r.package != "" && builtins.elem "headless" r.presentations) available
      )) "headless";
      editors-x11 = selectedFixture [ "vscode" "zed" "vim" "emacs" ] "x11";
      editor-hosts = selectedFixture [ "vscode-remote-host" "zed-remote-host" ] "headless";
      full-x11 = selectedFixture (map (r: r.id) (
        builtins.filter (
          r:
          !r.requiresWorker
          && !(builtins.elem r.id [
            "chatgpt-desktop"
            "claude-desktop"
            "chatgpt-remote"
          ])
        ) available
      )) "x11";
      full-wayland = selectedFixture (map (r: r.id) (
        builtins.filter (
          r:
          !r.requiresWorker
          && !(builtins.elem r.id [
            "chatgpt-desktop"
            "claude-desktop"
            "chatgpt-remote"
          ])
          && builtins.elem "wayland" r.presentations
        ) available
      )) "wayland";
    };
  configurations = lib.mapAttrs' (
    name: machine: lib.nameValuePair "${pkgs.stdenv.hostPlatform.system}-${name}" machine
  ) (localConfigurations // componentConfigurations);
  # NixOS coerces portal backend lists to semicolon-separated strings. Export
  # this predicate so the lightweight typed harness exercises the same gate.
  portalBackendsMatch =
    presentation: portals:
    portals.${if presentation == "x11" then "openbox" else "labwc"}.default
    == (if presentation == "x11" then "gtk" else "wlr;gtk");
  audit =
    name: machine:
    let
      a = machine.config.assbox.audit;
      good =
        a.enabled
        && a.firewall
        && a.rootLocked
        && a.agentLocked
        && a.sandbox
        && a.requireSignatures
        && !a.acceptFlakeConfig
        && !a.automount
        && !a.passwordlessSudo
        && !(builtins.elem "wheel" a.agentGroups)
        && (a.boot != "apple-refind" || !a.efiWrites)
        && (!(builtins.elem "chatgpt-desktop" a.selectedComponents) || a.presentation == "x11")
        && (
          !(builtins.any (id: builtins.elem id a.selectedComponents) [
            "vscode"
            "zed"
            "vscode-remote-host"
            "zed-remote-host"
            "vscode-tunnel"
          ])
          || machine.config.programs.nix-ld.enable
        )
        && (
          !(builtins.any (id: builtins.elem id a.selectedComponents) [
            "chatgpt-desktop"
            "claude-desktop"
            "vscode"
            "zed"
          ])
          || (
            builtins.elem pkgs.chromium machine.config.environment.systemPackages
            && machine.config.xdg.mime.defaultApplications."x-scheme-handler/http" == "chromium-browser.desktop"
            &&
              machine.config.xdg.mime.defaultApplications."x-scheme-handler/https" == "chromium-browser.desktop"
          )
        )
        && (
          a.presentation == "headless"
          || (
            machine.config.xdg.portal.enable
            && machine.config.services.gnome.gnome-keyring.enable
            && builtins.elem pkgs.xdg-desktop-portal-gtk machine.config.xdg.portal.extraPortals
            && portalBackendsMatch a.presentation machine.config.xdg.portal.config
          )
        )
        && (
          a.presentation != "x11"
          || (
            !machine.config.services.xserver.displayManager.lightdm.greeter.enable
            && machine.config.systemd.services.display-manager.startLimitIntervalSec == 0
            && machine.config.systemd.services.display-manager.serviceConfig.Restart == "always"
            && machine.config.systemd.services.display-manager.serviceConfig.RestartSec == 5
            && machine.config.systemd.services.display-manager.serviceConfig.RestartMaxDelaySec == 60
          )
        )
        && (
          a.presentation != "wayland"
          || (
            machine.config.systemd.services.greetd.startLimitIntervalSec == 0
            && machine.config.systemd.services.greetd.serviceConfig.Restart == "always"
            && machine.config.systemd.services.greetd.serviceConfig.RestartSec == 5
            && machine.config.systemd.services.greetd.serviceConfig.RestartSteps == 5
            && machine.config.systemd.services.greetd.serviceConfig.RestartMaxDelaySec == 60
          )
        );
      assertions = builtins.all (entry: entry.assertion) machine.config.assertions;
    in
    assert good && assertions;
    pkgs.runCommand "assbox-policy-${name}" { } ''
      cp ${pkgs.writeText "assbox-audit.json" (builtins.toJSON a)} "$out"
    '';
  invalid = fixture {
    assbox = {
      components.chatgpt-desktop = {
        enable = true;
        allowMutableCode = true;
      };
      presentation = "wayland";
      acceptUnfree = true;
    };
  };
  rejectInvalid = !(builtins.all (entry: entry.assertion) invalid.config.assertions);
  invalidArmBios = fixture { assbox.boot.mode = "bios-gpt"; };
  invalidArmApple = fixture {
    assbox = {
      platform = "apple-intel";
      boot.mode = "apple-refind";
    };
  };
  rejects = machine: !(builtins.all (entry: entry.assertion) machine.config.assertions);
in
{
  inherit configurations portalBackendsMatch;
  checks =
    lib.mapAttrs' (
      name: machine: lib.nameValuePair "policy-${name}" (audit name machine)
    ) configurations
    // lib.mapAttrs' (
      name: machine:
      lib.nameValuePair "closure-${name}" (import ./component-closure.nix { inherit pkgs machine name; })
    ) configurations
    // lib.mapAttrs' (
      name: machine: lib.nameValuePair "build-${name}" machine.config.system.build.toplevel
    ) configurations
    // lib.optionalAttrs (pkgs.stdenv.hostPlatform.system == "aarch64-linux") {
      rejects-arm-bios =
        assert rejects invalidArmBios;
        pkgs.runCommand "assbox-reject-arm-bios" { } "touch $out";
      rejects-arm-apple =
        assert rejects invalidArmApple;
        pkgs.runCommand "assbox-reject-arm-apple" { } "touch $out";
    }
    // {
      incompatible-application =
        assert rejectInvalid;
        pkgs.runCommand "assbox-reject-incompatible-application" { } "touch $out";
      headed-opencode-no-browser =
        let
          names = machine: map lib.getName machine.config.environment.systemPackages;
          noBrowser = machine: !(builtins.elem "chromium" (names machine));
        in
        assert noBrowser localConfigurations.uefi-opencode-x11;
        assert noBrowser localConfigurations.uefi-opencode-wayland;
        assert builtins.elem "chromium" (names localConfigurations.uefi-openclaw-wayland);
        pkgs.runCommand "assbox-headed-application-packages" { } "touch $out";
      boot-receipt-policy =
        let
          current = localConfigurations.uefi-none-headless.config.system.build.toplevel;
          changed = (fixture { assbox.boot.generations = 16; }).config.system.build.toplevel;
        in
        pkgs.runCommand "assbox-generation-policy-is-not-storage-binding"
          { nativeBuildInputs = [ pkgs.jq ]; }
          ''
            jq -n -e --slurpfile a ${current}/assbox-boot-policy.json \
              --slurpfile b ${changed}/assbox-boot-policy.json '
                $a[0].schema == 2 and $b[0].schema == 2 and
                $a[0].binding == $b[0].binding and
                $a[0].policy.generations == 8 and $b[0].policy.generations == 16
              ' > "$out"
          '';
    };
}
