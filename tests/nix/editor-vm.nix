# SPDX-License-Identifier: GPL-3.0-or-later
# Actual packaged foreground entry points; the lifecycle fixture cannot validate
# an upstream wrapper or prove that an editor reached a usable display.
{ pkgs, module }:
let
  arm = pkgs.stdenv.hostPlatform.isAarch64;
  # Use a real, locked language server, but remove Nix's interpreter/RPATH fixes
  # so the gate exercises the same loader contract as a downloaded GNU binary.
  interpreter = if arm then "/lib/ld-linux-aarch64.so.1" else "/lib64/ld-linux-x86-64.so.2";
  genericLanguageServer =
    pkgs.runCommand "assbox-generic-rust-analyzer" { nativeBuildInputs = [ pkgs.patchelf ]; }
      ''
        mkdir -p "$out/bin"
        cp ${pkgs.rust-analyzer-unwrapped}/bin/rust-analyzer "$out/bin/rust-analyzer"
        chmod u+w "$out/bin/rust-analyzer"
        patchelf --set-interpreter ${interpreter} --remove-rpath "$out/bin/rust-analyzer"
        test "$(patchelf --print-interpreter "$out/bin/rust-analyzer")" = ${interpreter}
        test -z "$(patchelf --print-rpath "$out/bin/rust-analyzer")"
      '';
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
    environment.etc."assbox-test/lsp-probe.py".source = ../fixtures/lsp-probe.py;
    environment.systemPackages = [
      pkgs.xdotool
      pkgs.wmctrl
      pkgs.python3
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
    # Copy outside the store like a downloaded helper. Neither command injects
    # loader variables; the production login and user-manager environments own them.
    machine.succeed("install -o agent -g users -m700 ${genericLanguageServer}/bin/rust-analyzer /home/agent/rust-analyzer")
    probe = "timeout 60 ${pkgs.python3}/bin/python3 /etc/assbox-test/lsp-probe.py /home/agent/rust-analyzer"
    machine.succeed("runuser -l agent -c " + shlex.quote(probe), timeout=90)
    machine.succeed(user("systemd-run --user --wait --pipe --collect --unit=assbox-lsp-probe "
        + "--property=NoNewPrivileges=yes " + probe), timeout=90)
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

    # Crash only the session or X server; restarting LightDM manually would hide
    # a stranded greeter. Normal logout must also repeat the locked-user login.
    assert machine.succeed("getent shadow agent | cut -d: -f2").strip() == "!"
    assert machine.succeed("systemctl show display-manager -p StartLimitIntervalUSec --value").strip() == "0"
    assert machine.succeed("systemctl show display-manager -p RestartMaxDelayUSec --value").strip() == "1min"

    def only_pid(command):
        pids = machine.succeed(command).splitlines()
        assert len(pids) == 1 and int(pids[0]) > 0, pids
        return pids[0]

    def manager(property):
        return machine.succeed("systemctl show display-manager -p " + property + " --value").strip()

    for failure in ["openbox-crash", "xserver-crash", "logout"]:
        previous_manager = manager("MainPID")
        previous_restarts = int(manager("NRestarts"))
        previous_wm = only_pid("pgrep -u agent -f '^${pkgs.openbox}/bin/openbox( |$)'")
        previous_apps = [machine.succeed(ctl("show -p MainPID --value " + unit(id))).strip() for id in editors]
        if failure == "openbox-crash":
            machine.succeed("kill -KILL " + previous_wm)
        elif failure == "xserver-crash":
            machine.succeed("kill -KILL " + only_pid("pgrep -x 'X|Xorg'"))
        else:
            machine.succeed(user("openbox --exit"))
        machine.wait_until_succeeds("test $(systemctl show display-manager -p NRestarts --value) -gt " + str(previous_restarts), timeout=180)
        machine.wait_until_succeeds("systemctl is-active display-manager", timeout=180)
        machine.wait_until_succeeds("pgrep -u agent -f '^${pkgs.openbox}/bin/openbox( |$)'", timeout=180)
        assert manager("MainPID") != previous_manager
        assert only_pid("pgrep -u agent -f '^${pkgs.openbox}/bin/openbox( |$)'") != previous_wm
        for id in editors:
            ready(id)
        for pid in [previous_wm, *previous_apps]:
            if pid != "0":
                machine.succeed("test ! -e /proc/" + pid)
        machine.succeed(ctl("is-active graphical-session.target"))
        machine.screenshot(failure + "-recovered")

    # Deliberate administrative stop must not create another login.
    machine.succeed("systemctl stop display-manager")
    assert manager("ActiveState") == "inactive"
    assert manager("MainPID") == "0"
    machine.fail("pgrep -u agent -f '^${pkgs.openbox}/bin/openbox( |$)'")
    machine.fail(ctl("is-active graphical-session.target"))
    for id in editors:
        machine.wait_until_succeeds(ctl("show -p ActiveState --value " + unit(id)) + " | grep -x inactive", timeout=90)
        assert machine.succeed(ctl("show -p MainPID --value " + unit(id))).strip() == "0"
    machine.shutdown()
  '';
}
