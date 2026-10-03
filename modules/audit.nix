# SPDX-License-Identifier: GPL-3.0-or-later
{ config, lib, ... }:
let
  cfg = config.assbox;
  locked =
    user:
    user.enable
    && user.hashedPassword == "!"
    && user.hashedPasswordFile == null
    && user.password == null
    && user.initialPassword == null
    && user.initialHashedPassword == null
    && !config.users.mutableUsers;
  agent = config.users.users.agent;
  agentGroups = lib.unique (
    [ agent.group ]
    ++ agent.extraGroups
    ++ lib.attrNames (
      lib.filterAttrs (_: group: builtins.elem "agent" group.members) config.users.groups
    )
  );
  # A conservative check, not a general sudoers theorem prover.
  noPasswordCommand =
    command: builtins.isAttrs command && builtins.elem "NOPASSWD" (command.options or [ ]);
  extraSudo = builtins.any (
    rule: builtins.elem "agent" rule.users || builtins.any noPasswordCommand rule.commands
  ) config.security.sudo.extraRules;
in
{
  config = lib.mkIf cfg.enable {
    assbox.audit = {
      enabled = cfg.enable;
      inherit (cfg) selectedComponents presentation;
      boot = cfg.boot.mode;
      firewall = config.networking.firewall.enable;
      rootLocked = locked config.users.users.root;
      agentLocked = locked agent && agent.uid != 0;
      inherit agentGroups;
      trustedUsers = config.nix.settings.trusted-users;
      sandbox = config.nix.settings.sandbox == true;
      requireSignatures = config.nix.settings.require-sigs;
      acceptFlakeConfig = config.nix.settings.accept-flake-config;
      automount = config.services.udisks2.enable || config.services.gvfs.enable;
      passwordlessSudo =
        !config.security.sudo.wheelNeedsPassword
        || extraSudo
        || lib.hasInfix "NOPASSWD" config.security.sudo.extraConfig
        || lib.hasInfix "agent" config.security.sudo.extraConfig;
      efiWrites = config.boot.loader.efi.canTouchEfiVariables;
    };
  };
}
