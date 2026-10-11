# SPDX-License-Identifier: GPL-3.0-or-later
# Actual appliance adapters and user units, with harmless provider executables.
# This tests Assbox lifecycle contracts, not provider login, network or GUI support.
{ pkgs, assbox }:
let
  lib = pkgs.lib;
  arm = pkgs.stdenv.hostPlatform.isAarch64;
  catalog = builtins.fromJSON (builtins.readFile ../../catalog/components.json);
  fixture = pkgs.runCommand "assbox-lifecycle-provider" { } ''
    mkdir -p "$out/bin" "$out/libexec"
    for name in claude cursor-agent openclaw opencode st chromium happier hermes agy codex assbox-vscode claude-desktop code zeditor emacs assbox-vscode-gui; do
      printf '#!${pkgs.python3}/bin/python3\n' > "$out/bin/$name"
      cat ${../fixtures/remote_provider.py} >> "$out/bin/$name"
      chmod +x "$out/bin/$name"
    done
    cp "$out/bin/zeditor" "$out/libexec/zed-editor"
  '';
  package = fixture // {
    meta.license = lib.licenses.mit;
  };
  applications = lib.genAttrs (lib.unique (map (row: row.family) catalog)) (
    family:
    lib.listToAttrs (
      map (row: lib.nameValuePair row.package package) (
        builtins.filter (row: row.family == family && row.package != "") catalog
      )
    )
  );
  # Substitute packages only in the adapter modules under test. Do not change
  # global pkgs.callPackage or add test hooks to the production module interface.
  fixturePkgs = pkgs // {
    callPackage = _: _: package; # The adapter's standalone VS Code CLI recipe.
    vscode = package;
    zed-editor = package;
    emacs = package;
    emacs-nox = package;
    st = package // {
      overrideAttrs = _: package;
    };
    chromium = package;
  };
  adapter =
    path:
    { config, lib, ... }:
    import path {
      inherit config lib;
      pkgs = fixturePkgs;
      assboxApplications = applications;
      assboxPackage = assbox;
    };
  remoteIds = [
    "claude-code-remote"
    "cursor-worker"
    "openclaw-node"
    "happier-daemon"
    "vscode-tunnel"
  ];
  guiIds = [
    "vscode"
    "zed"
    "emacs"
  ];
  selected =
    remoteIds
    ++ guiIds
    ++ [
      "claude-code"
      "cursor-agent"
      "openclaw"
      "openclaw-gateway"
      "opencode"
      "opencode-server"
      "happier"
      "codex"
      "vscode-cli"
    ];
in
pkgs.testers.runNixOSTest {
  name = "assbox-remote-lifecycle";
  node.pkgsReadOnly = false;
  requiredFeatures.kvm = !arm;
  nodes.machine = { config, lib, ... }: {
    imports = [
      ../../modules/options.nix
      ../../modules/instances.nix
      ../../modules/base.nix
      ../../modules/access.nix
      ({ lib, ... }: {
        # This adapter fixture exercises standalone components. Define its
        # absent managed-worker interface for the real controller calculation.
        options.assbox.worker = {
          enable = lib.mkEnableOption "the fixture's unused managed worker";
          components = lib.mkOption {
            type = lib.types.listOf lib.types.str;
            default = [ ];
          };
        };
        options.assbox.computerUse = lib.mkOption {
          type = lib.types.attrs;
          default = {
            mode = "none";
            runtime = fixture;
            memoryMaxMiB = 4096;
          };
        };
      })
      (adapter ../../modules/controller.nix)
      (adapter ../../modules/components.nix)
      (adapter ../../modules/remotes.nix)
      (adapter ../../modules/editors.nix)
      (adapter ../../modules/applications.nix)
    ];
    _module.args.assboxPackage = assbox;
    assbox = {
      enable = true;
      presentation = "x11";
      acceptUnfree = true;
      updates.enable = false;
      components =
        lib.recursiveUpdate
          (lib.genAttrs selected (_: {
            enable = true;
            allowMutableCode = true;
          }))
          {
            cursor-worker.computerUse.enable = false;
            emacs.variant = "gui";
          };
      session.autostart = guiIds ++ [
        "opencode-attach"
        "openclaw-dashboard"
      ];
    };
    # A real passive graphical target with a test owner; no Xorg or GPU is needed.
    systemd.user.targets.assbox-test-session = {
      bindsTo = [ "graphical-session.target" ];
      after = [ "graphical-session-pre.target" ];
    };
    systemd.user.services =
      lib.genAttrs
        (map (id: "assbox-${id}") (
          builtins.filter (id: config.assbox.components.${id}.enable) (remoteIds ++ guiIds)
          ++ [
            "opencode"
            "openclaw"
          ]
          ++ lib.optional (builtins.elem "opencode-attach" config.assbox.session.autostart) "opencode-ui"
          ++ lib.optional (builtins.elem "openclaw-dashboard" config.assbox.session.autostart) "openclaw-ui"
        ))
        (name: {
          # Only compress time in the fixture. Keep production restart/limit policy.
          serviceConfig.RestartSec = lib.mkForce "100ms";
          serviceConfig.RestartMaxDelaySec = lib.mkForce "500ms";
          serviceConfig.ExecStartPre = "${pkgs.coreutils}/bin/rm -f /home/agent/lifecycle-fixture/${lib.removePrefix "assbox-" name}.pids";
        });
    specialisation.changed.configuration.assbox.components.claude-code-remote.name =
      lib.mkForce "changed";
    specialisation.disabled.configuration.assbox.components.claude-code-remote.enable =
      lib.mkForce false;
    specialisation.disabled.configuration.assbox.session.autostart = lib.mkForce guiIds;
    users.allowNoPasswordLogin = true;
    users.users.root.hashedPasswordFile = lib.mkForce null;
    users.users.admin.hashedPasswordFile = lib.mkForce null;
    users.users.admin.hashedPassword = lib.mkForce "!";
    boot.loader.grub.enable = lib.mkForce false;
    boot.loader.systemd-boot.enable = lib.mkForce false;
    virtualisation.memorySize = 1024;
    virtualisation.qemu.forceAccel = lib.mkForce (!arm);
    system.stateVersion = "26.05";
  };
  testScript = ''
    import json, shlex, time
    start_all()
    machine.wait_for_unit("multi-user.target")
    # Direct VM boot has no installer-created profile; doctor also inspects it.
    machine.succeed("mkdir -p /nix/var/nix/profiles; ln -sfn $(readlink -f /run/current-system) /nix/var/nix/profiles/system")
    uid = machine.succeed("id -u agent").strip()
    machine.wait_for_unit("user@" + uid + ".service")
    prefix = "runuser -u agent -- env HOME=/home/agent XDG_RUNTIME_DIR=/run/user/" + uid + " DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/" + uid + "/bus "
    def user(command):
        return prefix + "bash -c " + shlex.quote(command)
    def ctl(command):
        return user("systemctl --user " + command)
    def unit(id):
        return "assbox-" + id + ".service"
    def active(id):
        machine.wait_until_succeeds(ctl("is-active " + unit(id)), timeout=60)
    def inactive(id):
        machine.wait_until_succeeds(ctl("show -p ActiveState --value " + unit(id)) + " | grep -x inactive", timeout=60)
    def mode(id, value):
        machine.succeed(user("mkdir -p ~/lifecycle-fixture; printf %s " + shlex.quote(value) + " > ~/lifecycle-fixture/" + id + ".mode"))
    def starts(id):
        return int(machine.succeed(user("wc -l < ~/lifecycle-fixture/" + id + ".starts")).strip())
    def pids(id):
        machine.wait_until_succeeds(user("test -s ~/lifecycle-fixture/" + id + ".pids"), timeout=60)
        return json.loads(machine.succeed(user("cat ~/lifecycle-fixture/" + id + ".pids")))
    def gone(values):
        for pid in values:
            machine.wait_until_succeeds("test ! -e /proc/" + str(pid), timeout=60)
    def onboard(id):
        machine.succeed(user("printf 'yes\\n' | ASSBOX_TEST_ONBOARD=1 assbox component setup " + id))
        active(id)

    remote_ids = ${builtins.toJSON remoteIds}
    gui_ids = ${builtins.toJSON guiIds}
    # Units cannot start before permission exists, even when their target is up.
    machine.succeed(ctl("start assbox-test-session.target"))
    applications = [("opencode-server", "opencode"), ("openclaw-gateway", "openclaw")]
    for component, backend in applications:
        inactive(backend)
        inactive(backend + "-ui")
        machine.succeed(ctl("show -p ConditionResult --value " + unit(backend + "-ui")) + " | grep -x no")
        machine.fail(user("ASSBOX_TEST_ONBOARD=1 ASSBOX_TEST_SETUP_FAIL=1 assbox component setup " + component))
        inactive(backend)
        inactive(backend + "-ui")
        # Real CLI routing after first login must start the previously skipped UI.
        machine.succeed(user("ASSBOX_TEST_ONBOARD=1 assbox component setup " + component))
        active(backend)
        active(backend + "-ui")
    for id in remote_ids:
        machine.succeed(ctl("start " + unit(id)))
        inactive(id)
        machine.succeed(ctl("show -p ConditionResult --value " + unit(id)) + " | grep -x no")
        machine.fail(user("printf 'no\\n' | ASSBOX_TEST_ONBOARD=1 assbox component setup " + id))
        inactive(id)
    machine.fail("assbox component setup claude-code-remote")

    for id in remote_ids:
        onboard(id)
        machine.succeed(user("test $(stat -c %a ~/.config/assbox/onboarded/" + id + "-*) = 600"))
        # More than three quick failures must not strand the service.
        mode(id, "exit7")
        machine.succeed(ctl("restart " + unit(id)))
        machine.wait_until_succeeds(ctl("show -p NRestarts --value " + unit(id)) + " | awk '{exit !($1 >= 4)}'", timeout=60)
        report = machine.succeed("assbox doctor")
        assert unit(id) in report and "NRestarts=" in report
        assert "TEST_PROVIDER_SECRET" not in report
        mode(id, "run")
        machine.wait_until_succeeds(user("test -s ~/lifecycle-fixture/" + id + ".pids"), timeout=60)
        active(id)
        # A clean provider exit also needs recovery for a persistent remote server.
        mode(id, "exit0")
        before = starts(id)
        machine.succeed(ctl("restart " + unit(id)))
        machine.wait_until_succeeds(user("test $(wc -l < ~/lifecycle-fixture/" + id + ".starts) -ge " + str(before + 3)), timeout=60)
        mode(id, "run")
        machine.succeed(ctl("restart " + unit(id)))
        active(id)
        children = pids(id)
        machine.succeed(ctl("stop " + unit(id)))
        gone(children)
        count = starts(id)
        time.sleep(1)
        assert starts(id) == count
        inactive(id)
        machine.succeed(ctl("start " + unit(id)))
        active(id)

    # Doctor can inspect as agent; an ordinary admin cannot silently inspect another UID.
    assert "assbox-cursor-worker.service" in machine.succeed(user("assbox doctor"))
    machine.fail("runuser -u admin -- assbox doctor")

    # Private capture uses the real transient service and ordinary CLI routing.
    mode("claude-code-remote", "exit7")
    output = machine.succeed(user("assbox component diagnose claude-code-remote"))
    assert "TEST_PROVIDER_SECRET" not in output
    machine.succeed(user("test $(stat -c %a ~/.local/state/assbox/diagnostics) = 700"))
    machine.succeed(user("test $(stat -c %a ~/.local/state/assbox/diagnostics/*.log) = 600"))
    machine.succeed(user("grep -q TEST_PROVIDER_SECRET ~/.local/state/assbox/diagnostics/*.log"))
    assert "TEST_PROVIDER_SECRET" not in machine.succeed("journalctl _UID=" + uid + " --no-pager")
    mode("claude-code-remote", "run")
    machine.succeed(ctl("restart " + unit("claude-code-remote")))

    # Foreground entry points preserve crash status after wrapper exec/handoff.
    # A surviving helper must not hide a crashed GUI or delay its restart.
    for id in gui_ids:
        mode(id, "run")
        machine.succeed(ctl("restart " + unit(id)))
        active(id)
        children = pids(id)
        assert machine.succeed(ctl("show -p ExitType --value " + unit(id))).strip() == "main"
        main = int(machine.succeed(ctl("show -p MainPID --value " + unit(id))).strip())
        assert main == children[0]
        before = starts(id)
        machine.succeed("kill -KILL " + str(main))
        gone(children)
        machine.wait_until_succeeds(user("test $(wc -l < ~/lifecycle-fixture/" + id + ".starts) -gt " + str(before)), timeout=60)
        active(id)
        assert pids(id)[0] != main
    owned = [pid for id in gui_ids for pid in pids(id)]
    machine.succeed(ctl("stop assbox-test-session.target graphical-session.target"))
    gone(owned)
    for id in gui_ids:
        inactive(id)
    for component, backend in applications:
        inactive(backend + "-ui")
        active(backend)
        # Onboarding without a graphical session must leave the frontend stopped.
        machine.succeed(user("ASSBOX_TEST_ONBOARD=1 assbox component setup " + component))
        active(backend)
        inactive(backend + "-ui")
    for id in remote_ids:
        if id != "cursor-worker": active(id)
    machine.succeed(ctl("start assbox-test-session.target"))
    active("cursor-worker")
    for component, backend in applications:
        active(backend + "-ui")
        children = pids(backend + "-ui")
        count = starts(backend + "-ui")
        machine.succeed("kill -TERM " + str(children[0]))
        inactive(backend + "-ui")
        gone(children)
        machine.succeed(ctl("restart " + unit(backend)))
        active(backend)
        if backend == "openclaw":
            # The fixture handles TERM by exiting zero; unlike systemctl stop,
            # this must recover the persistent Gateway and clean up its helpers.
            children = pids(backend)
            before = starts(backend)
            machine.succeed("kill -TERM " + str(children[0]))
            gone(children)
            machine.wait_until_succeeds(user("test $(wc -l < ~/lifecycle-fixture/" + backend + ".starts) -gt " + str(before)), timeout=60)
            active(backend)
            assert pids(backend)[0] != children[0]
        time.sleep(1)
        assert starts(backend + "-ui") == count
        inactive(backend + "-ui")
        if backend == "openclaw":
            children = pids(backend)
            machine.succeed(ctl("stop " + unit(backend)))
            gone(children)
            stopped_count = starts(backend)
            time.sleep(1)  # Longer than the fixture's maximum restart delay.
            inactive(backend)
            assert starts(backend) == stopped_count
            machine.succeed(ctl("start " + unit(backend)))
            active(backend)
    # Closing an editor normally must not restart it.
    for id in gui_ids:
        active(id)
        children = pids(id)
        count = starts(id)
        machine.succeed("kill -TERM " + str(children[0]))
        inactive(id)
        gone(children)
        time.sleep(1)
        assert starts(id) == count

    # Real NixOS reconfiguration replaces permission fingerprints and removes units.
    original_marker = machine.succeed(user("ls ~/.config/assbox/onboarded/claude-code-remote-*"))
    old_pids = pids("claude-code-remote")
    machine.succeed("/run/current-system/specialisation/changed/bin/switch-to-configuration test", timeout=180)
    gone(old_pids)
    machine.succeed(ctl("start " + unit("claude-code-remote")))
    inactive("claude-code-remote")
    onboard("claude-code-remote")
    assert machine.succeed(user("ls ~/.config/assbox/onboarded/claude-code-remote-*")) != original_marker
    children = pids("claude-code-remote")
    machine.succeed("/run/booted-system/specialisation/disabled/bin/switch-to-configuration test", timeout=180)
    gone(children)
    machine.fail(ctl("start " + unit("claude-code-remote")))
    machine.succeed(user("test -n \"$(ls ~/.config/assbox/onboarded/claude-code-remote-*)\""))
    for component, backend in applications:
        # Removing a launcher must not make setup try to start its missing unit.
        machine.succeed(user("ASSBOX_TEST_ONBOARD=1 assbox component setup " + component))
        active(backend)
        machine.succeed(ctl("show -p LoadState --value " + unit(backend + "-ui")) + " | grep -x not-found")
  '';
}
