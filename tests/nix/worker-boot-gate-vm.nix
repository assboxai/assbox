# SPDX-License-Identifier: GPL-3.0-or-later
{ pkgs, module }:
let
  arm = pkgs.stdenv.hostPlatform.isAarch64;
  buildId = builtins.hashString "sha256" "assbox-boot-health-fixture";
  runtime = pkgs.writeText "worker-runtime-test.json" (
    builtins.toJSON {
      schema = 2;
      inherit buildId;
    }
  );
  checker = pkgs.writeShellScript "worker-health-test" ''
    test "$1" = check
    touch /run/worker-check-was-called
    test -e /run/worker-ready
  '';
  maintenance = pkgs.writeText "worker-maintenance-test.json" (
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
in
pkgs.testers.runNixOSTest {
  name = "assbox-worker-boot-gate";
  node.pkgsReadOnly = false;
  requiredFeatures.kvm = !arm;
  nodes.machine = { lib, ... }: {
    imports = [ module ];
    assbox.enable = true;
    assbox.updates.enable = false;
    assbox.components = { };
    assbox.presentation = "headless";
    assbox.workerBootPolicy = {
      schema = 1;
      enabled = true;
      inherit buildId;
      checker = "${checker}";
      configuration = "${runtime}";
    };
    environment.etc."assbox/worker-runtime.json".source = runtime;
    systemd.timers.assbox-boot-check.wantedBy = lib.mkForce [ ];
    # Start the real retry timer deliberately after failure-state assertions.
    systemd.timers.assbox-worker-boot-retry.wantedBy = lib.mkForce [ ];
    systemd.timers.assbox-worker-boot-retry.timerConfig = {
      OnBootSec = lib.mkForce "1s";
      OnUnitInactiveSec = lib.mkForce "1s";
      AccuracySec = lib.mkForce "100ms";
    };
    boot.loader.systemd-boot.enable = lib.mkForce false;
    boot.loader.grub.enable = lib.mkForce false;
    users.allowNoPasswordLogin = true;
    users.users.root.hashedPasswordFile = lib.mkForce null;
    users.users.admin.hashedPasswordFile = lib.mkForce null;
    users.users.admin.hashedPassword = lib.mkForce "!";
    virtualisation.memorySize = 2048;
    virtualisation.qemu.forceAccel = lib.mkForce (!arm);
    virtualisation.additionalPaths = [ maintenance ];
    system.stateVersion = "26.05";
  };
  testScript = ''
    import shlex
    machine.start()
    machine.wait_for_unit("multi-user.target")
    machine.succeed("mkdir -p /etc/nixos /var/lib/assbox; chmod 700 /etc/nixos /var/lib/assbox")
    # This marker enables the systemd retry guard; the fixture uses runtime
    # policy and does not evaluate source or resolve this inert lock file.
    machine.succeed("printf '{}' > /etc/nixos/flake.lock; chmod 600 /etc/nixos/flake.lock")
    current = machine.succeed("readlink -f /run/current-system").strip()
    machine.succeed("ln -sfn " + shlex.quote(current) + " /nix/var/nix/profiles/system")
    pending = "/var/lib/assbox/pending-reboot"
    # A different boot identity proves completion, not a live activation.
    record = "assbox-pending-reboot-v1\n" + current + "\n00000000-0000-0000-0000-000000000000\n"
    machine.succeed("printf %s " + shlex.quote(record) + " > " + pending + "; chmod 600 " + pending)
    machine.fail("assbox internal boot-check")
    assert machine.succeed("cat " + pending) == record
    machine.succeed("test -e /run/worker-check-was-called; grep worker-health-failed /var/lib/assbox/worker-boot-status")
    # Maintenance's already-booted fast path must not bypass worker acceptance.
    original = machine.succeed("readlink -f /etc/assbox/runtime.json").strip()
    machine.succeed("ln -sfn ${maintenance} /etc/assbox/runtime.json")
    machine.fail("assbox internal maintenance")
    assert machine.succeed("cat " + pending) == record
    machine.succeed("ln -sfn " + shlex.quote(original) + " /etc/assbox/runtime.json")
    machine.fail("assbox internal boot-check --retry")
    assert machine.succeed("cat " + pending) == record
    # A failed run must later be accepted by the engine's real timer route,
    # even though unattended updates are disabled. No manual boot check here.
    machine.succeed("systemctl start assbox-worker-boot-retry.timer")
    machine.wait_until_succeeds("systemctl is-active assbox-worker-boot-retry.timer")
    machine.succeed("test -e " + pending)
    machine.succeed("touch /run/worker-ready")
    machine.wait_until_succeeds("test ! -e " + pending + " && test -e /var/lib/assbox/boot-acceptance", timeout=60)
    machine.wait_until_succeeds("test $(systemctl is-active assbox-worker-boot-retry.timer) = inactive", timeout=30)
    machine.wait_until_succeeds("test $(systemctl is-active assbox-worker-boot-retry.service) = inactive", timeout=30)
    machine.fail("test -e " + pending)
    receipt = machine.succeed("cat /var/lib/assbox/boot-acceptance")
    boot_id = machine.succeed("cat /proc/sys/kernel/random/boot_id").strip()
    assert receipt == "assbox-boot-acceptance-v1\n" + current + "\n" + boot_id + "\n"
    machine.succeed("grep outcome=accepted /var/lib/assbox/worker-boot-status")
    machine.succeed("rm /run/worker-check-was-called; assbox internal boot-check --retry")
    machine.fail("test -e /run/worker-check-was-called")
    # Repeated timer firings reuse only completed acceptance, not mutable
    # diagnostics. Pending intent always re-enters health and cannot be skipped.
    machine.succeed("printf %s " + shlex.quote(record) + " > " + pending + "; chmod 600 " + pending)
    machine.succeed("assbox internal boot-check --retry; test -e /run/worker-check-was-called")
    machine.fail("test -e " + pending)
    # Even without a pending record, cleanup must fail before deleting anything.
    machine.succeed("rm /run/worker-ready /run/worker-check-was-called")
    machine.fail("assbox cleanup")
    machine.succeed("test -e /run/worker-check-was-called")
    # A receipt for another kernel boot cannot suppress a retry check.
    stale = receipt.replace(boot_id, "00000000-0000-0000-0000-000000000000")
    machine.succeed("printf %s " + shlex.quote(stale) + " > /var/lib/assbox/boot-acceptance")
    machine.fail("assbox internal boot-check --retry")
    # A damaged receipt is not success. Explicit full validation can regenerate
    # it after the operator diagnoses the damage and the worker is healthy.
    machine.succeed("printf damaged > /var/lib/assbox/boot-acceptance")
    machine.fail("assbox internal boot-check --retry")
    machine.succeed("touch /run/worker-ready; assbox internal boot-check")
    machine.succeed("mkdir /var/lib/assbox/transaction; chmod 700 /var/lib/assbox/transaction")
    machine.fail("assbox internal boot-check --retry")
    machine.succeed("rmdir /var/lib/assbox/transaction")
    # The mutable /etc pointer cannot replace the booted receipt's configuration.
    machine.succeed("touch /run/worker-ready; rm /etc/assbox/worker-runtime.json; printf '{}' > /etc/assbox/worker-runtime.json")
    machine.fail("assbox internal boot-check")
  '';
}
