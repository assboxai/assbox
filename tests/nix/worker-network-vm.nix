# SPDX-License-Identifier: GPL-3.0-or-later
# Exercises production host firewall tables with a hostile root-capable peer.
# This is NOT the production QEMU lifecycle test; see worker/kvm-acceptance.py.
{ pkgs, module }:
let
  arm = pkgs.stdenv.hostPlatform.isAarch64;
in
pkgs.testers.runNixOSTest {
  name = "assbox-worker-network";
  node.pkgsReadOnly = false;
  requiredFeatures.kvm = !arm;
  nodes = {
    host = { lib, ... }: {
      virtualisation.qemu.forceAccel = lib.mkForce (!arm);
      imports = [ module ];
      assbox = {
        enable = true;
        presentation = "headless";
        updates.enable = false;
        worker = {
          stateGiB = 8;
          enable = true;
          components = [ "vim" ];
          interface = "eth1";
          uplinkInterfaces = [ "eth2" ];
        };
      };
      # Peer VMs provide the packets; no nested virtualization is used in this gate.
      systemd.services.assbox-worker.enable = lib.mkForce false;
      systemd.services.assbox-worker-network.enable = lib.mkForce false;
      systemd.services.assbox-worker-provision.enable = lib.mkForce false;
      systemd.services.assbox-worker-health.enable = lib.mkForce false;
      systemd.timers.assbox-worker-health.enable = lib.mkForce false;
      systemd.services.assbox-boot-check.enable = lib.mkForce false;
      boot.loader.systemd-boot.enable = lib.mkForce false;
      boot.loader.grub.enable = lib.mkForce false;
      users.allowNoPasswordLogin = true;
      users.users.admin.hashedPasswordFile = lib.mkForce null;
      virtualisation.vlans = [
        1
        2
      ];
      networking.useDHCP = false;
      networking.networkmanager.enable = lib.mkForce false;
      networking.interfaces.eth1.ipv4.addresses = [
        {
          address = "10.77.0.1";
          prefixLength = 30;
        }
      ];
      networking.interfaces.eth1.ipv6.addresses = [
        {
          address = "fd77::1";
          prefixLength = 64;
        }
      ];
      networking.interfaces.eth2.ipv4.addresses = [
        {
          address = "192.168.55.1";
          prefixLength = 24;
        }
      ];
      networking.defaultGateway = "192.168.55.2";
      specialisation.normal.configuration.assbox.worker.egress = lib.mkForce "normal";
      specialisation.offline.configuration.assbox.worker = {
        egress = lib.mkForce "offline";
        uplinkInterfaces = lib.mkForce [ ];
        nameservers = lib.mkForce [ ];
      };
      # Even a host service deliberately opened by an unrelated module stays
      # inaccessible to unsolicited worker traffic because the drop is independent.
      networking.firewall.allowedTCPPorts = [
        18080
        18083
      ];
      environment.systemPackages = [
        pkgs.python3
        pkgs.curl
      ];
      systemd.services.listener = {
        wantedBy = [ "multi-user.target" ];
        serviceConfig.ExecStart = "${pkgs.python3}/bin/python3 -m http.server 18080 --bind 0.0.0.0 --directory /run";
      };
      systemd.services.listener6 = {
        wantedBy = [ "multi-user.target" ];
        serviceConfig.ExecStart = "${pkgs.python3}/bin/python3 -m http.server 18083 --bind :: --directory /run";
      };
      system.stateVersion = "26.05";
    };
    attacker = { ... }: {
      virtualisation.qemu.forceAccel = pkgs.lib.mkForce (!arm);
      virtualisation.vlans = [ 1 ];
      networking.useDHCP = false;
      networking.interfaces.eth1.ipv4.addresses = [
        {
          address = "10.77.0.2";
          prefixLength = 30;
        }
      ];
      networking.interfaces.eth1.ipv6.addresses = [
        {
          address = "fd77::2";
          prefixLength = 64;
        }
      ];
      networking.defaultGateway = "10.77.0.1";
      networking.firewall.enable = false;
      environment.systemPackages = [
        pkgs.curl
        pkgs.python3
        pkgs.bind.dnsutils
      ];
      systemd.services.listener = {
        wantedBy = [ "multi-user.target" ];
        serviceConfig.ExecStart = "${pkgs.python3}/bin/python3 -m http.server 18082 --bind 0.0.0.0 --directory /run";
      };
      system.stateVersion = "26.05";
    };
    outside = { ... }: {
      virtualisation.qemu.forceAccel = pkgs.lib.mkForce (!arm);
      virtualisation.vlans = [ 2 ];
      networking.useDHCP = false;
      networking.interfaces.eth1.ipv4.addresses = [
        {
          address = "192.168.55.2";
          prefixLength = 24;
        }
        # A simulated public address entirely inside the test network.
        {
          address = "8.8.8.8";
          prefixLength = 32;
        }
      ];
      networking.firewall.enable = false;
      environment.systemPackages = [
        pkgs.curl
        pkgs.python3
      ];
      systemd.services.listener = {
        wantedBy = [ "multi-user.target" ];
        serviceConfig.ExecStart = "${pkgs.python3}/bin/python3 -m http.server 18081 --bind 0.0.0.0 --directory /run";
      };
      services.dnsmasq = {
        enable = true;
        settings = {
          no-resolv = true;
          address = "/worker-fixture.test/8.8.8.8";
        };
      };
      system.stateVersion = "26.05";
    };
  };
  testScript = ''
    start_all()
    for machine in machines:
        machine.wait_for_unit("multi-user.target")
        machine.wait_for_unit("listener.service")
    host.wait_for_unit("nftables.service")
    outside.wait_for_unit("dnsmasq.service")
    original = host.succeed("readlink -f /run/current-system").strip()
    host.wait_for_unit("listener6.service")
    host.wait_until_succeeds("curl --noproxy '*' -g -fsS --max-time 3 http://[::1]:18083/ >/dev/null")
    outside.wait_until_succeeds("curl --noproxy '*' -fsS --max-time 3 http://192.168.55.1:18080/ >/dev/null")
    attacker.succeed("ip route replace default via 10.77.0.1 dev eth1")
    host.succeed("ip route replace default via 192.168.55.2 dev eth2")
    public = "curl --noproxy '*' --interface 10.77.0.2 -fsS --max-time 4 http://8.8.8.8:18081/ >/dev/null"
    attacker.wait_until_succeeds(public)
    public_dns = "dig +tries=1 +time=2 +short @8.8.8.8 worker-fixture.test A"
    private_dns = "dig +tries=1 +time=2 +short @192.168.55.2 worker-fixture.test A"
    assert attacker.succeed(public_dns).strip() == "8.8.8.8"
    attacker.fail(private_dns)
    # Default host firewall permits this port; the independent worker drop wins.
    attacker.fail("curl --noproxy '*' -fsS --max-time 3 http://10.77.0.1:18080/")
    attacker.fail("curl --noproxy '*' -fsS --max-time 3 http://192.168.55.2:18081/")
    attacker.fail("curl --noproxy '*' -g -fsS --max-time 3 http://[fd77::1]:18083/")
    # Host-initiated transport and its replies remain usable.
    host.succeed("curl --noproxy '*' -fsS --max-time 4 http://10.77.0.2:18082/ >/dev/null")
    # Guest root can change its own address, not the host's source policy.
    attacker.succeed("ip addr add 10.77.0.6/32 dev eth1")
    attacker.fail("curl --noproxy '*' --interface 10.77.0.6 -fsS --max-time 3 http://8.8.8.8:18081/")
    attacker.succeed(public)
    # Atomic reload retains both working egress and host-service denial.
    host.succeed("systemctl reload nftables")
    attacker.succeed(public)
    attacker.fail("curl --noproxy '*' -fsS --max-time 3 http://10.77.0.1:18080/")
    # Exercise all policies from evaluated production configurations.
    host.succeed(f"{original}/specialisation/normal/bin/switch-to-configuration test")
    attacker.succeed(public)
    assert attacker.succeed(public_dns).strip() == "8.8.8.8"
    assert attacker.succeed(private_dns).strip() == "8.8.8.8"
    attacker.succeed("curl --noproxy '*' -fsS --max-time 4 http://192.168.55.2:18081/ >/dev/null")
    attacker.fail("curl --noproxy '*' -fsS --max-time 3 http://10.77.0.1:18080/")
    outside.succeed("ip route replace 10.77.0.0/30 via 192.168.55.1")
    outside.fail("curl --noproxy '*' -fsS --max-time 3 http://10.77.0.2:18082/")
    attacker.fail("curl --noproxy '*' --interface 10.77.0.6 -fsS --max-time 3 http://8.8.8.8:18081/")
    host.succeed(f"{original}/specialisation/offline/bin/switch-to-configuration test")
    attacker.fail(public)
    attacker.fail(public_dns)
    attacker.fail(private_dns)
    attacker.fail("curl --noproxy '*' -fsS --max-time 3 http://192.168.55.2:18081/")
    host.succeed("curl --noproxy '*' -fsS --max-time 4 http://10.77.0.2:18082/ >/dev/null")
  '';
}
