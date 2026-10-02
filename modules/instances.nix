# SPDX-License-Identifier: GPL-3.0-or-later
{ config, lib, ... }:
let
  cfg = config.assbox;
  catalog = builtins.fromJSON (builtins.readFile ../catalog/presets.json);
  ids = map (p: p.id) catalog;
in
{
  options.assbox.instance = {
    purpose = lib.mkOption {
      type = lib.types.enum [
        "assistant"
        "coder"
        "kiosk"
        "custom"
      ];
      default = "custom";
      description = "Informational instance purpose; concrete settings enforce policy.";
    };
    preset = lib.mkOption {
      type = lib.types.enum ids;
      default = "custom";
    };
    revision = lib.mkOption {
      type = lib.types.ints.positive;
      default = 1;
    };
    exclusions = lib.mkOption {
      type = lib.types.listOf lib.types.str;
      default = [ ];
      description = "Explicit deselections; defaults are never expanded again at activation.";
    };
  };
  config = lib.mkIf cfg.enable {
    assertions = [
      {
        assertion = builtins.any (
          p: p.id == cfg.instance.preset && p.purpose == cfg.instance.purpose
        ) catalog;
        message = "Instance purpose and preset provenance disagree.";
      }
      {
        assertion = builtins.all (
          id: !(builtins.elem id cfg.selectedComponents) && !(builtins.elem id cfg.worker.components)
        ) cfg.instance.exclusions;
        message = "Explicitly excluded components must not be selected on host or worker.";
      }
    ];
    environment.etc."assbox/presets.json".source = ../catalog/presets.json;
  };
}
