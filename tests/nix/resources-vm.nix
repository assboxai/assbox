# SPDX-License-Identifier: GPL-3.0-or-later
{ pkgs, module }:
let
  arm = pkgs.stdenv.hostPlatform.isAarch64;
  worker = pkgs.writeText "assbox-resource-worker.nix" ''
    { label }:
    derivation {
      name = "assbox-resource-worker-" + label;
      system = "${pkgs.stdenv.hostPlatform.system}";
      builder = (builtins.storePath "${pkgs.bash}") + "/bin/bash";
      args = [ "-c" ((builtins.storePath "${pkgs.coreutils}") + "/bin/cat /proc/self/cgroup > $out") ];
    }
  '';
in
pkgs.testers.runNixOSTest {
  name = "assbox-resources";
  node.pkgsReadOnly = false;
  requiredFeatures.kvm = !arm;
  nodes.machine = { lib, ... }: {
    imports = [ module ];
    assbox.enable = true;
    assbox.components = { };
    assbox.presentation = "headless";
    boot.loader.systemd-boot.enable = lib.mkForce false;
    boot.loader.grub.enable = lib.mkForce false;
    systemd.services.assbox-boot-check.enable = lib.mkForce false;
    users.allowNoPasswordLogin = true;
    users.users.root.hashedPasswordFile = lib.mkForce null;
    users.users.admin.hashedPasswordFile = lib.mkForce null;
    virtualisation.memorySize = 2048;
    virtualisation.qemu.forceAccel = pkgs.lib.mkForce (!arm);
    virtualisation.additionalPaths = [
      worker
      pkgs.bash
      pkgs.coreutils
    ];
    system.stateVersion = "26.05";
  };
  testScript = ''
    machine.start()
    machine.wait_for_unit("multi-user.target")
    machine.wait_for_unit("dev-zram0.swap")
    machine.succeed("systemctl start nix-daemon")
    assert machine.succeed("systemctl show nix-daemon -p Slice --value").strip() == "assbox.slice"
    assert machine.succeed("systemctl show assbox-maintenance -p Slice --value").strip() == "assbox.slice"
    assert machine.succeed("systemctl show assbox-reboot-retry -p Slice --value").strip() == "assbox.slice"
    group = "/sys/fs/cgroup/assbox.slice"
    assert machine.succeed("cat " + group + "/cpu.weight").strip() == "20"
    assert machine.succeed("cat " + group + "/io.weight").strip() == "default 20"
    assert machine.succeed("cat " + group + "/cpu.max").split()[0] == "max"
    for limit in ["memory.high", "memory.max"]:
        assert machine.succeed("cat " + group + "/" + limit).strip() == "max"
    # Root's automatic store selection uses the local store. Select the daemon
    # explicitly to inspect one of its actual sandboxed build children.
    output = machine.succeed("nix-build --store daemon --option substituters \"\" --no-out-link --argstr label daemon ${worker}").strip()
    worker_group = machine.succeed("cat " + output)
    assert "/assbox.slice/nix-daemon.service" in worker_group, worker_group
    # Root maintenance can build locally and inherits its service's slice. Use a
    # distinct derivation so the daemon case cannot supply a cached result.
    output = machine.succeed(
        "systemd-run --quiet --wait --pipe --collect --unit=assbox-resource-local --property=Slice=assbox.slice "
        "${pkgs.nix}/bin/nix-build --store local --option substituters \"\" --no-out-link --argstr label local ${worker}"
    ).strip()
    worker_group = machine.succeed("cat " + output)
    assert "/assbox.slice/assbox-resource-local.service" in worker_group, worker_group
    algorithm = machine.succeed("cat /sys/block/zram0/comp_algorithm")
    assert "[zstd]" in algorithm
    memory_kib = int(machine.succeed("awk '/MemTotal/ {print $2}' /proc/meminfo"))
    logical = int(machine.succeed("cat /sys/block/zram0/disksize"))
    assert abs(logical - memory_kib * 1024 // 2) < 2 * 1024 * 1024
    # The advertised size is capacity, not an eager reservation of half the RAM.
    used = int(machine.succeed("cat /sys/block/zram0/mm_stat").split()[2])
    assert used < logical // 4
    machine.succeed("test $(systemctl show nix-daemon -p Nice --value) = 0")
    machine.succeed("test $(systemctl show nix-daemon -p OOMScoreAdjust --value) = 0")
  '';
}
