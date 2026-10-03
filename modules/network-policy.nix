# SPDX-License-Identifier: GPL-3.0-or-later
{
  config,
  lib,
  pkgs,
  ...
}:
let
  cfg = config.assbox.network.execution;
  uid = toString config.users.users.agent.uid;
  admission = pkgs.writeShellScript "assbox-execution-admission" ''
    test "$PAM_USER" = agent || exit 0
    ${pkgs.systemd}/bin/systemctl is-active --quiet nftables.service || exit 1
    ${pkgs.nftables}/bin/nft list table inet assbox-execution >/dev/null 2>&1 || exit 1
  '';
  revoke = pkgs.writeShellScript "assbox-revoke-execution" ''
    ${pkgs.systemd}/bin/loginctl terminate-user 1000 || true
  '';
  ip4 = [
    "0.0.0.0/8"
    "10.0.0.0/8"
    "100.64.0.0/10"
    "127.0.0.0/8"
    "169.254.0.0/16"
    "172.16.0.0/12"
    "192.0.0.0/24"
    "192.0.2.0/24"
    "192.168.0.0/16"
    "198.18.0.0/15"
    "198.51.100.0/24"
    "203.0.113.0/24"
    "224.0.0.0/4"
    "240.0.0.0/4"
  ];
  ip6 = [
    "::/96"
    "::ffff:0:0/96"
    "64:ff9b::/96"
    "64:ff9b:1::/48"
    "100::/64"
    "2001::/32"
    "2001:db8::/32"
    "2002::/16"
    "fc00::/7"
    "fe80::/10"
    "ff00::/8"
  ];
  exceptions = lib.concatMapStringsSep "\n" (
    e:
    "meta skuid ${uid} ${
      if lib.hasInfix ":" e.address then "ip6" else "ip"
    } daddr ${e.address} ${e.protocol} dport ${toString e.port} accept"
  ) cfg.exceptions;
  table = ''
    set denied4 { type ipv4_addr; flags interval; auto-merge; elements = { ${
      lib.concatStringsSep ", " (ip4 ++ cfg.additionalDenied4)
    } } }
    set denied6 { type ipv6_addr; flags interval; auto-merge; elements = { ${
      lib.concatStringsSep ", " (ip6 ++ cfg.additionalDenied6)
    } } }
    chain output {
      type filter hook output priority 10; policy accept;
      # Reply direction only: an existing unauthorized workload connection cannot
      # survive a policy change by matching a general established rule.
      meta skuid ${uid} ct direction reply ct state established,related accept
      ${lib.optionalString (cfg.egress != "offline") exceptions}
      ${lib.optionalString (cfg.egress != "offline") ''
        meta skuid ${uid} ip daddr 127.0.0.53 udp dport 53 accept
              meta skuid ${uid} ip daddr 127.0.0.53 tcp dport 53 accept''}
      ${lib.optionalString (cfg.egress != "offline" && cfg.loopbackIpc) ''
        meta skuid ${uid} ip daddr 127.0.0.1 meta l4proto { tcp, udp } meta mark set 0x41534258 accept
              meta skuid ${uid} ip6 daddr ::1 meta l4proto { tcp, udp } meta mark set 0x41534258 accept''}
      meta skuid ${uid} fib daddr type local reject
      ${lib.optionalString (cfg.egress == "internet") ''
        meta skuid ${uid} ip daddr @denied4 reject
              meta skuid ${uid} ip6 daddr @denied6 reject''}
      ${lib.optionalString (cfg.egress == "offline") "meta skuid ${uid} reject"}
    }
    chain local_ipc {
      type filter hook input priority -150; policy accept;
      # On ingress the socket lookup identifies the receiving listener. This
      # permits dynamic provider IPC ports without authorizing root brokers.
      iifname "lo" meta mark 0x41534258 socket cgroupv2 level 2 "user.slice/user-1000.slice" accept
      iifname "lo" meta mark 0x41534258 reject
    }
  '';
in
{
  options.assbox.network.execution = {
    enable = lib.mkOption {
      type = lib.types.bool;
      default = true;
      description = "Root-owned standalone execution UID egress, across services and shells.";
    };
    egress = lib.mkOption {
      type = lib.types.enum [
        "internet"
        "normal"
        "offline"
      ];
      default = "internet";
    };
    loopbackIpc = lib.mkOption {
      type = lib.types.bool;
      default = true;
      description = "Loopback TCP/UDP IPC only to listeners in the execution user's slice, including provider-selected ephemeral ports.";
    };
    exceptions = lib.mkOption {
      type = lib.types.listOf (
        lib.types.submodule {
          options = {
            address = lib.mkOption { type = lib.types.strMatching "[0-9a-fA-F:.]+(/[0-9]{1,3})?"; };
            protocol = lib.mkOption {
              type = lib.types.enum [
                "tcp"
                "udp"
              ];
              default = "tcp";
            };
            port = lib.mkOption { type = lib.types.port; };
          };
        }
      );
      default = [ ];
      description = "Deliberately allowed destination/protocol/port tuples, including local services.";
    };
    additionalDenied4 = lib.mkOption {
      type = lib.types.listOf (lib.types.strMatching "[0-9.]+/[0-9]{1,2}");
      default = [ ];
    };
    additionalDenied6 = lib.mkOption {
      type = lib.types.listOf (lib.types.strMatching "[0-9a-fA-F:]+/[0-9]{1,3}");
      default = [ ];
    };
  };
  config = lib.mkIf (config.assbox.enable && cfg.enable && !config.assbox.controller.active) {
    assertions = [
      {
        assertion = config.users.users.agent.uid == 1000;
        message = "The execution egress identity must be the fixed unprivileged UID 1000.";
      }
    ];
    networking.nftables.enable = true;
    # NixOS checks rules in an LKL kernel without socket cgroupv2 support or the
    # installed user's slice. Adapt that expression only in the temporary check
    # copy; keep checking the surrounding rules. The deployed cgroup rule stays
    # unchanged and is exercised by the network policy acceptance tests.
    networking.nftables.preCheckRuleset = ''
      sed -i 's@socket cgroupv2 level 2 "user.slice/user-1000.slice"@meta mark 0x41534258@g' ruleset.conf
    '';
    networking.nftables.tables.assbox-execution = {
      family = "inet";
      content = table;
    };
    # nft resolves the receiver cgroup when loading the rules, before logins.
    systemd.slices."user-1000" = {
      before = [ "nftables.service" ];
    };
    systemd.services.nftables = {
      requires = [ "user-1000.slice" ];
      after = [ "user-1000.slice" ];
      serviceConfig.ExecStopPre = [ revoke ];
    };
    services.resolved.enable = true;
    # A root-owned build daemon is otherwise a proxy for private-network access.
    nix.settings.allowed-users = [ "root" ];
    # User-created network namespaces and FHS environments must keep traffic in
    # this namespace through an execution-UID userspace forwarder. No delegated
    # privileged network setup, rootless container socket or blanket devices.
    systemd.services."user@1000" = {
      requires = [ "nftables.service" ];
      after = [ "nftables.service" ];
      bindsTo = [ "nftables.service" ];
    };
    systemd.services.display-manager = lib.mkIf (config.assbox.presentation != "headless") {
      requires = [ "nftables.service" ];
      after = [ "nftables.service" ];
      bindsTo = [ "nftables.service" ];
    };
    systemd.services.greetd = lib.mkIf (config.assbox.presentation == "wayland") {
      requires = [ "nftables.service" ];
      after = [ "nftables.service" ];
      bindsTo = [ "nftables.service" ];
    };
    security.pam.services = lib.genAttrs [ "login" "sshd" "greetd" "lightdm" "su" "su-l" ] (_: {
      rules.account.assbox-network = {
        order = 0;
        control = "required";
        modulePath = "${pkgs.pam}/lib/security/pam_exec.so";
        args = [
          "quiet"
          (toString admission)
        ];
      };
    });
    environment.etc."assbox/execution-policy.json".text = builtins.toJSON {
      inherit (cfg)
        egress
        exceptions
        additionalDenied4
        additionalDenied6
        loopbackIpc
        ;
      uid = 1000;
    };
  };
}
