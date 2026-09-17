# SPDX-License-Identifier: GPL-3.0-or-later
# Real desktop services on both production sessions, without provider accounts.
{ pkgs, module }:
let
  arm = pkgs.stdenv.hostPlatform.isAarch64;
  python = pkgs.python3.withPackages (p: [
    p.dbus-python
    p.pygobject3
  ]);
in
pkgs.testers.runNixOSTest {
  name = "assbox-desktop-services";
  node.pkgsReadOnly = false;
  requiredFeatures.kvm = !arm;
  enableOCR = true;
  nodes = pkgs.lib.genAttrs [ "x11" "wayland" ] (
    presentation: { lib, ... }: {
      imports = [ module ];
      assbox = {
        enable = true;
        inherit presentation;
        updates.enable = false;
        components = { };
      };
      boot.loader.systemd-boot.enable = lib.mkForce false;
      boot.loader.grub.enable = lib.mkForce false;
      systemd.services.assbox-boot-check.enable = lib.mkForce false;
      users.allowNoPasswordLogin = true;
      users.users.root.hashedPasswordFile = lib.mkForce null;
      users.users.admin.hashedPasswordFile = lib.mkForce null;
      environment.etc."assbox-test/portal-probe.py".source = ../fixtures/portal-probe.py;
      environment.systemPackages = [ python ];
      virtualisation.memorySize = 2048;
      virtualisation.qemu.forceAccel = lib.mkForce (!arm);
      virtualisation.resolution = {
        x = 1280;
        y = 800;
      };
      system.stateVersion = "26.05";
    }
  );
  testScript = ''
    import json, shlex

    # Run one machine at a time; exercise native Wayland and X11 dialogs.
    for machine in machines:
        machine.start()
        machine.wait_for_unit("multi-user.target")
        uid = machine.succeed("id -u agent").strip()
        prefix = "runuser -u agent -- env XDG_RUNTIME_DIR=/run/user/" + uid + " DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/" + uid + "/bus "
        def user(command):
            return prefix + "bash -c " + shlex.quote(command)
        def ready():
            machine.wait_for_unit("user@" + uid + ".service")
            machine.wait_until_succeeds(user("systemctl --user is-active graphical-session.target"))
        def dialogs():
            for mode in ["open", "folder", "save", "cancel"]:
                output = "/home/agent/portal-result.json"
                machine.succeed(user("rm -f " + output))
                machine.succeed(user("systemd-run --user --collect --unit=assbox-portal-probe "
                    + "${python}/bin/python3 /etc/assbox-test/portal-probe.py " + mode + " " + output))
                machine.wait_for_text("Assbox " + mode, timeout=60)
                machine.screenshot(machine.name + "-portal-" + mode)
                if mode == "cancel":
                    machine.send_key("esc")
                else:
                    path = {"open": "/home/agent/input.txt", "folder": "/home/agent/project", "save": "/home/agent/saved.txt"}[mode]
                    machine.send_key("ctrl-l")
                    machine.send_chars(path)
                    machine.send_key("ret")
                machine.wait_until_succeeds("test -s " + output, timeout=60)
                result = json.loads(machine.succeed("cat " + output))
                assert result["code"] == (1 if mode == "cancel" else 0), result
                if mode != "cancel":
                    assert result["uris"] == ["file://" + path], result
                machine.wait_until_fails(user("systemctl --user is-active assbox-portal-probe.service"))

        ready()
        machine.succeed(user("mkdir -p /home/agent/project; printf 'disposable fixture' > /home/agent/input.txt"))
        dialogs()
        # Portals must be relaunched with the new session's display environment.
        manager = "display-manager" if machine.name == "x11" else "greetd"
        machine.succeed("systemctl stop " + manager)
        machine.wait_until_fails(user("systemctl --user is-active graphical-session.target"))
        machine.wait_until_fails(user("systemctl --user is-active xdg-desktop-portal-gtk.service"))
        machine.succeed("systemctl start " + manager)
        ready()
        dialogs()
        machine.shutdown()
  '';
}
