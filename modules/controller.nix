# SPDX-License-Identifier: GPL-3.0-or-later
{ config, lib, ... }:
let
  cfg = config.assbox;
  catalog = builtins.fromJSON (builtins.readFile ../catalog/components.json);
  selected = builtins.filter (row: cfg.components.${row.id}.enable) catalog;
  sensitive = builtins.any (row: row.requiresWorker) selected;
  chatgpt = cfg.components.chatgpt-desktop.enable;
  active = cfg.worker.enable || sensitive;
in
{
  config = lib.mkIf cfg.enable {
    assbox.controller = {
      inherit active;
      profile =
        if chatgpt then
          "chatgpt-desktop"
        else if sensitive then
          "unqualified"
        else if active then
          "generic"
        else
          "none";
    };
    assertions = [
      {
        assertion = !sensitive || cfg.worker.enable;
        message = "Sensitive controller components require an isolated worker; controller execution is not a supported fallback.";
      }
      {
        assertion = !active || builtins.all (row: row.controllerAllowed) selected;
        message = "Move execution components and unqualified controller integrations off the thin controller. Only reviewed controller components are supported here.";
      }
      {
        assertion = !chatgpt || builtins.elem "codex" cfg.worker.components;
        message = "ChatGPT Desktop requires explicit selection of Codex in assbox.worker.components.";
      }
    ];
    # Administrative builds still use the management engine's private tool PATH.
    # This is not a claim that Desktop cannot download its own executable code.
    nix.settings.allowed-users = lib.mkIf active [ "root" ];
  };
}
