# SPDX-License-Identifier: GPL-3.0-or-later
# Deliberately does not import the host, bootloader, updater, display or access modules.
{
  config,
  lib,
  pkgs,
  assboxPackage,
  workerSettings,
  ...
}:
let
  healthShell = pkgs.writeShellScriptBin "assbox-health-shell" ''
    # Ignore all caller arguments. Never consult the persistent workload home.
    printf 'ASSBOX-WORKER-HEALTH/1\n'
    exec ${pkgs.coreutils}/bin/cat /assbox-worker-build-id
  '';
in
{
  imports = [
    ../options.nix
    ../computer-use.nix
    ../resources.nix
    ../state.nix
    ../service-control.nix
    ../components.nix
    ../applications.nix
    ../remotes.nix
    ../editors.nix
  ];

  # editors.nix uses this fact to validate SSH-backed editor components. Actual
  # authentication below is runtime-seeded; no private key enters the Nix store.
  options.assbox.network.ssh.agent.enable = lib.mkOption {
    type = lib.types.bool;
    default = true;
    internal = true;
  };

  config = {
    assbox = {
      enable = true;
      presentation = "headless";
      acceptUnfree = workerSettings.acceptUnfree;
      components = lib.genAttrs workerSettings.components (name: {
        enable = true;
        allowMutableCode = builtins.elem name workerSettings.allowMutableCodeFor;
      });
      updates.enable = false;
      session.autostart = [ ];
      computerUse.mode = workerSettings.computerUseMode;
      state.directory = lib.mkDefault "/home/.assbox-state-backups";
      controller = {
        active = false;
        profile = "none";
      };
    };
    assertions = [
      {
        assertion = config.assbox.presentation == "headless";
        message = "The isolated worker is headless; do not forward a host display.";
      }
      {
        assertion =
          config.assbox.selectedComponents == builtins.sort builtins.lessThan workerSettings.components;
        message = "Select every guest component in assbox.worker.components, not only in extraGuestConfig.";
      }
    ];
    networking = {
      hostName = "assbox-worker";
      useDHCP = false;
      enableIPv6 = false;
      interfaces.eth0.ipv4.addresses = [
        {
          address = workerSettings.guestAddress;
          prefixLength = 30;
        }
      ];
      defaultGateway = workerSettings.hostAddress;
      nameservers = workerSettings.nameservers;
      firewall = {
        enable = true;
        allowedTCPPorts = [ 22 ];
        allowPing = false;
      };
    };
    boot = {
      kernelParams = [ "net.ifnames=0" ];
      initrd.availableKernelModules = [
        "virtio_pci"
        "virtio_blk"
        "virtio_net"
        "ext4"
        "isofs"
      ];
      loader.grub.enable = false;
      loader.systemd-boot.enable = false;
    };
    fileSystems = {
      "/" = {
        device = "/dev/vda";
        fsType = "ext4";
      };
      "/home" = {
        device = "/dev/disk/by-label/ASSBOX_WORK";
        fsType = "ext4";
        options = [
          "nodev"
          "nosuid"
        ];
        neededForBoot = true;
      };
      "/run/assbox-seed" = {
        device = "/dev/vdc";
        fsType = "iso9660";
        options = [
          "ro"
          "nodev"
          "nosuid"
          "noexec"
        ];
      };
    };
    services.openssh = {
      enable = true;
      openFirewall = false;
      # Host-generated seed is the sole identity source. Do not race the mount
      # with a guest key-generation service.
      generateHostKeys = false;
      authorizedKeysInHomedir = false;
      hostKeys = [
        {
          type = "ed25519";
          path = "/run/assbox-seed/ssh_host_ed25519_key";
        }
      ];
      authorizedKeysFiles = lib.mkForce [ "/run/assbox-seed/%u.pub" ];
      extraConfig = ''
        Match User assbox-health
          ForceCommand ${healthShell}/bin/assbox-health-shell
          DisableForwarding yes
          PermitTTY no
          PermitUserRC no
      '';
      settings = {
        PasswordAuthentication = false;
        KbdInteractiveAuthentication = false;
        PermitRootLogin = "no";
        AllowUsers = [
          "agent"
          "assbox-health"
        ];
        PermitUserRC = false;
        AllowAgentForwarding = false;
        X11Forwarding = false;
        PermitTunnel = "no";
        PermitUserEnvironment = false;
        GatewayPorts = "no";
        AllowTcpForwarding = "local";
        PermitOpen = "localhost:* 127.0.0.1:* [::1]:*";
      };
    };
    systemd.services.sshd = {
      requires = [ "run-assbox\\x2dseed.mount" ];
      after = [ "run-assbox\\x2dseed.mount" ];
    };
    users.groups.assbox-health = { };
    users.users.assbox-health = {
      isSystemUser = true;
      group = "assbox-health";
      home = "/var/empty";
      createHome = false;
      hashedPassword = "!";
      # A script derivation is not a NixOS shell package. Use its executable
      # subpath, not the derivation's top-level store path.
      shell = "${healthShell}/bin/assbox-health-shell";
    };
    # No static root/wheel login is intentional. SSH public keys arrive only
    # from the runtime seed; this suppresses NixOS's static lockout assertion,
    # not SSH/PAM authentication. All account passwords remain locked.
    users.allowNoPasswordLogin = true;
    users.mutableUsers = false;
    users.users.root.hashedPassword = "!";
    users.users.agent = {
      isNormalUser = true;
      uid = 1000;
      home = "/home/agent";
      homeMode = "0700";
      hashedPassword = "!";
      linger = true;
      extraGroups = lib.optional workerSettings.allowGuestSudo "wheel";
    };
    security.sudo = {
      enable = workerSettings.allowGuestSudo;
      wheelNeedsPassword = !workerSettings.allowGuestSudo;
    };
    services.dbus.enable = true;
    services.timesyncd.enable = true;
    time.timeZone = workerSettings.timeZone;
    environment.systemPackages = with pkgs; [
      assboxPackage
      bash
      coreutils
      findutils
      gnugrep
      gnused
      gawk
      python3
      curl
      git
      jq
      ripgrep
      fd
      less
      file
      which
      gnutar
      gzip
      xz
      zstd
      unzip
      procps
      psmisc
      util-linux
      iproute2
      tmux
      nano
      rsync
      openssh
      cacert
    ];
    environment.variables.EDITOR = lib.mkDefault config.assbox.editor.default;
    environment.etc."assbox/runtime.json".text = builtins.toJSON {
      inherit (config.assbox)
        selectedComponents
        presentation
        platform
        updates
        ;
      boot = config.assbox.boot;
      session.autostart = [ ];
    };
    environment.etc."assbox/worker-components.json".text = builtins.toJSON workerSettings.components;
    environment.etc."assbox/worker-role".text = "execution-worker\n";
    environment.etc."assbox/codex-example.toml".text = ''
      # Copy into ~/.codex/config.toml deliberately; existing settings are not overwritten.
      # Credentials are intentionally inside the guest trust domain.
      cli_auth_credentials_store = "file"
      sandbox_mode = "workspace-write"
      approval_policy = "on-request"
    '';
    systemd.tmpfiles.rules = [ "d /home/agent/projects 0700 agent users -" ];
    nix.settings = {
      experimental-features = [
        "nix-command"
        "flakes"
      ];
      sandbox = true;
      require-sigs = true;
      accept-flake-config = false;
      trusted-users = [ "root" ];
      substituters = [ "https://cache.nixos.org" ];
      trusted-public-keys = [ "cache.nixos.org-1:6NCHdD59X431o0gWypbMrAURkbJ16ZPMQFGspcDShjY=" ];
    };
    nix.gc.automatic = false;
    system.autoUpgrade.enable = false;
    # The host supplies RAM compression. Avoid two independently sized zram pools.
    zramSwap.enable = false;
    system.stateVersion = "26.05";
  };
}
