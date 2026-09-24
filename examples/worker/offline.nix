# SPDX-License-Identifier: GPL-3.0-or-later
# A network-isolation test profile, not a way to use cloud Codex while offline.
{ ... }:
{
  assbox.worker = {
    enable = true;
    components = [ "vim" ];
    egress = "offline";
    uplinkInterfaces = [ ];
    nameservers = [ ];
  };
}
