# SPDX-License-Identifier: GPL-3.0-or-later
{
  config,
  lib,
  pkgs,
  assboxApplications,
  ...
}:
let
  cfg = config.assbox;
  catalog = builtins.fromJSON (builtins.readFile ../catalog/components.json);
  selected = builtins.filter (row: cfg.components.${row.id}.enable) catalog;
  enabled = id: cfg.components.${id}.enable;
  owners = {
    opencode-attach = "opencode-server";
    openclaw-dashboard = "openclaw-gateway";
  };
  licenseFree =
    license:
    if builtins.isList license then
      builtins.all licenseFree license
    else if builtins.isAttrs license && license ? licenseType then
      lib.licenses.isFree license
    else
      builtins.isAttrs license && (license.free or false);
  rawPackage =
    row:
    if row.id == "vscode-cli" then
      pkgs.callPackage ../nix/vscode-cli.nix { }
    else if row.family == "nixpkgs" then
      pkgs.${row.package}
    else
      assboxApplications.${row.family}.${row.package};
  packageFor =
    row:
    if row.id == "chatgpt-desktop" then
      assboxApplications.chatgpt.chatgpt.override {
        commandLineArgs = "--ozone-platform=x11 --password-store=basic --force-device-scale-factor=${toString cfg.display.scale}";
      }
    else if row.id == "grok" then
      pkgs.runCommand "assbox-grok-command" { } ''
        mkdir -p "$out/bin"
        ln -s ${assboxApplications.grok.grok}/bin/grok "$out/bin/grok"
      ''
    else if row.id == "vscode-cli" then
      pkgs.callPackage ../nix/vscode-cli.nix { }
    else if row.id == "emacs" && cfg.components.emacs.variant == "gui" then
      pkgs.emacs
    else if row.family == "nixpkgs" then
      pkgs.${row.package}
    else
      assboxApplications.${row.family}.${row.package};
in
{
  options.assbox.componentPackagePaths = lib.mkOption {
    type = lib.types.attrsOf (lib.types.listOf lib.types.str);
    internal = true;
    readOnly = true;
    description = "Known curated package identities for closure verification; never installed implicitly.";
  };
  options.assbox.components = lib.listToAttrs (
    map (
      row:
      lib.nameValuePair row.id {
        enable = lib.mkEnableOption "the ${row.id} component";
        allowMutableCode = lib.mkOption {
          type = lib.types.bool;
          default = false;
          description = "Acknowledge this component's provider/client-managed executable downloads. This is consent, not a sandbox.";
        };
      }
    ) catalog
  );
  config = lib.mkIf cfg.enable {
    assbox.componentPackagePaths = lib.listToAttrs (
      map (
        row:
        let
          raw = rawPackage row;
        in
        lib.nameValuePair row.id (
          lib.unique (
            [
              (toString (packageFor row))
              (toString raw)
            ]
            ++ lib.optional (raw ? unwrapped) (toString raw.unwrapped)
          )
        )
      ) (builtins.filter (row: row.package != "") catalog)
    );
    assbox.selectedComponents = map (row: row.id) selected;
    assertions =
      lib.concatMap (
        row:
        [
          {
            assertion = row.blocked == "";
            message = "${row.id}: ${row.blocked}";
          }
          {
            assertion = builtins.elem cfg.presentation row.presentations;
            message = "${row.id} is incompatible with ${cfg.presentation}.";
          }
          {
            assertion = !row.unfree || cfg.acceptUnfree;
            message = "${row.id} requires explicit assbox.acceptUnfree consent.";
          }
          {
            assertion =
              row.package == "" || cfg.acceptUnfree || licenseFree ((rawPackage row).meta.license or { });
            message = "${row.id} has proprietary or unknown package license metadata; explicit consent is required even for external flakes.";
          }
          {
            assertion = !row.mutableCode || cfg.components.${row.id}.allowMutableCode;
            message = "${row.id} requires explicit allowMutableCode consent; review its provisioning authority.";
          }
        ]
        ++ map (dep: {
          assertion = enabled dep;
          message = "${row.id} requires explicit selection of ${dep}.";
        }) row.dependencies
      ) selected
      ++ map (launcher: {
        assertion = cfg.presentation != "headless" && enabled (owners.${launcher} or launcher);
        message = "Autostart ${launcher} requires its component and a graphical presentation.";
      }) cfg.session.autostart
      ++ [
        {
          assertion = cfg.editor.default == "nano" || enabled cfg.editor.default;
          message = "The default editor must be explicitly installed.";
        }
        {
          assertion =
            builtins.length cfg.session.autostart == builtins.length (lib.unique cfg.session.autostart);
          message = "Duplicate graphical launcher.";
        }
      ];
    # ChatGPT's X11 wrapper is provided by applications.nix.
    environment.systemPackages =
      map packageFor (builtins.filter (row: row.package != "" && row.id != "chatgpt-desktop") selected)
      ++ lib.optionals (enabled "chatgpt-desktop" || enabled "claude-desktop") [ pkgs.chromium ];
    environment.etc."assbox/components.json".text = builtins.toJSON selected;
  };
}
