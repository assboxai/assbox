# SPDX-License-Identifier: GPL-3.0-or-later
{
  config,
  lib,
  pkgs,
  ...
}:
let
  cfg = config.assbox.network;
  ssh = cfg.ssh;
  enabled = ssh.admin.enable || ssh.agent.enable;
  interfaces = if ssh.exposure == "tailscale" then [ "tailscale0" ] else ssh.lanInterfaces;
  validInterface = name: builtins.match "[a-zA-Z0-9_.:-]{1,15}" name != null && name != "lo";
  validCidr =
    cidr:
    let
      parts = lib.splitString "/" cidr;
      address = builtins.head parts;
      prefix = lib.last parts;
      octet = "(25[0-5]|2[0-4][0-9]|1[0-9]{2}|[1-9]?[0-9])";
      ipv4 =
        builtins.match "${octet}\\.${octet}\\.${octet}\\.${octet}" address != null
        && builtins.match "([0-9]|[12][0-9]|3[0-2])" prefix != null;
      halves = lib.splitString "::" address;
      groups = lib.splitString ":" address;
      nonempty = builtins.filter (group: group != "") groups;
      ipv6 =
        builtins.match "([0-9]|[1-9][0-9]|1[01][0-9]|12[0-8])" prefix != null
        && !(lib.hasInfix ":::" address)
        && builtins.all (group: builtins.match "[0-9a-fA-F]{1,4}" group != null) nonempty
        && (
          if builtins.length halves == 2 then
            builtins.length nonempty < 8
            && builtins.all (
              half:
              half == ""
              || builtins.all (group: builtins.match "[0-9a-fA-F]{1,4}" group != null) (lib.splitString ":" half)
            ) halves
          else
            builtins.length halves == 1 && builtins.length groups == 8 && builtins.length nonempty == 8
        );
    in
    builtins.length parts == 2 && (ipv4 || ipv6);
  admissions = lib.concatMapStringsSep "\n" (
    iface:
    if ssh.exposure == "tailscale" || ssh.lanSourceCidrs == [ ] then
      ''iifname "${iface}" tcp dport 22 accept''
    else
      lib.concatMapStringsSep "\n" (
        cidr:
        ''iifname "${iface}" ${
          if lib.hasInfix ":" cidr then "ip6" else "ip"
        } saddr ${cidr} tcp dport 22 accept''
      ) (builtins.filter validCidr ssh.lanSourceCidrs)
  ) (builtins.filter validInterface interfaces);
in
{
  options.assbox.network = {
    tailscale.enable = lib.mkEnableOption "Tailscale overlay networking (interactive owner login required)";
    ssh = {
      admin.enable = lib.mkEnableOption "key-only administrative SSH";
      agent.enable = lib.mkEnableOption "unprivileged agent SSH for terminals and remote editors";
      admin.keys = lib.mkOption {
        type = lib.types.listOf lib.types.str;
        default = [ ];
        description = "Administrator public keys.";
      };
      agent.keys = lib.mkOption {
        type = lib.types.listOf lib.types.str;
        default = [ ];
        description = "Agent public keys; no administrative privileges.";
      };
      exposure = lib.mkOption {
        type = lib.types.enum [
          "tailscale"
          "lan"
        ];
        default = "tailscale";
        description = "Shared SSH listener exposure.";
      };
      lanInterfaces = lib.mkOption {
        type = lib.types.listOf lib.types.str;
        default = [ ];
        description = "Explicit interfaces for LAN SSH.";
      };
      lanSourceCidrs = lib.mkOption {
        type = lib.types.listOf lib.types.str;
        default = [ ];
        description = "Optional LAN source CIDRs; empty admits any source on selected interfaces.";
      };
    };
  };
  config = lib.mkIf config.assbox.enable {
    assertions = [
      {
        assertion = !enabled || ssh.exposure != "tailscale" || cfg.tailscale.enable;
        message = "Tailnet SSH requires explicit Tailscale enablement.";
      }
      {
        assertion = !enabled || ssh.exposure != "lan" || ssh.lanInterfaces != [ ];
        message = "LAN SSH requires explicit interfaces.";
      }
      {
        assertion = builtins.all validInterface interfaces;
        message = "Invalid SSH interface name.";
      }
      {
        assertion = builtins.all validCidr ssh.lanSourceCidrs;
        message = "SSH source restrictions must be CIDRs.";
      }
      {
        assertion = !ssh.admin.enable || ssh.admin.keys != [ ];
        message = "Administrative SSH requires its own public keys.";
      }
      {
        assertion = !ssh.agent.enable || ssh.agent.keys != [ ];
        message = "Agent SSH requires its own public keys.";
      }
    ];
    services.tailscale = lib.mkIf cfg.tailscale.enable {
      enable = true;
      openFirewall = true;
      extraSetFlags = [
        "--ssh=false"
        "--netfilter-mode=off"
        "--accept-routes=false"
      ];
    };
    systemd.services.tailscaled.serviceConfig.ExecStartPost = lib.mkIf cfg.tailscale.enable [
      "${pkgs.coreutils}/bin/chmod 0600 /run/tailscale/tailscaled.sock"
    ];
    users.users.admin.openssh.authorizedKeys.keys = lib.optionals ssh.admin.enable ssh.admin.keys;
    users.users.agent.openssh.authorizedKeys.keys = lib.optionals ssh.agent.enable ssh.agent.keys;
    services.openssh = {
      enable = enabled;
      openFirewall = false;
      settings = {
        PasswordAuthentication = false;
        KbdInteractiveAuthentication = false;
        PermitRootLogin = "no";
        AllowUsers = lib.optional ssh.admin.enable "admin" ++ lib.optional ssh.agent.enable "agent";
        AllowAgentForwarding = false;
        GatewayPorts = "no";
        AllowTcpForwarding = "local";
        PermitOpen = "localhost:* 127.0.0.1:* [::1]:*";
      };
    };
    networking.firewall.interfaces = lib.genAttrs (builtins.filter validInterface interfaces) (_: {
      allowedTCPPorts = lib.optional enabled 22;
    });
    # An independent input hook rejects other ingress even if another service
    # installs an ACCEPT rule. No trust of the entire tailscale0 interface.
    networking.nftables.enable = true;
    networking.nftables.tables.assbox-ssh = lib.mkIf enabled {
      family = "inet";
      content = ''
        chain input {
          type filter hook input priority 10; policy accept;
          iifname "lo" tcp dport 22 accept
          ${admissions}
          tcp dport 22 drop
        }
      '';
    };
  };
}
