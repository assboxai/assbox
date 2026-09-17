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
        # A Zed-only selection must supply its browser, not borrow one from a
        # separate agent application or from the test's systemPackages.
        components.zed.enable = true;
      };
      boot.loader.systemd-boot.enable = lib.mkForce false;
      boot.loader.grub.enable = lib.mkForce false;
      systemd.services.assbox-boot-check.enable = lib.mkForce false;
      users.allowNoPasswordLogin = true;
      users.users.root.hashedPasswordFile = lib.mkForce null;
      users.users.admin.hashedPasswordFile = lib.mkForce null;
      environment.etc."assbox-test/portal-probe.py".source = ../fixtures/portal-probe.py;
      environment.etc."assbox-test/browser-probe.py".source = ../fixtures/browser-probe.py;
      environment.systemPackages = [
        python
        pkgs.libsecret
      ];
      virtualisation.memorySize = 3072;
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
            # The passive target can become active before the compositor's
            # terminal finishes mapping; do not let it steal the dialog focus.
            machine.wait_for_text("agent", timeout=60)
        def credentials():
            # A new client process must read the same persistent default keyring.
            # A bounded call also catches a stray unlock prompt after autologin.
            assert machine.succeed(user("timeout 30 secret-tool lookup assbox-test desktop")).strip() == "assbox-disposable-secret"
            assert machine.succeed("stat -c %a /home/agent").strip() == "700"
            machine.succeed("test -d /home/agent/.local/share/keyrings")
            machine.succeed("test -z \"$(find /home/agent/.local/share/keyrings -type f \\( ! -user agent -o -perm /077 \\) -print)\"")
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
        def browser():
            for scheme in ["http", "https"]:
                assert machine.succeed(user("xdg-mime query default x-scheme-handler/" + scheme)).strip() == "chromium-browser.desktop"
            # Inherit the production user manager's display environment. Use the
            # installed handler and normal sandbox, without injecting Chromium flags.
            machine.succeed(user("systemd-run --user --wait --pipe --collect --unit=assbox-browser-probe "
                + "timeout 90 ${python}/bin/python3 /etc/assbox-test/browser-probe.py"), timeout=120)
            machine.wait_until_fails(user("systemctl --user is-active assbox-browser-probe.service"))
            machine.wait_until_fails("pgrep -u agent -x 'chromium|chrome|chrome_crashpad'", timeout=30)

        ready()
        assert machine.succeed("getent shadow agent | cut -d: -f2").strip() == "!"
        # Follow the real first-use creation prompt, including explicit consent
        # to unencrypted storage. No fixture keyring file or private API is used.
        store = "printf %s assbox-disposable-secret | secret-tool store --label='Assbox desktop test' assbox-test desktop"
        machine.succeed(user("systemd-run --user --no-block --unit=assbox-test-store "
            + "--property=Type=oneshot --property=RemainAfterExit=yes bash -o pipefail -c " + shlex.quote(store)))
        machine.wait_for_text("Choose password for new keyring", timeout=60)
        machine.send_key("ret")
        machine.wait_for_text("Store passwords unencrypted", timeout=60)
        machine.send_key("ret")
        machine.wait_until_succeeds(user("systemctl --user is-active assbox-test-store.service"), timeout=60)
        machine.succeed(user("systemctl --user stop assbox-test-store.service"))
        credentials()
        machine.succeed(user("mkdir -p /home/agent/project; printf 'disposable fixture' > /home/agent/input.txt"))
        dialogs()
        browser()
        # Portals must be relaunched with the new session's display environment.
        manager = "display-manager" if machine.name == "x11" else "greetd"
        machine.succeed("systemctl stop " + manager)
        machine.wait_until_fails(user("systemctl --user is-active graphical-session.target"))
        machine.wait_until_fails(user("systemctl --user is-active xdg-desktop-portal-gtk.service"))
        machine.succeed("systemctl start " + manager)
        ready()
        credentials()
        dialogs()
        browser()
        # Restart the actual D-Bus owner, then reboot: neither step may lose the
        # credential or require the absent agent login password.
        owner = json.loads(machine.succeed(user("busctl --user --json=short call org.freedesktop.DBus /org/freedesktop/DBus org.freedesktop.DBus GetConnectionUnixProcessID s org.freedesktop.secrets")))["data"][0]
        machine.succeed("kill -TERM " + str(owner))
        machine.wait_until_fails("test -e /proc/" + str(owner))
        credentials()
        machine.reboot()
        ready()
        credentials()
        dialogs()
        browser()
        machine.succeed(user("secret-tool clear assbox-test desktop"))
        status, _ = machine.execute(user("timeout 30 secret-tool lookup assbox-test desktop"))
        assert status == 1, status
        machine.shutdown()
  '';
}
