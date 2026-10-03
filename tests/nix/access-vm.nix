# SPDX-License-Identifier: GPL-3.0-or-later
# Real IPv4/IPv6 packet and OpenSSH tests. The tailnet variant renames a test
# interface to tailscale0; provider authentication remains owner acceptance.
{
  pkgs,
  module,
  exposure,
}:
let
  lib = pkgs.lib;
  arm = pkgs.stdenv.hostPlatform.isAarch64;
  keys = pkgs.runCommand "assbox-disposable-access-keys" { nativeBuildInputs = [ pkgs.openssh ]; } ''
    mkdir "$out"
    ssh-keygen -q -t ed25519 -N "" -f "$out/agent"
    ssh-keygen -q -t ed25519 -N "" -f "$out/admin"
  '';
in
pkgs.testers.runNixOSTest {
  name = "assbox-access-${exposure}";
  node.pkgsReadOnly = false;
  requiredFeatures.kvm = !arm;
  nodes = {
    box = { lib, ... }: {
      imports = [ module ];
      virtualisation = {
        vlans = [
          1
          2
        ];
        memorySize = 768;
        qemu.forceAccel = lib.mkForce (!arm);
      };
      assbox = {
        enable = true;
        updates.enable = false;
        network = {
          tailscale.enable = exposure == "tailscale";
          ssh = {
            inherit exposure;
            admin = {
              enable = true;
              keys = [ (builtins.readFile "${keys}/admin.pub") ];
            };
            agent = {
              enable = true;
              keys = [ (builtins.readFile "${keys}/agent.pub") ];
            };
            lanInterfaces = [ "eth1" ];
            lanSourceCidrs = [
              "192.168.10.2/32"
              "fd00:10::2/128"
            ];
          };
        };
      };
      services.tailscale.enable = lib.mkForce false; # no external account in VM
      networking.useDHCP = false;
      networking.networkmanager.enable = lib.mkForce false;
      networking.interfaces.eth1 = {
        ipv4.addresses = lib.mkForce [
          {
            address = "192.168.10.1";
            prefixLength = 24;
          }
        ];
        ipv6.addresses = lib.mkForce [
          {
            address = "fd00:10::1";
            prefixLength = 64;
          }
        ];
      };
      networking.interfaces.eth2 = {
        ipv4.addresses = lib.mkForce [
          {
            address = "192.168.20.1";
            prefixLength = 24;
          }
        ];
        ipv6.addresses = lib.mkForce [
          {
            address = "fd00:20::1";
            prefixLength = 64;
          }
        ];
      };
      # Even another module opening port 22 cannot broaden Assbox's ingress.
      networking.firewall.allowedTCPPorts = [ 22 ];
      boot.loader.systemd-boot.enable = lib.mkForce false;
      boot.loader.grub.enable = lib.mkForce false;
      systemd.services.assbox-boot-check.enable = lib.mkForce false;
      users.allowNoPasswordLogin = true;
      users.users.root.hashedPasswordFile = lib.mkForce null;
      users.users.admin.hashedPasswordFile = lib.mkForce null;
      system.stateVersion = "26.05";
    };
    client = { lib, ... }: {
      virtualisation = {
        vlans = [
          1
          2
        ];
        memorySize = 384;
        qemu.forceAccel = lib.mkForce (!arm);
      };
      networking.useDHCP = false;
      networking.interfaces.eth1 = {
        ipv4.addresses = lib.mkForce [
          {
            address = "192.168.10.2";
            prefixLength = 24;
          }
        ];
        ipv6.addresses = lib.mkForce [
          {
            address = "fd00:10::2";
            prefixLength = 64;
          }
        ];
      };
      networking.interfaces.eth2 = {
        ipv4.addresses = lib.mkForce [
          {
            address = "192.168.20.2";
            prefixLength = 24;
          }
        ];
        ipv6.addresses = lib.mkForce [
          {
            address = "fd00:20::2";
            prefixLength = 64;
          }
        ];
      };
      environment.systemPackages = [
        pkgs.openssh
        pkgs.netcat-openbsd
      ];
      system.stateVersion = "26.05";
    };
  };
  testScript = ''
    import shlex
    start_all()
    box.wait_for_unit("sshd.service")
    box.wait_for_unit("nftables.service")
    box.succeed("systemctl is-active user-1000.slice")
    box.succeed("nft list table inet assbox-execution | grep -F 'socket cgroupv2 level 2 \"user.slice/user-1000.slice\"'")
    client.wait_for_unit("network.target")
    client.succeed("cp ${keys}/agent /tmp/agent; cp ${keys}/admin /tmp/admin; chmod 600 /tmp/agent /tmp/admin")
    def ssh(user, key, host, command="id -un"):
        return "ssh -o BatchMode=yes -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ConnectTimeout=3 -i /tmp/" + key + " " + user + "@" + host + " " + shlex.quote(command)
    for host in ["192.168.20.1", "fd00:20::1"]:
        client.fail(ssh("agent", "agent", host))
    if ${if exposure == "tailscale" then "True" else "False"}:
        client.fail(ssh("agent", "agent", "192.168.10.1"))
        box.succeed("ip link set eth1 down; ip link set eth1 name tailscale0; ip link set tailscale0 up")
    for host in ["192.168.10.1", "fd00:10::1"]:
        client.wait_until_succeeds(ssh("agent", "agent", host))
        client.succeed(ssh("admin", "admin", host))
        client.fail(ssh("admin", "agent", host))
        client.fail(ssh("root", "agent", host))
        client.fail(ssh("agent", "agent", host, "sudo -n true"))
    box.succeed("sshd -T | grep -F 'allowagentforwarding no'")
    box.succeed("sshd -T | grep -F 'gatewayports no'")
    box.succeed("sshd -T | grep -Fx 'allowtcpforwarding local'")
    box.succeed("sshd -T | grep -Fx 'permitopen localhost:* 127.0.0.1:* [::1]:*'")
    if ${if exposure == "tailscale" then "True" else "False"}:
        box.succeed("ip link set tailscale0 down; ip link set tailscale0 name untrusted0; ip link set untrusted0 up")
        for host in ["192.168.10.1", "fd00:10::1"]:
            client.fail(ssh("agent", "agent", host))
  '';
}
