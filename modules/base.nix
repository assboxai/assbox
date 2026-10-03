# SPDX-License-Identifier: GPL-3.0-or-later
{
  config,
  lib,
  pkgs,
  assboxPackage,
  ...
}:
let
  cfg = config.assbox;
in
{
  options.assbox.workerBootPolicy = lib.mkOption {
    type = lib.types.attrs;
    internal = true;
    default = {
      schema = 1;
      enabled = false;
    };
    description = "Immutable worker boot acceptance receipt for the running generation.";
  };
  config = lib.mkIf cfg.enable {
    system.systemBuilderCommands =
      let
        receipt = pkgs.writeText "assbox-worker-policy.json" (builtins.toJSON cfg.workerBootPolicy);
      in
      ''
        ln -s ${receipt} "$out/assbox-worker-policy.json"
      '';
    assertions = [
      {
        assertion = builtins.elem pkgs.stdenv.hostPlatform.system [
          "x86_64-linux"
          "aarch64-linux"
        ];
        message = "Assbox supports x86-64 PCs and generic AArch64 UEFI machines.";
      }
    ];
    nixpkgs.config.allowUnfree = cfg.acceptUnfree;
    # Redistributable device firmware is allowed independently of proprietary apps.
    nixpkgs.config.allowUnfreePredicate =
      package:
      builtins.elem lib.licenses.unfreeRedistributableFirmware (lib.toList (package.meta.license or [ ]));
    hardware.enableRedistributableFirmware = lib.mkDefault true;
    environment.systemPackages =
      with pkgs;
      [
        assboxPackage
        bash
        coreutils
        findutils
        gnugrep
        gnused
        gawk
        curl
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
        pciutils
        usbutils
        bind
        htop
        tmux
        nano
        nixos-rebuild
        rsync
        openssh
      ]
      ++ lib.optionals (!cfg.controller.active) (
        with pkgs;
        [
          just
          perl
          python3
          git
          nixfmt
        ]
      );
    environment.variables.EDITOR = lib.mkDefault cfg.editor.default;
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
    # Assbox journals explicit generation retention before ordinary store GC.
    # Do not run a competing NixOS garbage-collection timer.
    nix.gc.automatic = false;
    users.mutableUsers = false;
    users.users.root.hashedPassword = "!";
    users.users.agent = {
      uid = 1000;
      isNormalUser = true;
      home = "/home/agent";
      homeMode = "0700";
      hashedPassword = "!";
      linger = true;
      extraGroups = [ ];
    };
    users.users.admin = {
      uid = 1001;
      isNormalUser = true;
      extraGroups = [ "wheel" ];
      hashedPasswordFile = "/var/lib/assbox-secrets/admin-password.hash";
    };
    security.sudo.wheelNeedsPassword = true;
    security.sudo.execWheelOnly = true;
    security.polkit.enable = true;
    security.polkit.extraConfig = ''
      polkit.addRule(function(action, subject) {
        if (subject.user == "agent") return polkit.Result.NO;
      });
    '';
    networking.networkmanager.enable = true;
    networking.firewall.enable = true;
    services.timesyncd.enable = lib.mkDefault true;
    services.dbus.enable = true;
    services.udisks2.enable = false;
    services.gvfs.enable = false;
    services.avahi = {
      enable = cfg.network.discoverable;
      nssmdns4 = cfg.network.discoverable;
      publish = {
        enable = cfg.network.discoverable;
        addresses = cfg.network.discoverable;
      };
    };
    systemd.tmpfiles.rules = [
      "d /var/lib/assbox 0700 root root -"
      "d /var/lib/assbox-secrets 0700 root root -"
    ];
    environment.etc."assbox/runtime.json".text = builtins.toJSON {
      inherit (cfg)
        selectedComponents
        instance
        presentation
        platform
        updates
        ;
      controller = cfg.controller;
      boot = cfg.boot;
      session = { inherit (cfg.session) autostart; };
    };
  };
}
