# SPDX-License-Identifier: GPL-3.0-or-later
# Exercises real CLI recovery and foreign-generation refusal. It does not claim
# full installation, package activation, retention or power-loss acceptance.
{ pkgs, module }:
let
  arm = pkgs.stdenv.hostPlatform.system == "aarch64-linux";
  # Immutable observation fixture for maintenance ordering, not a real upgrade.
  maintenancePolicy = pkgs.writeText "assbox-maintenance-fixture.json" (
    builtins.toJSON {
      selectedComponents = [ ];
      presentation = "headless";
      updates = {
        enable = true;
        calendar = "hourly";
        rebootGraceSeconds = 0;
        minimumBatteryPercent = 20;
        maximumStageRetries = 3;
        keepGenerations = 8;
      };
    }
  );
  foreign = pkgs.runCommand "nixos-system-assbox-foreign" { } ''
    mkdir -p "$out/bin"
    cat > "$out/bin/switch-to-configuration" <<'EOF'
    #!${pkgs.runtimeShell}
    touch /run/foreign-generation-was-activated
    EOF
    chmod +x "$out/bin/switch-to-configuration"
  '';
in
pkgs.testers.runNixOSTest {
  # Assbox configures unfree consent and redistributable firmware per machine.
  node.pkgsReadOnly = false;
  name = "assbox-management-recovery";
  requiredFeatures.kvm = !arm;
  nodes.machine = { lib, ... }: {
    imports = [ module ];
    assbox.enable = true;
    assbox.updates.enable = false;
    assbox.components = { };
    assbox.presentation = "headless";
    boot.loader.systemd-boot.enable = lib.mkForce false;
    boot.loader.grub.enable = lib.mkForce false;
    # The test driver provides console access; production accounts remain locked.
    users.allowNoPasswordLogin = true;
    users.users.root.hashedPasswordFile = lib.mkForce null;
    users.users.admin.hashedPasswordFile = lib.mkForce null;
    users.users.admin.hashedPassword = lib.mkForce "!";
    virtualisation.memorySize = 2048;
    virtualisation.qemu.forceAccel = pkgs.lib.mkForce (!arm);
    virtualisation.additionalPaths = [
      foreign
      maintenancePolicy
    ];
    system.stateVersion = "26.05";
  };
  testScript = ''
    import itertools
    import shlex

    machine.start()
    machine.wait_for_unit("multi-user.target")
    # This uninstalled fixture has no /etc/nixos. The real boot check fails once;
    # starting active targets (as live activation does) must not retry it.
    machine.wait_for_unit("assbox-boot-check.timer")
    machine.wait_until_succeeds("test $(systemctl show assbox-boot-check.service -p ActiveState --value) = failed")
    boot_check_id = machine.succeed("systemctl show assbox-boot-check.service -p InvocationID --value").strip()
    assert boot_check_id
    machine.succeed("systemctl reset-failed assbox-boot-check.service; systemctl start timers.target multi-user.target")
    assert machine.succeed("systemctl show assbox-boot-check.timer -p SubState --value").strip() == "elapsed"
    assert machine.succeed("systemctl show assbox-boot-check.service -p InvocationID --value").strip() == boot_check_id
    config = "/etc/nixos"
    state = "/var/lib/assbox"
    txn = state + "/transaction"
    machine.succeed("mkdir -p " + config + "; chmod 700 " + config)
    machine.succeed("printf 'old configuration\\n' > " + config + "/local.nix")
    # A crash during preparation or retirement cannot leave an active half-journal.
    for prefix in ["transaction-preparing-", "transaction-retired-"]:
        for contents in ["", "phase", "old-system"]:
            orphan = state + "/" + prefix + "a" * 24
            machine.succeed("mkdir -m700 " + orphan)
            if contents:
                machine.succeed("touch " + orphan + "/" + contents)
            machine.succeed("assbox recover")
            machine.fail("test -e " + orphan)
            machine.succeed("grep 'old configuration' " + config + "/local.nix")

    for phase in ["prepared", "built", "committed"]:
        machine.succeed("mkdir -m700 " + txn + "; printf %s " + phase + " > " + txn + "/phase")
        if phase == "committed":
            machine.succeed("touch " + txn + "/changed-files")
        machine.succeed("assbox recover")
        machine.fail("test -e " + txn)

    # Publication can stop on either side of the local single-file rename.
    for live in ["old", "candidate", "administrator"]:
        machine.succeed("mkdir -m700 " + txn + "; mkdir -m700 " + txn + "/original " + txn + "/candidate")
        machine.succeed("printf published > " + txn + "/phase; printf assbox-packages.nix > " + txn + "/changed-file")
        for location, text in [(txn + "/original", "old"), (txn + "/candidate", "candidate"), (config, live)]:
            machine.succeed("printf %s " + shlex.quote(text) + " > " + location + "/assbox-packages.nix")
        if live == "administrator":
            machine.fail("assbox recover")
            machine.succeed("grep administrator " + config + "/assbox-packages.nix")
            machine.succeed("rm -rf " + txn)
        else:
            machine.succeed("assbox recover")
            machine.succeed("test $(cat " + config + "/assbox-packages.nix) = old")
            machine.fail("test -e " + txn)

    # Release publication can stop between any of its three source renames.
    # The independent anti-replay high-water mark is never part of source rollback.
    release_names = ["flake.nix", "flake.lock", "assbox-release.json"]
    floor_file = state + "/release-state"
    floor_bytes = "release-floor-sentinel-not-source-state"
    machine.succeed("printf %s " + shlex.quote(floor_bytes) + " > " + floor_file + "; chmod 600 " + floor_file)
    for live_values in itertools.product(["old", "candidate"], repeat=3):
        machine.succeed("mkdir -m700 " + txn + "; mkdir -m700 " + txn + "/original " + txn + "/candidate")
        machine.succeed("printf published > " + txn + "/phase")
        machine.succeed("printf '%s\\n' " + " ".join(release_names) + " > " + txn + "/changed-files")
        for name, live in zip(release_names, live_values):
            for location, text in [(txn + "/original", "old"), (txn + "/candidate", "candidate"), (config, live)]:
                machine.succeed("printf %s " + shlex.quote(text + "-" + name) + " > " + location + "/" + name)
        machine.succeed("assbox recover")
        for name in release_names:
            assert machine.succeed("cat " + config + "/" + name) == "old-" + name
        assert machine.succeed("cat " + floor_file) == floor_bytes
        machine.fail("test -e " + txn)
    # A later administrator edit refuses the ENTIRE restore, not just its final
    # file. This test deliberately places the changed file last in the intent.
    machine.succeed("mkdir -m700 " + txn + "; mkdir -m700 " + txn + "/original " + txn + "/candidate")
    machine.succeed("printf published > " + txn + "/phase")
    machine.succeed("printf '%s\\n' " + " ".join(release_names) + " > " + txn + "/changed-files")
    for name in release_names:
        for location, text in [(txn + "/original", "old"), (txn + "/candidate", "candidate"), (config, "candidate")]:
            machine.succeed("printf %s " + shlex.quote(text + "-" + name) + " > " + location + "/" + name)
    machine.succeed("printf administrator > " + config + "/assbox-release.json")
    machine.fail("assbox recover")
    for name in release_names[:2]:
        assert machine.succeed("cat " + config + "/" + name) == "candidate-" + name
    assert machine.succeed("cat " + config + "/assbox-release.json") == "administrator"
    assert machine.succeed("cat " + floor_file) == floor_bytes
    machine.succeed("rm -rf " + txn)

    machine.succeed("mkdir -m700 " + txn + "; printf activating > " + txn + "/phase")
    machine.fail("assbox recover")
    machine.succeed("test -d " + txn + "; rm -rf " + txn)
    # A genuinely corrupt active journal still requires inspection, not guessing.
    machine.succeed("mkdir -m700 " + txn)
    machine.fail("assbox recover")
    machine.succeed("rm -rf " + txn)

    # Maintenance must act on an already-staged boot before reading a broken
    # staging budget or authenticating a new release. The pending generation here
    # is already running, so this fixture cannot request a reboot.
    runtime_path = "/etc/assbox/runtime.json"
    saved_runtime = machine.succeed("readlink -f " + runtime_path).strip()
    machine.succeed("ln -sfn ${maintenancePolicy} " + runtime_path)
    machine.succeed("mkdir -p /nix/var/nix/profiles; ln -sfn $(readlink -f /run/current-system) /nix/var/nix/profiles/system")
    pending = state + "/pending-reboot"
    budget = state + "/stage-retry"
    for retry_flag in ["", " --retry"]:
        machine.succeed("printf %s $(readlink -f /run/current-system) > " + pending + "; chmod 600 " + pending)
        machine.succeed("printf not-a-number > " + budget + "; chmod 600 " + budget)
        machine.succeed("assbox internal maintenance" + retry_flag)
        machine.fail("test -e " + pending)
        assert machine.succeed("cat " + budget) == "not-a-number"
        assert machine.succeed("cat " + floor_file) == floor_bytes
        # A recovery journal wins even over a pending boot and exhausted retries.
        machine.succeed("mkdir -m700 " + txn)
        machine.succeed("printf %s $(readlink -f /run/current-system) > " + pending + "; chmod 600 " + pending)
        machine.succeed("printf 3 > " + budget)
        error = machine.fail("assbox internal maintenance" + retry_flag + " 2>&1")
        assert "interrupted operation" in error
        machine.succeed("test -d " + txn + "; test -f " + pending)
        assert machine.succeed("cat " + budget) == "3"
        machine.succeed("rm -rf " + txn + "; rm -f " + pending + " " + budget)
    machine.succeed("ln -sfn " + shlex.quote(saved_runtime) + " " + runtime_path)

    # Every uncertain durable-state observation refuses before changing source,
    # profile or replay state. A dangling link is present, never missing state.
    profile_before = machine.succeed("readlink -f /nix/var/nix/profiles/system")
    source_before = machine.succeed("sha256sum " + config + "/*")
    for marker in ["transaction", "pending-reboot"]:
        path = state + "/" + marker
        machine.succeed("ln -s /missing-assbox-state " + path)
        for command in ["assbox recover", "assbox internal boot-check"]:
            machine.fail(command)
        machine.succeed("test -L " + path + "; rm " + path)
        assert machine.succeed("readlink -f /nix/var/nix/profiles/system") == profile_before
        assert machine.succeed("sha256sum " + config + "/*") == source_before
        assert machine.succeed("cat " + floor_file) == floor_bytes

    # A malformed new generation or an unrelated pending reboot cannot authorize
    # even the first rollback effect, despite a valid old generation and profile.
    current = profile_before.strip()
    unrelated = "/nix/store/22222222222222222222222222222222-nixos-system-unrelated"
    for new_value, pending_value in [("not-a-generation", current), (current, unrelated)]:
        machine.succeed("mkdir -m700 " + txn + "; mkdir -m700 " + txn + "/original " + txn + "/candidate")
        machine.succeed("printf activating > " + txn + "/phase; touch " + txn + "/changed-files")
        for name, value in [("old-system", current), ("new-system", new_value)]:
            machine.succeed("printf %s " + shlex.quote(value) + " > " + txn + "/" + name)
        machine.succeed("printf %s " + shlex.quote(pending_value) + " > " + pending)
        failure = machine.fail("assbox recover --rollback 2>&1")
        assert "generation state changed outside this operation or is invalid" in failure
        assert machine.succeed("cat " + pending) == pending_value
        assert machine.succeed("readlink -f /nix/var/nix/profiles/system") == profile_before
        assert machine.succeed("sha256sum " + config + "/*") == source_before
        assert machine.succeed("cat " + floor_file) == floor_bytes
        machine.succeed("rm -rf " + txn + "; rm " + pending)

    # Rollback must inspect the old generation's immutable receipt before setting
    # the system profile or executing its activation program.
    machine.succeed("mkdir -p /nix/var/nix/profiles")
    machine.succeed("ln -sfn $(readlink -f /run/current-system) /nix/var/nix/profiles/system-9000-link")
    machine.succeed("ln -sfn ${foreign} /nix/var/nix/profiles/system-8999-link")
    machine.succeed("ln -sfn system-9000-link /nix/var/nix/profiles/system")
    before = machine.succeed("readlink -f /nix/var/nix/profiles/system")
    machine.fail("assbox rollback")
    assert machine.succeed("readlink -f /nix/var/nix/profiles/system") == before
    machine.fail("test -e /run/foreign-generation-was-activated")
    machine.fail("test -e " + txn)
  '';
}
