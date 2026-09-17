# SPDX-License-Identifier: GPL-3.0-or-later
# Actual packaged foreground entry points; the lifecycle fixture cannot validate
# an upstream wrapper or prove that an editor reached a usable display.
{ pkgs, module }:
let
  arm = pkgs.stdenv.hostPlatform.isAarch64;
in
pkgs.testers.runNixOSTest {
  name = "assbox-editors";
  node.pkgsReadOnly = false;
  requiredFeatures.kvm = !arm;
  nodes.machine = { lib, ... }: {
    imports = [ module ];
    assbox = {
      enable = true;
      presentation = "x11";
      acceptUnfree = true;
      updates.enable = false;
      components = {
        vscode.enable = true;
        zed.enable = true;
        emacs = {
          enable = true;
          variant = "gui";
        };
      };
      session.autostart = [
        "vscode"
        "zed"
        "emacs"
      ];
    };
    boot.loader.systemd-boot.enable = lib.mkForce false;
    boot.loader.grub.enable = lib.mkForce false;
    systemd.services.assbox-boot-check.enable = lib.mkForce false;
    users.allowNoPasswordLogin = true;
    users.users.root.hashedPasswordFile = lib.mkForce null;
    users.users.admin.hashedPasswordFile = lib.mkForce null;
    hardware.graphics.enable = true;
    environment.systemPackages = [
      pkgs.xdotool
      pkgs.wmctrl
    ];
    virtualisation.memorySize = 6144;
    virtualisation.qemu.forceAccel = lib.mkForce (!arm);
    virtualisation.resolution = {
      x = 1280;
      y = 800;
    };
    system.stateVersion = "26.05";
  };
  testScript = ''
    import shlex, time
    start_all()
    machine.wait_for_unit("multi-user.target")
    uid = machine.succeed("id -u agent").strip()
    prefix = "runuser -u agent -- env HOME=/home/agent DISPLAY=:0 XDG_RUNTIME_DIR=/run/user/" + uid + " "
    def user(command):
        return prefix + "bash -c " + shlex.quote(command)
    def ctl(command):
        return user("systemctl --user " + command)
    def unit(id):
        return "assbox-" + id + ".service"
    def window(id):
        pattern = {"vscode": "[Cc]ode", "zed": "[Zz]ed", "emacs": "[Ee]macs"}[id]
        command = user("xdotool search --onlyvisible --class " + shlex.quote(pattern))
        machine.wait_until_succeeds(command, timeout=180)
        return machine.succeed(command).splitlines()[0]
    def ready(id):
        machine.wait_until_succeeds(ctl("is-active " + unit(id)), timeout=180)
        return window(id)

    machine.wait_for_unit("user@" + uid + ".service")
    editors = ["vscode", "zed", "emacs"]
    for id in editors:
        ready(id)
        assert machine.succeed(ctl("show -p ExitType --value " + unit(id))).strip() == "main"
        before = machine.succeed(ctl("show -p MainPID --value " + unit(id))).strip()
        assert int(before) > 0
        restarts = int(machine.succeed(ctl("show -p NRestarts --value " + unit(id))).strip())
        # Kill only the GUI main process, not its entire cgroup. Helpers must not
        # hide the failure, and recovery must produce a real window again.
        machine.succeed("kill -KILL " + before)
        machine.wait_until_succeeds(ctl("show -p NRestarts --value " + unit(id)) + " | awk '{exit !($1 > " + str(restarts) + ")}'", timeout=180)
        ready(id)
        after = machine.succeed(ctl("show -p MainPID --value " + unit(id))).strip()
        assert int(after) > 0 and after != before
    machine.screenshot("editors-recovered")

    # A real window-manager close must stay closed, including past RestartSec.
    closed = {}
    for id in editors:
        machine.succeed(user("wmctrl -ic " + hex(int(window(id)))))
        machine.wait_until_succeeds(ctl("show -p ActiveState --value " + unit(id)) + " | grep -x inactive", timeout=90)
        closed[id] = machine.succeed(ctl("show -p NRestarts --value " + unit(id)))
    time.sleep(25)
    for id in editors:
        assert machine.succeed(ctl("show -p ActiveState --value " + unit(id))).strip() == "inactive"
        assert machine.succeed(ctl("show -p NRestarts --value " + unit(id))) == closed[id]

    # A new graphical session starts the selected editors again.
    machine.succeed("systemctl restart display-manager")
    for id in editors:
        ready(id)
    machine.succeed("systemctl stop display-manager")
    for id in editors:
        machine.wait_until_succeeds(ctl("show -p ActiveState --value " + unit(id)) + " | grep -x inactive", timeout=90)
        assert machine.succeed(ctl("show -p MainPID --value " + unit(id))).strip() == "0"
    machine.shutdown()
  '';
}
