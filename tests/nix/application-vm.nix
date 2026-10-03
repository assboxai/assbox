# SPDX-License-Identifier: GPL-3.0-or-later
# Real locked application packages and session managers. No provider credentials.
{
  pkgs,
  module,
  application,
}:
let
  arm = pkgs.stdenv.hostPlatform.isAarch64;
  modes =
    if application == "chatgpt" then
      [ "x11" ]
    else
      [
        "headless"
        "x11"
        "wayland"
      ];
in
pkgs.testers.runNixOSTest {
  name = "assbox-application-${application}";
  node.pkgsReadOnly = false;
  requiredFeatures.kvm = !arm;
  nodes = pkgs.lib.genAttrs modes (
    presentation: { lib, ... }: {
      imports = [ module ];
      assbox = {
        enable = true;
        inherit presentation;
        components =
          if application == "chatgpt" then
            {
              chatgpt-desktop = {
                enable = true;
                allowMutableCode = true;
              };
            }
          else
            {
              ${application}.enable = true;
              ${if application == "opencode" then "opencode-server" else "openclaw-gateway"}.enable = true;
            };
        session.autostart = lib.optionals (presentation != "headless") [
          (
            if application == "chatgpt" then
              "chatgpt-desktop"
            else if application == "opencode" then
              "opencode-attach"
            else
              "openclaw-dashboard"
          )
        ];
        worker = lib.optionalAttrs (application == "chatgpt") {
          enable = true;
          stateGiB = 8;
          components = [ "codex" ];
          egress = "offline";
          nameservers = [ ];
        };
        acceptUnfree = application == "chatgpt";
        updates.enable = false;
      };
      boot.loader.systemd-boot.enable = lib.mkForce false;
      boot.loader.grub.enable = lib.mkForce false;
      systemd.services.assbox-boot-check.enable = lib.mkForce false;
      # UI smoke only: production worker image is evaluated/built, but the
      # controller VM does not request nested KVM. Actual worker/client routing
      # is a separate mandatory hardware acceptance gate.
      systemd.services.assbox-worker.enable = lib.mkIf (application == "chatgpt") (lib.mkForce false);
      systemd.services.assbox-worker-network.enable = lib.mkIf (application == "chatgpt") (
        lib.mkForce false
      );
      systemd.services.assbox-worker-provision.enable = lib.mkIf (application == "chatgpt") (
        lib.mkForce false
      );
      systemd.services.assbox-worker-health.enable = lib.mkIf (application == "chatgpt") (
        lib.mkForce false
      );
      systemd.timers.assbox-worker-health.enable = lib.mkIf (application == "chatgpt") (
        lib.mkForce false
      );
      users.allowNoPasswordLogin = true;
      users.users.root.hashedPasswordFile = lib.mkForce null;
      users.users.admin.hashedPasswordFile = lib.mkForce null;
      environment.systemPackages = [
        pkgs.python3
        pkgs.xwininfo
        pkgs.xdotool
        pkgs.wmctrl
      ];
      # OpenClaw's ownership gate runs two independent Chromium profiles.
      virtualisation.memorySize = if application == "opencode" then 3072 else 4096;
      virtualisation.qemu.forceAccel = pkgs.lib.mkForce (!arm);
      virtualisation.resolution = {
        x = 1280;
        y = 800;
      };
      system.stateVersion = "26.05";
    }
  );
  testScript =
    if application == "chatgpt" then
      ''
        start_all()
        machine = x11
        machine.wait_for_unit("multi-user.target")
        machine.succeed("test -x /run/current-system/sw/bin/chatgpt")
        machine.fail("runuser -u agent -- assbox-native-policy check chatgpt-desktop")
        machine.fail("runuser -u agent -- assbox-native-policy launch chatgpt-desktop")
        machine.fail("pgrep -u agent -f '/bin/chatgpt'")
        machine.succeed("test -r /etc/assbox/native-policy.json")
        # Exact native login and Code/Work enforcement belong to qualification,
        # and are never inferred from this credential-free staging fixture.
      ''
    else
      ''
        import json
        import shlex
        import time

        application = ${builtins.toJSON application}
        modes = ${builtins.toJSON modes}
        for mode in modes:
            # Resolve by node name rather than assuming test-driver machine ordering.
            machine = next(node for node in machines if node.name == mode)
            machine.start()
            machine.wait_for_unit("multi-user.target")
            uid = machine.succeed("id -u agent").strip()
            prefix = "runuser -u agent -- env HOME=/home/agent XDG_RUNTIME_DIR=/run/user/" + uid + " "

            def user(command):
                return prefix + "bash -c " + shlex.quote(command)

            def active(unit):
                machine.wait_until_succeeds(user("systemctl --user is-active " + unit), timeout=180)

            def private_file(path, content):
                machine.succeed("install -d -o agent -g users -m700 " + shlex.quote(path.rsplit('/', 1)[0]))
                machine.succeed("printf %s " + shlex.quote(content) + " > " + shlex.quote(path))
                machine.succeed("chown agent:users " + shlex.quote(path) + "; chmod 600 " + shlex.quote(path))

            unit = "assbox-" + application + ".service"
            machine.wait_for_unit("user@" + uid + ".service")
            machine.fail("runuser -u agent -- cat /etc/shadow")
            machine.fail("runuser -u agent -- head -c1 /dev/vda")
            machine.fail("runuser -u agent -- sudo -n true")
            machine.fail("assbox component setup opencode-server")
            if application != "chatgpt":
                machine.fail(user("systemctl --user is-active " + unit))
                machine.succeed(user(application + " --version"), timeout=120)
            if application == "opencode":
                # Local server authentication is separate from provider login.
                # Every direct service start must refuse an interrupted or ambiguous
                # credential, even when no setup command has validated it first.
                for invalid in ["", "OPENCODE_SERVER_PASS", "OPENCODE_SERVER_PASSWORD=\n",
                                'OPENCODE_SERVER_PASSWORD=""\n',
                                "OPENCODE_SERVER_PASSWORD=secret\nOPENCODE_SERVER_PASSWORD=\n"]:
                    private_file("/home/agent/.config/assbox/opencode.env", invalid)
                    if invalid == "":
                        # Lingering/default.target must also refuse an empty file
                        # after reboot, without an explicit start or setup command.
                        machine.reboot()
                        machine.wait_for_unit("multi-user.target")
                        machine.wait_for_unit("user@" + uid + ".service")
                    else:
                        machine.succeed(user("systemctl --user reset-failed " + unit))
                        machine.succeed(user("systemctl --user start " + unit))
                    machine.wait_until_succeeds(user("systemctl --user show " + unit + " -p ExecMainStatus --value | grep -x 1"))
                    assert not machine.succeed("ss -H -ltn 'sport = :4096'").strip()
                    machine.succeed(user("systemctl --user stop " + unit))
                machine.succeed(user("systemctl --user reset-failed " + unit))
                private_file("/home/agent/.config/assbox/opencode.env", "OPENCODE_SERVER_PASSWORD=disposable-test-password\n")
                machine.succeed(user("opencode auth --help"))
            elif application == "openclaw":
                machine.succeed(user("openclaw onboard --help"), timeout=120)
                private_file("/home/agent/.openclaw/openclaw.json", json.dumps({
                    "gateway": {"mode": "local", "bind": "loopback", "auth": {"mode": "token", "token": "disposable-test-token"}}
                }))
            else:
                # Controller PATH must not contain the separate guest Codex CLI.
                machine.succeed(user('test -x "$(command -v chatgpt)"'))
                machine.fail(user("command -v codex"))
                machine.succeed(user("assbox component setup chatgpt-desktop"))
            machine.succeed(user("systemctl --user restart " + unit))
            active(unit)

            def local_auth():
                if application == "opencode":
                    command = "curl -sS -o /tmp/auth-response -w '%{http_code}' http://127.0.0.1:4096/session"
                    machine.wait_until_succeeds("test $(" + command + ") = 401", timeout=180)
                    body = machine.succeed("curl --fail -sS -u opencode:disposable-test-password http://127.0.0.1:4096/session")
                    assert isinstance(json.loads(body), list)
                    created = json.loads(machine.succeed("curl --fail -sS -u opencode:disposable-test-password -H 'Content-Type: application/json' -d '{}' http://127.0.0.1:4096/session"))
                    assert isinstance(created["id"], str) and created["id"]
                    machine.succeed("curl --fail -sS -u opencode:disposable-test-password http://127.0.0.1:4096/session/" + shlex.quote(created["id"]))
                elif application == "openclaw":
                    machine.wait_until_succeeds(user("openclaw gateway health --url ws://127.0.0.1:18789 --token disposable-test-token"), timeout=180)
                    machine.fail(user("openclaw gateway health --url ws://127.0.0.1:18789 --token incorrect-test-token"))
                if application != "chatgpt":
                    port = "4096" if application == "opencode" else "18789"
                    listeners = machine.succeed("ss -H -ltn 'sport = :" + port + "'")
                    assert listeners.strip()
                    for line in listeners.splitlines():
                        assert line.split()[3] in ["127.0.0.1:" + port, "[::1]:" + port], line

            def gateway_restart_handoff():
                # The real Gateway detects systemd, drains, and exits zero to ask
                # its supervisor for a fresh process. Signal only the main process;
                # killing the cgroup or using systemctl restart bypasses that path.
                before = machine.succeed(user("systemctl --user show " + unit + " -p MainPID --value")).strip()
                count = machine.succeed(user("systemctl --user show " + unit + " -p NRestarts --value")).strip()
                assert int(before) > 0
                machine.succeed(user("systemctl --user kill --kill-whom=main --signal=USR1 " + unit))
                machine.wait_until_succeeds(user("test $(systemctl --user show " + unit + " -p NRestarts --value) -gt " + count), timeout=180)
                active(unit)
                after = machine.succeed(user("systemctl --user show " + unit + " -p MainPID --value")).strip()
                assert int(after) > 0 and after != before
                machine.succeed("test ! -e /proc/" + before)
                local_auth()

            local_auth()
            if application == "openclaw" and mode == "headless":
                gateway_restart_handoff()
            if mode != "headless":
                active("graphical-session.target")
                if application == "openclaw":
                    ui = "assbox-openclaw-ui.service"
                    ordinary = "assbox-test-browser.service"
                    profile = "/home/agent/.local/share/assbox/openclaw-browser"

                    def browser_property(service, name):
                        return machine.succeed(user("systemctl --user show " + service + " -p " + name + " --value")).strip()

                    def browser_window(service):
                        pid = browser_property(service, "MainPID")
                        assert int(pid) > 0
                        command = user("DISPLAY=:0 xdotool search --onlyvisible --pid " + pid)
                        machine.wait_until_succeeds(command, timeout=180)
                        return machine.succeed(command).splitlines()[0]

                    def ordinary_alive():
                        active(ordinary)
                        assert browser_property(ordinary, "MainPID") == ordinary_pid
                        if mode == "x11":
                            browser_window(ordinary)

                    def start_ordinary_browser():
                        # No profile override: this exercises the user's ordinary
                        # Chromium profile and its real singleton/handoff behavior.
                        machine.wait_until_succeeds(user("systemctl --user show " + ordinary + " -p LoadState --value | grep -x not-found"), timeout=90)
                        machine.succeed(user("systemd-run --user --unit=" + ordinary + " --collect --service-type=exec --property=KillMode=control-group chromium --no-first-run --no-default-browser-check about:blank"))
                        active(ordinary)
                        machine.wait_until_succeeds("test -L /home/agent/.config/chromium/SingletonLock", timeout=180)
                        if mode == "x11":
                            browser_window(ordinary)
                        return browser_property(ordinary, "MainPID")

                    def dashboard_ready():
                        active(ui)
                        machine.wait_until_succeeds("test -L " + profile + "/SingletonLock", timeout=180)
                        ordinary_alive()
                        dashboard_pid = browser_property(ui, "MainPID")
                        assert int(dashboard_pid) > 0 and dashboard_pid != ordinary_pid
                        dashboard_group = browser_property(ui, "ControlGroup")
                        ordinary_group = browser_property(ordinary, "ControlGroup")
                        assert dashboard_group and ordinary_group and dashboard_group != ordinary_group
                        assert machine.succeed("cat /proc/" + dashboard_pid + "/cgroup").strip() == "0::" + dashboard_group
                        assert machine.succeed("cat /proc/" + ordinary_pid + "/cgroup").strip() == "0::" + ordinary_group
                        if mode == "x11":
                            browser_window(ui)
                        return dashboard_pid

                    machine.succeed(user("systemctl --user stop " + ui))
                    ordinary_pid = start_ordinary_browser()
                if application != "chatgpt":
                    machine.succeed(user("systemctl --user restart assbox-" + application + "-ui.service"))
                    active("assbox-" + application + "-ui.service")
                if mode == "x11":
                    machine.wait_until_succeeds(user("DISPLAY=:0 xwininfo -root -tree | grep -Ei '" + ("ChatGPT" if application == "chatgpt" else "opencode|OpenClaw|chromium|xterm") + "'"), timeout=180)
                else:
                    machine.wait_until_succeeds(user("systemctl --user show-environment | grep '^WAYLAND_DISPLAY='"))
                if application == "opencode":
                    ui = "assbox-opencode-ui.service"

                    def ui_property(name):
                        return machine.succeed(user("systemctl --user show " + ui + " -p " + name + " --value")).strip()

                    def frontend_pid():
                        terminal = ui_property("MainPID")
                        assert int(terminal) > 0
                        command = "pgrep -P " + terminal + " -f 'opencode.* attach http://127[.]0[.]0[.]1:4096'"
                        machine.wait_until_succeeds(command, timeout=180)
                        pids = machine.succeed(command).splitlines()
                        assert len(pids) == 1, pids
                        return pids[0]

                    def frontend_window():
                        command = user("DISPLAY=:0 xdotool search --onlyvisible --class '^AssboxOpenCode$'")
                        machine.wait_until_succeeds(command, timeout=180)
                        return machine.succeed(command).splitlines()[0]

                    backend = machine.succeed(user("systemctl --user show " + unit + " -p MainPID --value")).strip()
                    terminal, child = ui_property("MainPID"), frontend_pid()
                    restarts = int(ui_property("NRestarts"))
                    # Kill only OpenCode attach. Killing the terminal or backend
                    # would miss a terminal that discards its child's failure status.
                    machine.succeed("kill -KILL " + child)
                    machine.wait_until_succeeds(user("test $(systemctl --user show " + ui + " -p NRestarts --value) -gt " + str(restarts)), timeout=180)
                    active(ui)
                    assert ui_property("MainPID") != terminal
                    assert frontend_pid() != child
                    for pid in [terminal, child]:
                        machine.succeed("test ! -e /proc/" + pid)
                    assert machine.succeed(user("systemctl --user show " + unit + " -p MainPID --value")).strip() == backend

                    def stays_closed():
                        machine.wait_until_succeeds(user("systemctl --user show " + ui + " -p ActiveState --value | grep -x inactive"), timeout=90)
                        count = ui_property("NRestarts")
                        # Observe longer than the production maximum restart delay.
                        time.sleep(65)
                        assert ui_property("ActiveState") == "inactive"
                        assert ui_property("MainPID") == "0"
                        assert ui_property("NRestarts") == count
                        active(unit)

                    if mode == "x11":
                        # Exercise the packaged terminal itself as well as the real
                        # frontend: zero/nonzero child exits and installed terminfo.
                        machine.succeed(user("DISPLAY=:0 st -e python3 -c 'import curses; curses.setupterm()'"))
                        machine.fail(user("DISPLAY=:0 st -e bash -c 'exit 42'"))
                        machine.succeed(user("DISPLAY=:0 wmctrl -ic " + hex(int(frontend_window()))))
                        stays_closed()
                        machine.succeed(user("systemctl --user start " + ui))
                        active(ui)
                        frontend_window()
                    child = frontend_pid()
                    machine.succeed(user("systemctl --user stop " + ui))
                    stays_closed()
                    machine.succeed("test ! -e /proc/" + child)
                    machine.succeed(user("systemctl --user start " + ui))
                    active(ui)
                    frontend_pid()
                elif application == "openclaw":
                    before = dashboard_ready()
                    assert machine.succeed("stat -c '%U:%a' " + profile).strip() == "agent:700"
                    # A stable profile retains browser state across supervised restarts.
                    machine.succeed(user("printf %s retained > " + profile + "/assbox-test-persistence"))
                    group = browser_property(ui, "ControlGroup")
                    members = machine.succeed("cat /sys/fs/cgroup" + group + "/cgroup.procs").splitlines()
                    restarts = int(browser_property(ui, "NRestarts"))
                    machine.succeed("kill -KILL " + before)
                    machine.wait_until_succeeds(user("test $(systemctl --user show " + ui + " -p NRestarts --value) -gt " + str(restarts)), timeout=180)
                    assert dashboard_ready() != before
                    for pid in members:
                        machine.wait_until_succeeds("test ! -e /proc/" + pid, timeout=90)
                    assert machine.succeed(user("cat " + profile + "/assbox-test-persistence")) == "retained"

                    def dashboard_stays_closed():
                        machine.wait_until_succeeds(user("systemctl --user show " + ui + " -p ActiveState --value | grep -x inactive"), timeout=90)
                        count = browser_property(ui, "NRestarts")
                        gateway_restart_handoff()
                        time.sleep(65)  # Longer than the production maximum restart delay.
                        assert browser_property(ui, "ActiveState") == "inactive"
                        assert browser_property(ui, "MainPID") == "0"
                        assert browser_property(ui, "NRestarts") == count
                        ordinary_alive()
                        active(unit)

                    if mode == "x11":
                        machine.succeed(user("DISPLAY=:0 wmctrl -ic " + hex(int(browser_window(ui)))))
                        dashboard_stays_closed()
                        machine.succeed(user("systemctl --user start " + ui))
                        dashboard_ready()
                    before = browser_property(ui, "MainPID")
                    machine.succeed(user("systemctl --user stop " + ui))
                    dashboard_stays_closed()
                    machine.succeed("test ! -e /proc/" + before)
                    machine.succeed(user("systemctl --user start " + ui))
                    before = dashboard_ready()
                    # Also test the reverse launch order: ordinary Chromium must
                    # not hand its new window into the dashboard's managed process.
                    machine.succeed(user("systemctl --user stop " + ordinary))
                    ordinary_pid = start_ordinary_browser()
                    assert dashboard_ready() == before
                    machine.succeed(user("systemctl --user stop " + ordinary))
                machine.screenshot(application + "-" + mode)
                display = "display-manager" if mode == "x11" else "greetd"
                machine.succeed("systemctl stop " + display)
                machine.wait_until_fails(user("systemctl --user is-active graphical-session.target"))
                if application != "chatgpt":
                    active(unit)  # Backend survives a graphical logout.
                    machine.fail(user("systemctl --user is-active assbox-" + application + "-ui.service"))
                machine.succeed("systemctl start " + display)
                active("graphical-session.target")
                active(unit)
            else:
                machine.fail("systemctl is-active display-manager")
                machine.fail("systemctl is-active greetd")

            # Failure recovery and cgroup cleanup exercise the actual app process.
            before = machine.succeed(user("systemctl --user show " + unit + " -p MainPID --value")).strip()
            count = machine.succeed(user("systemctl --user show " + unit + " -p NRestarts --value")).strip()
            machine.succeed(user("systemctl --user kill --signal=KILL " + unit))
            machine.wait_until_succeeds(user("test $(systemctl --user show " + unit + " -p NRestarts --value) -gt " + count), timeout=120)
            active(unit)
            after = machine.succeed(user("systemctl --user show " + unit + " -p MainPID --value")).strip()
            assert after != before and int(after) > 0
            assert machine.succeed(user("systemctl --user show " + unit + " -p RestartMaxDelayUSec --value")).strip() == "1min"
            machine.succeed(user("systemctl --user stop " + unit), timeout=90)
            if application == "openclaw":
                count = machine.succeed(user("systemctl --user show " + unit + " -p NRestarts --value")).strip()
                time.sleep(65)  # An explicit stop must override Restart=always.
                assert machine.succeed(user("systemctl --user show " + unit + " -p ActiveState --value")).strip() == "inactive"
                assert machine.succeed(user("systemctl --user show " + unit + " -p NRestarts --value")).strip() == count
            assert machine.succeed(user("systemctl --user show " + unit + " -p MainPID --value")).strip() == "0"
            machine.reboot()
            machine.wait_for_unit("multi-user.target")
            active(unit)
            local_auth()
            machine.shutdown()
      '';
}
