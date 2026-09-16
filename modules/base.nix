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
  config = lib.mkIf cfg.enable {
    assertions = [
      {
        assertion = builtins.elem pkgs.stdenv.hostPlatform.system [
          "x86_64-linux"
          "aarch64-linux"
        ];
        message = "Assbox supports x86-64 PCs and generic AArch64 UEFI machines.";
      }
      {
        assertion = cfg.application != "chatgpt" || cfg.presentation == "x11";
        message = "ChatGPT requires the X11 presentation.";
      }
      {
        assertion = cfg.application != "chatgpt" || cfg.acceptUnfree;
        message = "ChatGPT requires explicit assbox.acceptUnfree consent.";
      }
    ];
    nixpkgs.config.allowUnfree = cfg.acceptUnfree;
    # Redistributable device firmware is allowed independently of proprietary apps.
    nixpkgs.config.allowUnfreePredicate =
      package:
      builtins.elem lib.licenses.unfreeRedistributableFirmware (lib.toList (package.meta.license or [ ]));
    hardware.enableRedistributableFirmware = lib.mkDefault true;
    environment.systemPackages = with pkgs; [
      assboxPackage
      just
      bash
      coreutils
      findutils
      gnugrep
      gnused
      gawk
      perl
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
      pciutils
      usbutils
      bind
      htop
      tmux
      nano
      nixfmt
      nixos-rebuild
      rsync
      openssh
    ];
    environment.variables.EDITOR = lib.mkDefault "nano";
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
      isNormalUser = true;
      home = "/home/agent";
      homeMode = "0700";
      hashedPassword = "!";
      linger = true;
      extraGroups = [ ];
    };
    users.users.admin = {
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
    networking.firewall.allowedTCPPorts = lib.optionals cfg.network.ssh.enable [ 22 ];
    services.dbus.enable = true;
    services.openssh = {
      enable = cfg.network.ssh.enable;
      openFirewall = cfg.network.ssh.enable;
      settings = {
        PasswordAuthentication = false;
        KbdInteractiveAuthentication = false;
        PermitRootLogin = "no";
        AllowUsers = [ "admin" ];
      };
    };
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
        application
        presentation
        platform
        updates
        ;
      boot = cfg.boot;
    };
  };
}
