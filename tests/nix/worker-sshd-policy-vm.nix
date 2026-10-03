# SPDX-License-Identifier: GPL-3.0-or-later
# Real daemon interpretation of the GUEST config; no provider login or nested KVM.
{ pkgs, module }:
let
  arm = pkgs.stdenv.hostPlatform.isAarch64;
  evaluated = import (pkgs.path + "/nixos/lib/eval-config.nix") {
    system = pkgs.stdenv.hostPlatform.system;
    modules = [
      module
      ./fixture.nix
      {
        assbox.updates.enable = false;
        assbox.worker = {
          stateGiB = 8;
          enable = true;
          components = [ "vim" ];
          egress = "offline";
          nameservers = [ ];
        };
      }
    ];
  };
  policy = evaluated.config.system.build.assboxWorkerImage.guestPolicy;
in
assert builtins.all (a: a.assertion) evaluated.config.assertions;
assert builtins.all (a: a.assertion) policy.assertions;
pkgs.testers.runNixOSTest {
  name = "assbox-worker-effective-sshd-policy";
  requiredFeatures.kvm = !arm;
  nodes.machine = { ... }: {
    virtualisation.qemu.forceAccel = pkgs.lib.mkForce (!arm);
    services.openssh.enable = true;
    users.users.agent = {
      isNormalUser = true;
      hashedPassword = "!";
    };
    users.groups.assbox-health = { };
    users.users.assbox-health = {
      isSystemUser = true;
      group = "assbox-health";
      home = "/var/empty";
    };
    environment.systemPackages = [
      pkgs.openssh
      pkgs.python3
    ];
    environment.etc."assbox-test-guest-sshd".source = policy.sshdConfig;
    system.stateVersion = "26.05";
  };
  testScript = ''
    start_all()
    machine.wait_for_unit("sshd.service")
    machine.succeed('install -d -m700 /run/assbox-seed; ssh-keygen -q -t ed25519 -N "" -f /run/assbox-seed/ssh_host_ed25519_key')
    machine.succeed("python3 ${../worker/native-sshd-policy.py} ${pkgs.openssh}/bin/sshd /etc/assbox-test-guest-sshd")
  '';
}
