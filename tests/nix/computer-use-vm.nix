# SPDX-License-Identifier: GPL-3.0-or-later
# Substrate-only gate. Provider tool loops and account/build qualification are separate.
{ pkgs, module }:
pkgs.testers.runNixOSTest {
  name = "assbox-computer-use";
  node.pkgsReadOnly = false;
  requiredFeatures.kvm = !pkgs.stdenv.hostPlatform.isAarch64;
  nodes.machine = { lib, ... }: {
    imports = [ module ];
    assbox = {
      enable = true;
      presentation = "headless";
      computerUse.mode = "virtual-desktop";
      components = { };
      session.autostart = [ ];
      updates.enable = false;
    };
    environment.etc."assbox-browser-probe.html".text = "<title>assbox-private-browser-fixture</title>";
    boot.loader.systemd-boot.enable = lib.mkForce false;
    boot.loader.grub.enable = lib.mkForce false;
    systemd.services.assbox-boot-check.enable = lib.mkForce false;
    users.users.agent.linger = true;
    users.allowNoPasswordLogin = true;
    users.users.root.hashedPasswordFile = lib.mkForce null;
    users.users.admin.hashedPasswordFile = lib.mkForce null;
    virtualisation.memorySize = 4096;
    virtualisation.qemu.forceAccel = lib.mkForce (!pkgs.stdenv.hostPlatform.isAarch64);
    system.stateVersion = "26.05";
  };
  testScript = ''
    import json, shlex
    start_all()
    machine.wait_for_unit("multi-user.target")
    machine.wait_for_unit("user@1000.service")
    user = "runuser -u agent -- env XDG_RUNTIME_DIR=/run/user/1000 DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus "
    probe = "assbox-computer-use display -- ${pkgs.python3}/bin/python3 ${../fixtures/computer_resource.py} ${pkgs.xdotool}/bin/xdotool ${pkgs.ffmpeg}/bin/ffmpeg ${pkgs.xorg.xmessage}/bin/xmessage"
    machine.succeed(user + "env DISPLAY=:0 WAYLAND_DISPLAY=wayland-physical SSH_AUTH_SOCK=/sensitive " + probe + " >/home/agent/lease.log 2>&1 &")
    machine.wait_until_succeeds("test -s /home/agent/display-result.json")
    result = json.loads(machine.succeed("cat /home/agent/display-result.json"))
    machine.succeed("test -S /tmp/.X11-unix/X90")
    machine.succeed("test $(stat -c %s /home/agent/capture.png) -gt 1000")
    # A second request must refuse rather than attach to the occupied display.
    machine.fail(user + "assbox-computer-use display -- true")
    machine.succeed("kill -TERM -- -" + str(result["pid"]))
    machine.wait_until_succeeds("test ! -S /tmp/.X11-unix/X90")
    machine.wait_until_succeeds("test ! -e " + shlex.quote(result["auth"]))
    machine.wait_until_succeeds("test -z \"$(find /run/user/1000 -maxdepth 1 -name 'assbox-desktop-*' -print -quit)\"")
    dom = machine.succeed(user + "assbox-browser --dump-dom file:///etc/assbox-browser-probe.html", timeout=90)
    assert "assbox-private-browser-fixture" in dom
    machine.fail(user + "assbox-browser --no-sandbox --dump-dom about:blank")
    machine.wait_until_succeeds("test -z \"$(find /run/user/1000 -maxdepth 1 -name 'assbox-desktop-*' -print -quit)\"")
    # Cleanup permits a later lease; this is not a provider CUA qualification.
    machine.succeed(user + "assbox-computer-use display -- true")
  '';
}
