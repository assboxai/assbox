# SPDX-License-Identifier: GPL-3.0-or-later
# Actual NixOS account/service activation and pre-activation admission, including
# a disabled-state reboot. The disk is a sparse synthetic fixture, not a booted
# worker filesystem. Real worker /home persistence is a separate KVM gate.
{ pkgs, module }:
let
  arm = pkgs.stdenv.hostPlatform.isAarch64;
in
pkgs.testers.runNixOSTest {
  name = "assbox-worker-disable-reenable";
  node.pkgsReadOnly = false;
  requiredFeatures.kvm = !arm;
  nodes.machine = { lib, ... }: {
    virtualisation.qemu.forceAccel = lib.mkForce (!arm);
    imports = [ module ];
    assbox = {
      enable = true;
      presentation = "headless";
      components = { };
      updates.enable = false;
      worker.enable = false;
    };
    specialisation.worker-enabled.configuration = {
      assbox.worker = {
        enable = lib.mkForce true;
        components = [ "vim" ];
        stateGiB = 8;
        egress = "offline";
        nameservers = [ ];
      };
      # Account/ownership admission must not depend on KVM or a running guest.
      # Leave real provisioning available for explicit invocation, but do not
      # start execution, networking or probes in this activation fixture.
      systemd.services.assbox-worker.wantedBy = lib.mkForce [ ];
      systemd.services.assbox-worker-health.enable = lib.mkForce false;
      systemd.timers.assbox-worker-health.enable = lib.mkForce false;
    };
    systemd.services.assbox-boot-check.enable = lib.mkForce false;
    boot.loader.systemd-boot.enable = lib.mkForce false;
    boot.loader.grub.enable = lib.mkForce false;
    users.allowNoPasswordLogin = true;
    users.users.root.hashedPasswordFile = lib.mkForce null;
    users.users.admin.hashedPasswordFile = lib.mkForce null;
    users.users.admin.hashedPassword = lib.mkForce "!";
    # This gate switches between controller roles to exercise system account,
    # service, network and retained-state activation. Keep the unrelated agent
    # user manager inactive: switch-to-configuration-ng snapshots linger users
    # before the old network policy terminates them, then attempts per-user
    # activation after /run/user/1000 has been removed.
    users.users.agent.linger = lib.mkForce false;
    environment.systemPackages = [
      pkgs.python3
      pkgs.jq
      pkgs.nftables
    ];
    virtualisation.diskSize = 262144; # Sparse backing; includes controller recovery headroom.
    virtualisation.memorySize = 2048;
    system.stateVersion = "26.05";
  };
  testScript = ''
    import json, shlex
    machine.start(allow_reboot=True)
    machine.wait_for_unit("multi-user.target")
    disabled = machine.succeed("readlink -f /run/current-system").strip()
    enabled = disabled + "/specialisation/worker-enabled"
    names = ("assbox-vmm", "assbox-health-probe")

    def identities():
        result = {}
        for name in names:
            fields = machine.succeed("getent passwd " + name).strip().split(":")
            assert int(fields[2]) > 0 and int(fields[3]) > 0
            assert fields[5] == "/var/empty" and fields[6].endswith("/bin/nologin")
            assert machine.succeed("getent shadow " + name).split(":")[1] == "!"
            result[name] = (fields[2], fields[3])
        return result

    expected_ids = identities()

    def assert_disabled():
        assert identities() == expected_ids
        machine.succeed("systemctl is-active user-1000.slice")
        for name in names:
            assert "kvm" not in machine.succeed("id -nG " + name).split()
            machine.fail("pgrep -u " + name)
        machine.fail("systemctl is-active assbox-worker.service")
        machine.fail("systemctl cat assbox-worker.service")
        machine.fail("ip link show ab-worker0")
        machine.fail("nft list table inet assbox-worker")
        machine.succeed("test ! -e /etc/assbox/worker-runtime.json")
        policy = json.loads(machine.succeed("cat /run/current-system/assbox-worker-policy.json"))
        assert policy["enabled"] is False

    def switch(system):
        machine.succeed(shlex.quote(system + "/bin/switch-to-configuration") + " test", timeout=240)

    assert_disabled()
    machine.succeed("test ! -e /var/lib/assbox-worker-data; test ! -e /var/lib/assbox-worker-identity")
    switch(enabled)
    assert identities() == expected_ids
    machine.succeed("systemctl is-active user-1000.slice")
    assert "kvm" in machine.succeed("id -nG assbox-vmm").split()
    machine.fail("systemctl is-active assbox-worker.service")
    policy = json.loads(machine.succeed("cat /run/current-system/assbox-worker-policy.json"))
    assert policy["enabled"] is True
    admit = shlex.quote(policy["checker"]) + " --configuration " + shlex.quote(policy["configuration"]) + " admit"
    machine.succeed("systemctl start assbox-worker-provision.service", timeout=120)
    # Never attach this synthetic disk to a worker or parse it with an image tool.
    machine.succeed("runuser -u assbox-vmm -- sh -c 'umask 077; printf preserved-state > /var/lib/assbox-worker-data/home.raw; truncate -s 8G /var/lib/assbox-worker-data/home.raw'")
    paths = [
        "/var/lib/assbox-worker-data", "/var/lib/assbox-worker-data/home.raw",
        "/var/lib/assbox-worker-control/client_ed25519",
        "/var/lib/assbox-worker-control/known_hosts",
        "/var/lib/assbox-worker-identity/ssh_host_ed25519_key",
        "/var/lib/assbox-worker-identity/health_ed25519",
        "/var/lib/assbox-worker-health/health_ed25519",
        "/var/lib/assbox-worker-health/known_hosts",
    ]

    def snapshot():
        # Inode/owner/size/mode plus bounded content, not an 8-GiB hash walk.
        command = "stat -c '%n:%u:%g:%a:%i:%s' " + " ".join(shlex.quote(p) for p in paths)
        command += "; head -c 128 /var/lib/assbox-worker-data/home.raw | sha256sum"
        command += "; sha256sum " + " ".join(shlex.quote(p) for p in paths[2:])
        return machine.succeed(command)

    preserved = snapshot()
    switch(disabled)
    assert_disabled()
    assert snapshot() == preserved
    # Reboot with the disabled base system and the same persistent test disk.
    machine.reboot()
    machine.wait_for_unit("multi-user.target")
    assert_disabled()
    assert snapshot() == preserved
    # Crucially this invokes the ENABLED candidate while DISABLED is active.
    # No activation, chown or inferred UID is needed to pass admission.
    assert json.loads(machine.succeed(admit))["admission"] == "accepted"
    assert snapshot() == preserved
    # Existing disks require exactly 0600, not just owner-only permissions.
    for mode in ("0400", "0200", "0000", "0700", "4600", "1600"):
        machine.succeed("chmod " + mode + " /var/lib/assbox-worker-data/home.raw")
        machine.fail(admit)
        observed = machine.succeed("stat -c %a /var/lib/assbox-worker-data/home.raw").strip()
        assert int(observed, 8) == int(mode, 8)
    machine.succeed("chmod 0600 /var/lib/assbox-worker-data/home.raw")
    # No canonical key may be regenerated while the retained disk exists.
    for key in (paths[2], paths[4], paths[5]):
        saved = key + ".saved"
        machine.succeed("mv " + shlex.quote(key) + " " + shlex.quote(saved))
        machine.fail(admit)
        machine.succeed("test ! -e " + shlex.quote(key))
        machine.succeed("mv " + shlex.quote(saved) + " " + shlex.quote(key))
        assert snapshot() == preserved
    machine.succeed("mv /var/lib/assbox-worker-data/home.raw /var/lib/assbox-worker-data/home.saved")
    machine.succeed("runuser -u assbox-vmm -- sh -c 'umask 077; printf stale-root > /var/lib/assbox-worker-data/root.qcow2'")
    machine.fail(admit)
    machine.succeed("test ! -e /var/lib/assbox-worker-data/home.raw")
    machine.succeed("rm /var/lib/assbox-worker-data/root.qcow2; mv /var/lib/assbox-worker-data/home.saved /var/lib/assbox-worker-data/home.raw")
    assert snapshot() == preserved
    machine.succeed("chmod 0755 /var/lib/assbox-worker-data")
    machine.fail(admit)
    switch(enabled)
    assert identities() == expected_ids
    machine.fail("systemctl start assbox-worker-provision.service")
    assert machine.succeed("stat -c %a /var/lib/assbox-worker-data").strip() == "755"
    # Deliberate fixture repair, never an automatic product ownership repair.
    machine.succeed("chmod 0700 /var/lib/assbox-worker-data; systemctl reset-failed assbox-worker-provision.service")
    # Save only content/ownership here: atomic reprovision may replace public
    # files and the probe's copied key but must retain key bytes and disk inode.
    old_disk = machine.succeed("stat -c '%i:%u:%g:%s' /var/lib/assbox-worker-data/home.raw")
    old_keys = machine.succeed("sha256sum " + " ".join(shlex.quote(p) for p in paths[2:]))
    machine.succeed("systemctl start assbox-worker-provision.service", timeout=120)
    assert machine.succeed("sha256sum " + " ".join(shlex.quote(p) for p in paths[2:])) == old_keys
    assert machine.succeed("stat -c '%i:%u:%g:%s' /var/lib/assbox-worker-data/home.raw") == old_disk
    assert json.loads(machine.succeed(admit))["admission"] == "accepted"
    machine.succeed("test $(head -c 15 /var/lib/assbox-worker-data/home.raw) = preserved-state")
  '';
}
