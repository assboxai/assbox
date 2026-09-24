# SPDX-License-Identifier: GPL-3.0-or-later
# Native package/lifecycle checks without provider accounts. Authentication is a
# separate owner-run gate; a skipped first-login unit is not a working remote.
{
  pkgs,
  module,
  family,
}:
let
  lib = pkgs.lib;
  catalog = builtins.fromJSON (builtins.readFile ../../catalog/components.json);
  members = builtins.filter (row: row.family == family && row.blocked == "") catalog;
  ids = map (r: r.id) members;
  selected =
    ids
    ++ lib.optionals (family == "happy") [
      "codex"
      "claude-code"
    ];
  graphical = family == "claude-desktop";
  mode = if graphical then "x11" else "headless";
  commands = map (r: r.command) (
    builtins.filter (r: r.command != "" && builtins.elem "headless" r.presentations) members
  );
  rejectedController = import (pkgs.path + "/nixos/lib/eval-config.nix") {
    system = pkgs.stdenv.hostPlatform.system;
    modules = [
      module
      ./fixture.nix
      {
        assbox.presentation = "x11";
        assbox.acceptUnfree = true;
        assbox.components.claude-desktop = {
          enable = true;
          allowMutableCode = true;
        };
        assbox.worker = {
          enable = true;
          components = [ "vim" ];
          egress = "offline";
          nameservers = [ ];
        };
      }
    ];
  };
in
# This family cannot claim a controller adapter until its transport is qualified.
# Its gate proves rejection and a minimal boot, not a successful Claude UI run.
assert
  !graphical
  || builtins.any (
    a: !a.assertion && lib.hasInfix "unqualified controller" a.message
  ) rejectedController.config.assertions;
pkgs.testers.runNixOSTest {
  name = "assbox-components-${family}";
  node.pkgsReadOnly = false;
  requiredFeatures.kvm = !pkgs.stdenv.hostPlatform.isAarch64;
  nodes.machine = { lib, ... }: {
    imports = [ module ];
    assbox = {
      enable = true;
      presentation = if graphical then "headless" else mode;
      acceptUnfree = true;
      components =
        lib.genAttrs (if graphical then [ ] else selected) (_: {
          enable = true;
          allowMutableCode = true;
        })
        // lib.optionalAttrs (family == "happy") {
          happy-remote = {
            enable = true;
            allowMutableCode = true;
            backends = [
              "codex"
              "claude-code"
            ];
          };
        };
      session.autostart = [ ];
      updates.enable = false;
    };
    boot.loader.systemd-boot.enable = lib.mkForce false;
    boot.loader.grub.enable = lib.mkForce false;
    systemd.services.assbox-boot-check.enable = lib.mkForce false;
    users.allowNoPasswordLogin = true;
    users.users.root.hashedPasswordFile = lib.mkForce null;
    users.users.admin.hashedPasswordFile = lib.mkForce null;
    virtualisation.memorySize = if graphical then 4096 else 2048;
    virtualisation.qemu.forceAccel = lib.mkForce (!pkgs.stdenv.hostPlatform.isAarch64);
    system.stateVersion = "26.05";
  };
  testScript = ''
    import json, shlex
    start_all()
    machine.wait_for_unit("multi-user.target")
    configured = json.loads(machine.succeed("cat /etc/assbox/runtime.json"))["selectedComponents"]
    assert sorted(configured) == sorted(${builtins.toJSON (if graphical then [ ] else selected)})
    for command in ${builtins.toJSON commands}:
        flag = "--help" if command == "agy" else "--version"
        machine.succeed("su - agent -c " + shlex.quote(command + " " + flag), timeout=120)
    for id in ${builtins.toJSON ids}:
        if id in ["claude-code-remote", "cursor-worker", "happy-remote"]:
            machine.succeed("test -x /etc/assbox/onboarding/" + id)
            machine.fail("pgrep -u agent -f '" + {"claude-code-remote":"remote-control", "cursor-worker":"worker.*start", "happy-remote":"daemon start-sync"}[id] + "'")
    if ${if graphical then "True" else "False"}:
        machine.fail("su - agent -c 'command -v claude-desktop'")
    machine.fail("su - agent -c 'sudo -n true'")
  '';
}
