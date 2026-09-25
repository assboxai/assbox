# SPDX-License-Identifier: GPL-3.0-or-later
{
  pkgs,
  machine,
  name,
}:
let
  cfg = machine.config.assbox;
  # Enumerating an excluded package must not require consent to install it.
  # Extend only the audit view so identities retain this machine's overlays and
  # package variants. The closure below still uses the original license policy.
  identities =
    (machine.extendModules {
      modules = [
        ({ lib, ... }: { nixpkgs.config.allowUnfree = lib.mkForce true; })
      ];
    }).config.assbox.componentPackagePaths;
  closure = pkgs.closureInfo { rootPaths = [ machine.config.system.build.toplevel ]; };
  forbidden = pkgs.writeText "assbox-unselected-identities.json" (
    builtins.toJSON (
      pkgs.lib.mapAttrs (_: paths: map builtins.unsafeDiscardStringContext paths) (
        pkgs.lib.filterAttrs (
          id: _: !(builtins.elem id (cfg.selectedComponents ++ cfg.componentRuntimeDependencies))
        ) identities
      )
    )
  );
in
pkgs.runCommand "assbox-closure-${name}" { nativeBuildInputs = [ pkgs.python3 ]; } ''
  python3 - ${closure}/store-paths ${forbidden} > "$out" <<'PY'
  import json, sys
  paths = set(open(sys.argv[1]).read().splitlines())
  forbidden = json.load(open(sys.argv[2]))
  leaked = sorted(id for id, identities in forbidden.items() if any(path in paths for path in identities))
  if leaked:
      raise SystemExit("Unselected curated runtime in system closure: " + ", ".join(leaked))
  print("Known standalone package identities absent; bundled/mutable code needs the documented separate inventory.")
  PY
''
