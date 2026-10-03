# SPDX-License-Identifier: GPL-3.0-or-later
{
  config,
  lib,
  pkgs,
  assboxApplications,
  assboxPackage,
  ...
}:
let
  cfg = config.assbox.worker;
  catalog = builtins.fromJSON (builtins.readFile ../../catalog/components.json);
  eligible = map (row: row.id) (
    builtins.filter (
      row: row.blocked == "" && row.workerAllowed && builtins.elem "headless" row.presentations
    ) catalog
  );
  controllerComponents = map (row: row.id) (builtins.filter (row: row.controllerAllowed) catalog);
  interfaceType = lib.types.strMatching "[a-zA-Z0-9_-]{1,15}";
  ipv4Type = lib.types.strMatching "[0-9]{1,3}(\\.[0-9]{1,3}){3}";
  settings = {
    inherit (cfg)
      components
      allowMutableCodeFor
      allowGuestSudo
      hostAddress
      guestAddress
      nameservers
      ;
    inherit (config.assbox) acceptUnfree;
    timeZone = config.time.timeZone;
    computerUseMode = cfg.computerUseMode;
  };
  guest = import (pkgs.path + "/nixos/lib/eval-config.nix") {
    system = pkgs.stdenv.hostPlatform.system;
    specialArgs = {
      inherit assboxApplications assboxPackage;
      workerSettings = settings;
    };
    modules = [
      ./guest.nix
      cfg.extraGuestConfig
      { nixpkgs.pkgs = pkgs; }
    ];
  };
  image = import ../../nix/worker-image.nix {
    inherit pkgs guest;
    inherit (cfg) scratchGiB maxArtifactMiB;
  };
  runtime = pkgs.stdenvNoCC.mkDerivation {
    pname = "assbox-worker-tools";
    version = "1";
    src = ../../scripts/worker;
    nativeBuildInputs = [ pkgs.makeWrapper ];
    installPhase = ''
      mkdir -p "$out/libexec/assbox-worker" "$out/bin"
      cp *.py "$out/libexec/assbox-worker/"
      makeWrapper ${pkgs.python3}/bin/python3 "$out/bin/assbox-worker" \
        --add-flags "$out/libexec/assbox-worker/worker.py" \
        --set ASSBOX_WORKER_CONFIG /etc/assbox/worker-runtime.json
    '';
  };
  machine = if pkgs.stdenv.hostPlatform.isAarch64 then "virt,gic-version=host" else "q35";
  qemuBinary =
    if pkgs.stdenv.hostPlatform.isAarch64 then "qemu-system-aarch64" else "qemu-system-x86_64";
  privateRanges = [
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
  uplinks = lib.concatMapStringsSep ", " (n: ''"${n}"'') cfg.uplinkInterfaces;
  publicEgress = cfg.egress != "offline";
  deniedRanges =
    if cfg.egress == "normal" then
      builtins.filter (
        range:
        !(builtins.elem range [
          "10.0.0.0/8"
          "100.64.0.0/10"
          "172.16.0.0/12"
          "192.168.0.0/16"
        ])
      ) privateRanges
    else
      privateRanges;
  sshText = ''
    Host assbox-worker
      HostName ${cfg.guestAddress}
      Port 22
      User agent
      IdentityFile /var/lib/assbox-worker-control/client_ed25519
      PasswordAuthentication no
      KbdInteractiveAuthentication no
      PreferredAuthentications publickey
      PubkeyAuthentication yes
      Tunnel no
      IdentitiesOnly yes
      IdentityAgent none
      ProxyCommand none
      ProxyJump none
      CanonicalizeHostname no
      RemoteCommand none
      HostKeyAlias assbox-worker
      GlobalKnownHostsFile /var/lib/assbox-worker-control/known_hosts
      UserKnownHostsFile /dev/null
      StrictHostKeyChecking yes
      UpdateHostKeys no
      ForwardAgent no
      ForwardX11 no
      ForwardX11Trusted no
      PermitLocalCommand no
      ControlMaster no
      ControlPath none
      EscapeChar none
      ServerAliveInterval 30
      ServerAliveCountMax 3
  '';
  runtimeConfig = {
    schema = 2;
    controller = "agent";
    vmm = "assbox-vmm";
    inherit (cfg)
      memoryMiB
      vcpus
      hostReserveMiB
      stateGiB
      interface
      hostAddress
      guestAddress
      uplinkInterfaces
      egress
      nameservers
      additionalDeniedCidrs
      ;
    inherit machine;
    dataDir = "/var/lib/assbox-worker-data";
    controlDir = "/var/lib/assbox-worker-control";
    identityDir = "/var/lib/assbox-worker-identity";
    seedDir = "/var/lib/assbox-worker-seed";
    healthProbeDir = "/var/lib/assbox-worker-health";
    runDir = "/run/assbox-worker";
    artifact = "${image}";
    buildId = image.buildId;
    selectedComponents = cfg.components;
    sshConfig = "/etc/assbox/worker-ssh-config";
    healthSshConfig = "/etc/assbox/worker-health-ssh-config";
    tools = {
      qemu = "${pkgs.qemu_kvm}/bin/${qemuBinary}";
      qemuImg = "${pkgs.qemu_kvm}/bin/qemu-img";
      ssh = "${pkgs.openssh}/bin/ssh";
      sshKeygen = "${pkgs.openssh}/bin/ssh-keygen";
      mkfs = "${pkgs.e2fsprogs}/bin/mkfs.ext4";
      xorriso = "${pkgs.xorriso}/bin/xorriso";
      ip = "${pkgs.iproute2}/bin/ip";
      systemctl = "${pkgs.systemd}/bin/systemctl";
      nft = "${pkgs.nftables}/bin/nft";
    };
  };
  runtimeFile = pkgs.writeText "assbox-worker-runtime.json" (builtins.toJSON runtimeConfig);
in
{
  imports = [
    ./identities.nix
    ./boot-retry.nix
  ];
  options.assbox.worker = {
    enable = lib.mkEnableOption "a separately booted, headless QEMU/KVM execution worker";
    components = lib.mkOption {
      type = lib.types.listOf (lib.types.enum eligible);
      default = [ ];
      description = "Explicit worker component IDs. Dependencies must also be selected; no agent is implicit.";
    };
    allowMutableCodeFor = lib.mkOption {
      type = lib.types.listOf (lib.types.enum eligible);
      default = [ ];
      description = "Per-component acknowledgement of worker client/provider-managed downloads.";
    };
    computerUseMode = lib.mkOption {
      type = lib.types.enum [
        "none"
        "browser"
        "virtual-desktop"
      ];
      default = "none";
    };
    allowGuestSudo = lib.mkEnableOption "passwordless sudo inside the worker VM only";
    maxArtifactMiB = lib.mkOption {
      type = lib.types.ints.between 1024 65536;
      default = 16384;
      description = "Hard build-time size limit for one self-contained worker artifact. Budget retained generations and transient build space separately.";
    };
    memoryMiB = lib.mkOption {
      type = lib.types.ints.between 2048 65536;
      default = 3072;
    };
    hostReserveMiB = lib.mkOption {
      type = lib.types.ints.between 1024 16384;
      default = 2048;
    };
    vcpus = lib.mkOption {
      type = lib.types.ints.between 1 32;
      default = 2;
    };
    stateGiB = lib.mkOption {
      type = lib.types.nullOr (lib.types.ints.between 8 2048);
      default = null;
      description = "Explicit persistent capacity. Use worker setup/configure --state-gib auto for first-time automatic sizing; existing disks are never resized.";
    };
    scratchGiB = lib.mkOption {
      type = lib.types.ints.between 4 256;
      default = 8;
    };
    interface = lib.mkOption {
      type = interfaceType;
      default = "ab-worker0";
    };
    hostAddress = lib.mkOption {
      type = ipv4Type;
      default = "10.77.0.1";
    };
    guestAddress = lib.mkOption {
      type = ipv4Type;
      default = "10.77.0.2";
    };
    uplinkInterfaces = lib.mkOption {
      type = lib.types.listOf interfaceType;
      default = [ ];
      description = "Explicit controller egress interfaces, e.g. enp3s0 and/or wlp2s0. No LAN bridge.";
    };
    egress = lib.mkOption {
      type = lib.types.enum [
        "normal"
        "internet"
        "offline"
      ];
      default = "internet";
      description = "Normal permits outbound IPv4 internet and LAN. Internet denies protected prefixes. Offline keeps controller-initiated SSH. These policies do not prevent exfiltration.";
    };
    nameservers = lib.mkOption {
      type = lib.types.listOf ipv4Type;
      default = [
        "1.1.1.1"
        "9.9.9.9"
      ];
      description = "Worker IPv4 DNS permitted by the egress policy; never the controller resolver.";
    };
    additionalDeniedCidrs = lib.mkOption {
      type = lib.types.listOf (lib.types.strMatching "[0-9]{1,3}(\\.[0-9]{1,3}){3}/[0-9]{1,2}");
      default = [ ];
      description = "Also deny organizational/public LAN and owned public prefixes. Not an allowlist override.";
    };
    extraGuestConfig = lib.mkOption {
      type = lib.types.deferredModule;
      default = { };
      description = "Trusted administrator NixOS module for worker tools and component settings; not agent-editable policy.";
    };
  };

  config = lib.mkIf (config.assbox.enable && cfg.enable) {
    assertions = [
      {
        assertion = cfg.stateGiB != null;
        message = "Set worker.stateGiB explicitly, or use assbox worker setup for automatic sizing. For an existing disk retain its capacity.";
      }
      {
        assertion =
          cfg.components != [ ]
          && builtins.length cfg.components == builtins.length (lib.unique cfg.components);
        message = "Worker requires a nonempty, duplicate-free explicit component selection.";
      }
      {
        assertion = builtins.all (name: builtins.elem name cfg.components) cfg.allowMutableCodeFor;
        message = "Mutable-code consent must refer to a selected worker component.";
      }
      {
        assertion = !publicEgress || cfg.uplinkInterfaces != [ ];
        message = "Worker internet egress requires explicit uplinkInterfaces.";
      }
      {
        assertion = publicEgress || (cfg.uplinkInterfaces == [ ] && cfg.nameservers == [ ]);
        message = "Offline workers must not select uplinks or DNS resolvers.";
      }
      {
        assertion = !(builtins.elem cfg.interface cfg.uplinkInterfaces);
        message = "Worker TAP cannot be an uplink.";
      }
      {
        assertion = builtins.all (
          name: builtins.elem name controllerComponents
        ) config.assbox.selectedComponents;
        message = "Move curated execution components to assbox.worker.components. Placement cannot be disabled.";
      }
    ];
    boot.kernelModules = [
      "kvm"
      "tun"
    ];
    boot.kernel.sysctl."net.ipv4.ip_forward" = lib.mkIf publicEgress 1;
    networking.networkmanager.unmanaged = [ "interface-name:${cfg.interface}" ];
    networking.nftables.enable = true;
    networking.firewall.filterForward = true;
    networking.firewall.extraForwardRules = lib.mkIf publicEgress ''
      iifname "${cfg.interface}" oifname { ${uplinks} } ip saddr ${cfg.guestAddress} accept
    '';
    networking.nftables.tables.assbox-worker = {
      family = "inet";
      content = ''
        set denied4 {
          type ipv4_addr; flags interval; auto-merge;
          elements = { ${lib.concatStringsSep ", " (deniedRanges ++ cfg.additionalDeniedCidrs)} }
        }
        chain input {
          type filter hook input priority -10; policy accept;
          iifname "${cfg.interface}" meta nfproto ipv6 counter drop
          iifname "${cfg.interface}" ip saddr != ${cfg.guestAddress} counter drop
          iifname "${cfg.interface}" ct state established,related accept
          iifname "${cfg.interface}" counter drop
        }
        chain forward {
          type filter hook forward priority -10; policy accept;
          iifname "${cfg.interface}" meta nfproto ipv6 counter drop
          iifname "${cfg.interface}" ip saddr != ${cfg.guestAddress} counter drop
          iifname "${cfg.interface}" ip daddr @denied4 counter drop
          ${lib.optionalString publicEgress ''
            iifname "${cfg.interface}" oifname { ${uplinks} } ct state new,established,related accept
            oifname "${cfg.interface}" ip daddr ${cfg.guestAddress} ct state established,related accept
          ''}
          iifname "${cfg.interface}" counter drop
          oifname "${cfg.interface}" counter drop
        }
      '';
    };
    networking.nftables.tables.assbox-worker-nat = lib.mkIf publicEgress {
      family = "ip";
      content = ''
        chain postrouting {
          type nat hook postrouting priority srcnat; policy accept;
          ip saddr ${cfg.guestAddress} oifname { ${uplinks} } masquerade
        }
      '';
    };
    environment.systemPackages = [ runtime ];
    environment.etc."assbox/worker-runtime.json".source = runtimeFile;
    environment.etc."assbox/worker-ssh-config".text = sshText;
    environment.etc."assbox/worker-health-ssh-config".text = ''
      Host assbox-worker-health
        HostName ${cfg.guestAddress}
        Port 22
        User assbox-health
        IdentityFile /var/lib/assbox-worker-health/health_ed25519
        PasswordAuthentication no
        KbdInteractiveAuthentication no
        PreferredAuthentications publickey
        PubkeyAuthentication yes
        Tunnel no
        ForwardX11Trusted no
        IdentitiesOnly yes
        IdentityAgent none
        ProxyCommand none
        ProxyJump none
        CanonicalizeHostname no
        RemoteCommand none
        HostKeyAlias assbox-worker
        GlobalKnownHostsFile /var/lib/assbox-worker-health/known_hosts
        UserKnownHostsFile /dev/null
        StrictHostKeyChecking yes
        UpdateHostKeys no
        ForwardAgent no
        ForwardX11 no
        PermitLocalCommand no
        ControlMaster no
        ControlPath none
        EscapeChar none
        RequestTTY no
    '';
    system.build.assboxWorkerImage = image;
    # Explicit release scanning must inspect packages hidden inside the image.
    # This evaluation attribute is not a runtime GC root or a toplevel symlink.
    system.build.assboxWorkerAudit = image.auditClosure;
    # Only the artifact, not the ordinary guest closure, is a host runtime root.
    system.systemBuilderCommands = ''
      ln -s ${image} "$out/assbox-worker-image"
    '';
    assbox.workerBootPolicy = {
      schema = 1;
      enabled = true;
      checker = "${runtime}/bin/assbox-worker";
      configuration = "${runtimeFile}";
      buildId = image.buildId;
    };
    systemd.services.assbox-worker-provision = {
      restartTriggers = [ runtimeFile ];
      description = "Create dedicated worker identities without copying Desktop credentials";
      after = [ "systemd-tmpfiles-setup.service" ];
      before = [ "assbox-worker.service" ];
      serviceConfig = {
        Type = "oneshot";
        RemainAfterExit = true;
        ExecStart = "${runtime}/bin/assbox-worker internal-provision";
        UMask = "0077";
      };
    };
    systemd.services.assbox-worker-network = {
      restartTriggers = [ runtimeFile ];
      description = "Private routed TAP for the Assbox worker";
      requires = [ "nftables.service" ];
      after = [ "nftables.service" ];
      bindsTo = [ "nftables.service" ];
      before = [ "assbox-worker.service" ];
      serviceConfig = {
        Type = "oneshot";
        RemainAfterExit = true;
        ExecStart = "${runtime}/bin/assbox-worker internal-network-up";
        ExecStop = "${runtime}/bin/assbox-worker internal-network-down";
        UMask = "0077";
      };
    };
    systemd.services.assbox-worker = {
      restartTriggers = [ runtimeFile ];
      description = "Assbox isolated execution worker";
      wantedBy = [ "multi-user.target" ];
      requires = [
        "assbox-worker-provision.service"
        "assbox-worker-network.service"
        "nftables.service"
      ];
      after = [
        "assbox-worker-provision.service"
        "assbox-worker-network.service"
        "nftables.service"
      ];
      bindsTo = [
        "assbox-worker-network.service"
        "nftables.service"
      ];
      restartIfChanged = true;
      unitConfig.StartLimitIntervalSec = 0;
      serviceConfig = {
        User = "assbox-vmm";
        Group = "assbox-vmm";
        SupplementaryGroups = [ "kvm" ];
        Type = "simple";
        ExecStartPre = "${runtime}/bin/assbox-worker internal-prepare";
        ExecStart = "${runtime}/bin/assbox-worker internal-run";
        ExecStop = "${runtime}/bin/assbox-worker internal-powerdown";
        Restart = "always";
        RestartSec = 30;
        TimeoutStopSec = 100;
        KillMode = "control-group";
        UMask = "0077";
        RuntimeDirectory = "assbox-worker";
        RuntimeDirectoryMode = "0700";
        ReadWritePaths = [
          "/var/lib/assbox-worker-data"
          "/run/assbox-worker"
        ];
        ProtectSystem = "strict";
        ProtectHome = true;
        PrivateTmp = true;
        PrivateMounts = true;
        NoNewPrivileges = true;
        ProtectKernelTunables = true;
        ProtectKernelModules = true;
        ProtectControlGroups = true;
        ProtectProc = "invisible";
        ProtectKernelLogs = true;
        ProtectClock = true;
        RestrictAddressFamilies = [
          "AF_UNIX"
          "AF_NETLINK"
        ];
        InaccessiblePaths = [
          "-/run/user"
          "-/run/dbus"
          "-/run/libvirt"
          "-/run/docker.sock"
          "-/run/nix/daemon-socket"
          "/var/lib/assbox"
          "/var/lib/assbox-secrets"
          "/var/lib/assbox-worker-control"
          "/var/lib/assbox-worker-identity"
          "/var/lib/assbox-worker-health"
        ];
        RestrictSUIDSGID = true;
        RestrictNamespaces = true;
        LockPersonality = true;
        RestrictRealtime = true;
        CapabilityBoundingSet = "";
        DevicePolicy = "closed";
        DeviceAllow = [
          "/dev/kvm rw"
          "/dev/net/tun rw"
          "/dev/urandom r"
        ];
        IPAddressDeny = "any";
        CPUAccounting = true;
        IOAccounting = true;
        MemoryAccounting = true;
        MemoryMax = "${toString (cfg.memoryMiB + 1024)}M";
        MemorySwapMax = "0";
        CPUQuota = "${toString (cfg.vcpus * 100)}%";
        TasksMax = 256;
        LimitCORE = 0;
        StandardOutput = "journal";
        StandardError = "journal";
      };
    };
    systemd.services.assbox-worker-health = {
      description = "Check the worker transport and expected running generation";
      requires = [ "assbox-worker.service" ];
      after = [ "assbox-worker.service" ];
      serviceConfig = {
        Type = "oneshot";
        ExecStart = "${runtime}/bin/assbox-worker check";
        TimeoutStartSec = 120;
        UMask = "0077";
      };
    };
    systemd.timers.assbox-worker-health = {
      wantedBy = [ "timers.target" ];
      timerConfig = {
        OnBootSec = "2min";
        OnUnitActiveSec = "5min";
      };
    };
    # Ordering is not the acceptance authority. The engine reads its generation's
    # immutable worker policy and checks health before clearing pending state/GC.
    systemd.services.assbox-boot-check.after = [ "assbox-worker.service" ];
  };
}
