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
  selected = ids;
  graphical = builtins.elem family [
    "chatgpt"
    "claude-desktop"
  ];
  mode = if graphical then "x11" else "headless";
  commands = map (r: r.command) (
    builtins.filter (r: r.command != "" && builtins.elem "headless" r.presentations) members
  );
in
pkgs.testers.runNixOSTest {
  name = "assbox-components-${family}";
  node.pkgsReadOnly = false;
  requiredFeatures.kvm = !pkgs.stdenv.hostPlatform.isAarch64;
  nodes.machine = { lib, ... }: {
    imports = [ module ];
    assbox = {
      enable = true;
      presentation = mode;
      acceptUnfree = true;
      components =
        lib.recursiveUpdate
          (lib.genAttrs selected (_: {
            enable = true;
            allowMutableCode = true;
          }))
          {
            hermes-dashboard.publicUrl = "https://assbox-ci.example.ts.net/";
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
    assert sorted(configured) == sorted(${builtins.toJSON selected})
    for command in ${builtins.toJSON commands}:
        flag = "--help" if command == "agy" else "--version"
        machine.succeed("su - agent -c " + shlex.quote(command + " " + flag), timeout=120)
    for id in ${builtins.toJSON ids}:
        if id in ["claude-code-remote", "cursor-worker", "happier-daemon"]:
            machine.succeed("test -x /etc/assbox/onboarding/" + id)
            machine.fail("pgrep -u agent -f '" + {"claude-code-remote":"remote-control", "cursor-worker":"worker.*start", "happier-daemon":"daemon start-sync"}[id] + "'")
    if ${if graphical then "True" else "False"}:
        machine.fail("su - agent -c 'assbox-native-policy check " + ("chatgpt-desktop" if "chatgpt-desktop" in configured else "claude-desktop") + "'")
    ${lib.optionalString (family == "happier") ''
      machine.succeed("runuser -u agent -- ${pkgs.python3}/bin/python3 ${../../scripts/providers/happier_contract.py} /run/current-system/sw/bin/happier", timeout=60)
    ''}
    machine.fail("su - agent -c 'sudo -n true'")
  '';
}
