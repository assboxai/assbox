# SPDX-License-Identifier: GPL-3.0-or-later
# A deliberate selection, not a default bundle. Replace the physical uplink.
{ lib, ... }:
{
  assbox.presentation = "x11";
  assbox.acceptUnfree = true;
  assbox.components.chatgpt-desktop = {
    enable = true;
    allowMutableCode = true;
  };
  assbox.components.chatgpt-remote.enable = true;
  assbox.session.autostart = [ "chatgpt-desktop" ];
  # Clear these entries only when migrating a managed host selection.
  assbox.components.codex.enable = lib.mkForce false;
  assbox.components.claude-code.enable = lib.mkForce false;
  assbox.components.grok.enable = lib.mkForce false;
  assbox.components.antigravity-cli.enable = lib.mkForce false;
  assbox.components.cursor-agent.enable = lib.mkForce false;
  assbox.components.opencode.enable = lib.mkForce false;
  assbox.components.gemini-cli.enable = lib.mkForce false;
  assbox.worker = {
    enable = true;
    components = [
      "codex"
      "claude-code"
      "grok"
      "antigravity-cli"
      "cursor-agent"
      "opencode"
      "gemini-cli"
    ];
    memoryMiB = 6144;
    vcpus = 2;
    stateGiB = 32;
    uplinkInterfaces = [ "enp3s0" ]; # Replace: never assume this exists.
    extraGuestConfig = { pkgs, ... }: {
      environment.systemPackages = [
        pkgs.gcc
        pkgs.gnumake
        pkgs.nodejs
        pkgs.cargo
      ];
    };
  };
}
