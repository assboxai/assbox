# SPDX-License-Identifier: GPL-3.0-or-later
{ fixture, pkgs }:
let
  lib = pkgs.lib;
  applications = [
    "none"
    "opencode"
    "openclaw"
  ];
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
            inherit application presentation;
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
          application = "chatgpt";
          presentation = "x11";
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
          application = "chatgpt";
          presentation = "x11";
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
  configurations = lib.mapAttrs' (
    name: machine: lib.nameValuePair "${pkgs.stdenv.hostPlatform.system}-${name}" machine
  ) localConfigurations;
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
        && (a.application != "chatgpt" || a.presentation == "x11");
      assertions = builtins.all (entry: entry.assertion) machine.config.assertions;
    in
    assert good && assertions;
    pkgs.runCommand "assbox-policy-${name}" { } ''
      cp ${pkgs.writeText "assbox-audit.json" (builtins.toJSON a)} "$out"
    '';
  invalid = fixture {
    assbox = {
      application = "chatgpt";
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
  inherit configurations;
  checks =
    lib.mapAttrs' (
      name: machine: lib.nameValuePair "policy-${name}" (audit name machine)
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
