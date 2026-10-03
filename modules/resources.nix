# SPDX-License-Identifier: GPL-3.0-or-later
{ config, lib, ... }:
let
  cfg = config.assbox;
  ids = [
    "chatgpt-desktop"
    "claude-desktop"
    "happier-daemon"
    "hermes-gateway"
    "hermes-dashboard"
    "codex-relay"
    "antigravity-remote"
    "claude-code-remote"
    "cursor-worker"
    "openclaw-node"
    "vscode-tunnel"
    "openclaw-gateway"
    "opencode-server"
  ];
  unitFor =
    id:
    if
      builtins.elem id [
        "chatgpt-desktop"
        "claude-desktop"
      ]
    then
      id
    else if id == "openclaw-gateway" then
      "assbox-openclaw"
    else if id == "opencode-server" then
      "assbox-opencode"
    else
      "assbox-${id}";
  units =
    map unitFor (
      builtins.filter (
        id:
        cfg.components.${id}.enable
        && (
          !(builtins.elem id [
            "antigravity-remote"
            "codex-relay"
          ])
          || cfg.components.${id}.foregroundCommand != [ ]
        )
      ) ids
    )
    ++ map (id: "assbox-${id}") (
      builtins.filter (id: builtins.elem id cfg.session.autostart) [
        "chromium"
        "vscode"
        "zed"
        "emacs"
      ]
    )
    ++ map (site: "assbox-web-${site}") (cfg.kiosk.webApps or [ ]);
in
{
  options.assbox.resources = {
    agentMemoryMaxMiB = lib.mkOption {
      type = lib.types.ints.between 512 65536;
      default = 4096;
      description = "Maximum memory for each managed agent service and its children, not a RAM reservation.";
    };
    agentCPUWeight = lib.mkOption {
      type = lib.types.ints.between 1 10000;
      default = 100;
    };
  };
  config = lib.mkIf config.assbox.enable {
    # Compress cold anonymous pages in RAM. These are the standard NixOS zram
    # defaults: zstd, a logical size of 50% of RAM, allocated only as used.
    zramSwap.enable = lib.mkDefault true;
    systemd.user.services = lib.genAttrs units (_: {
      serviceConfig = {
        MemoryMax = lib.mkDefault "${toString cfg.resources.agentMemoryMaxMiB}M";
        CPUWeight = cfg.resources.agentCPUWeight;
        CPUAccounting = true;
        MemoryAccounting = true;
        IOAccounting = true;
      };
    });

    # A root slice competes with system.slice and user.slice. Weights matter only
    # under contention; idle CPUs and available I/O remain fully usable by Nix.
    systemd.slices.assbox = {
      description = "Assbox background builds and maintenance";
      sliceConfig = {
        CPUWeight = 20;
        IOWeight = 20;
        CPUAccounting = true;
        IOAccounting = true;
        MemoryAccounting = true;
      };
    };
    # Build workers are children of the daemon, not of the client that asks Nix
    # for a build, so the daemon must share the background slice.
    systemd.services.nix-daemon.serviceConfig = {
      Slice = "assbox.slice";
      CPUAccounting = true;
      IOAccounting = true;
      MemoryAccounting = true;
    };
  };
}
