# SPDX-License-Identifier: GPL-3.0-or-later
# Real seat ACLs and kernel radio controls, using only disposable software radios.
{ pkgs, module }:
let
  arm = pkgs.stdenv.hostPlatform.isAarch64;
  cases = {
    x11off = {
      presentation = "x11";
      wifi = false;
    };
    x11on = {
      presentation = "x11";
      wifi = true;
    };
    waylandoff = {
      presentation = "wayland";
      wifi = false;
    };
    waylandon = {
      presentation = "wayland";
      wifi = true;
    };
  };
in
pkgs.testers.runNixOSTest {
  name = "assbox-radio-policy";
  node.pkgsReadOnly = false;
  requiredFeatures.kvm = !arm;
  nodes = pkgs.lib.mapAttrs (_: case: { lib, ... }: {
    imports = [ module ];
    assbox = {
      enable = true;
      inherit (case) presentation;
      devices.wifi.enable = case.wifi;
      updates.enable = false;
      components = { };
    };
    boot.kernelModules = [ "mac80211_hwsim" ];
    boot.extraModprobeConfig = "options mac80211_hwsim radios=1";
    boot.loader.systemd-boot.enable = lib.mkForce false;
    boot.loader.grub.enable = lib.mkForce false;
    systemd.services.assbox-boot-check.enable = lib.mkForce false;
    users.allowNoPasswordLogin = true;
    users.users.root.hashedPasswordFile = lib.mkForce null;
    users.users.admin.hashedPasswordFile = lib.mkForce null;
    environment.systemPackages = [
      pkgs.acl
      pkgs.python3
    ];
    virtualisation.memorySize = 2048;
    virtualisation.qemu.forceAccel = lib.mkForce (!arm);
    system.stateVersion = "26.05";
  }) cases;
  testScript = ''
    import json
    import shlex

    cases = json.loads(${builtins.toJSON (builtins.toJSON cases)})
    for name, case in cases.items():
        machine = next(node for node in machines if node.name == name)
        machine.start()
        machine.wait_for_unit("multi-user.target")
        # Verify the running kernel excludes the alternate evdev radio-hotkey
        # handler, not just that /dev/rfkill is inaccessible to the seat user.
        machine.succeed("zgrep -x '# CONFIG_RFKILL_INPUT is not set' /proc/config.gz")

        def user(command):
            return "runuser -u agent -- bash -c " + shlex.quote(command)

        def active_seat():
            # During a display-manager restart logind can briefly report the old
            # active session immediately before retiring it. Re-read the seat and
            # verify every property in one retry so a stale ID cannot be cached.
            expected = shlex.quote(case["presentation"])
            machine.wait_until_succeeds(
                "session=$(loginctl show-seat seat0 -p ActiveSession --value); "
                + "test -n \"$session\" && "
                + "test \"$(loginctl show-session \"$session\" -p Name --value)\" = agent && "
                + "test \"$(loginctl show-session \"$session\" -p Active --value)\" = yes && "
                + "test \"$(loginctl show-session \"$session\" -p Type --value)\" = " + expected,
                timeout=120)

        def radio():
            discover = "for p in /sys/class/rfkill/rfkill*; do if test $(cat $p/type) = wlan; then echo $p; fi; done"
            machine.wait_until_succeeds("test -n \"$(" + discover + ")\"")
            paths = machine.succeed(discover).splitlines()
            assert len(paths) == 1, paths
            assert machine.succeed("cat " + paths[0] + "/hard").strip() == "0"
            return paths[0]

        def soft(value):
            machine.wait_until_succeeds("test $(cat " + radio() + "/soft) = " + str(value), timeout=120)

        def denied():
            machine.succeed("udevadm settle; test -c /dev/rfkill")
            assert machine.succeed("stat -c %u:%g:%a /dev/rfkill").strip() == "0:0:600"
            properties = dict(line.split("=", 1) for line in machine.succeed("udevadm info -q property -n /dev/rfkill").splitlines() if "=" in line)
            assert "uaccess" not in properties.get("CURRENT_TAGS", "").split(":")
            acl = machine.succeed("getfacl -cpn /dev/rfkill")
            uid = machine.succeed("id -u agent").strip()
            assert "user:" + uid + ":" not in acl, acl
            # Require EACCES, not a missing device/tool or another unrelated error.
            # The /dev/char alias must protect the same inode too.
            probe = """
    import errno, os
    device = os.stat('/dev/rfkill').st_rdev
    alias = '/dev/char/%d:%d' % (os.major(device), os.minor(device))
    assert os.path.samefile('/dev/rfkill', alias)
    for path in ['/dev/rfkill', alias]:
        for flags in [os.O_WRONLY, os.O_RDWR]:
            try:
                fd = os.open(path, flags)
            except PermissionError as error:
                assert error.errno == errno.EACCES
            else:
                os.close(fd)
                raise AssertionError('agent opened ' + path)
    """
            machine.succeed(user("python3 -c " + shlex.quote(probe)))

        def controls():
            index = radio().rsplit("rfkill", 1)[1]
            # Both numeric-index and type-wide root operations still work.
            machine.succeed("rfkill block " + index)
            soft(1)
            machine.fail(user("rfkill unblock wlan"))
            soft(1)
            machine.succeed("rfkill unblock wlan")
            soft(0)
            machine.fail(user("rfkill block " + index))
            soft(0)
            denied()

        active_seat()
        denied()
        if not case["wifi"]:
            soft(1)  # Radio was already present during boot.
        controls()

        # Seed the opposite saved NM preference. Startup must reapply the Nix
        # policy for both disabled->enabled and enabled->disabled selections.
        machine.succeed("nmcli radio wifi " + ("off" if case["wifi"] else "on"))
        machine.succeed("systemctl restart NetworkManager")
        assert machine.succeed("nmcli radio wifi").strip() == ("enabled" if case["wifi"] else "disabled")
        soft(0 if case["wifi"] else 1)
        denied()
        controls()

        display = "display-manager" if case["presentation"] == "x11" else "greetd"
        machine.succeed("systemctl restart " + display)
        active_seat()
        denied()
        controls()

        # controls() leaves the global WLAN state unblocked: a fresh disabled
        # radio must be blocked by the actual add rule, not inherited state.
        machine.succeed("modprobe -r mac80211_hwsim; modprobe mac80211_hwsim; udevadm settle")
        if not case["wifi"]:
            soft(1)
        denied()
        controls()
        machine.shutdown()
  '';
}
