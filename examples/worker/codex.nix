# SPDX-License-Identifier: GPL-3.0-or-later
# Merge into /etc/nixos/local.nix on an already installed Assbox.
{ lib, ... }:
{
  assbox.presentation = "x11";
  assbox.acceptUnfree = true;
  assbox.components.chatgpt-desktop = {
    enable = true;
    allowMutableCode = true;
  };
  assbox.components.chatgpt-remote.enable = true;
  assbox.kiosk.localExecution = "managed-worker";
  # Desktop stays inactive until an exact native-policy contract is qualified.
  assbox.session.autostart = [ "chatgpt-desktop" ];
  # Override an installed host selection deliberately. Credentials are not moved.
  assbox.components.codex.enable = lib.mkForce false;
  assbox.worker = {
    enable = true;
    components = [ "codex" ];
    memoryMiB = 3072;
    vcpus = 2;
    stateGiB = 128; # Example only; the CLI defaults to automatic sizing.
    # Set to actual interface names shown by `ip -brief link` / `ip route`.
    egress = "normal"; # Explicit internet + LAN access; choose internet for public-only.
    uplinkInterfaces = [ "enp3s0" ];
    allowGuestSudo = false;
  };
}
