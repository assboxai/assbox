# SPDX-License-Identifier: GPL-3.0-or-later
# Exercise the audit's license boundary with real nixpkgs, without a NixOS build.
{ libPath }:
let
  lib = import libPath;
  packages =
    allowUnfree:
    import (libPath + "/..") {
      system = builtins.currentSystem;
      config = { inherit allowUnfree; };
      overlays = [
        (_: previous: {
          vscode = previous.vscode.overrideAttrs (old: {
            postInstall = (old.postInstall or "") + "\n# identity regression overlay\n";
          });
        })
      ];
    };
  machine = lib.evalModules {
    modules = [
      ({ config, ... }: {
        options = {
          nixpkgs.config.allowUnfree = lib.mkOption {
            type = lib.types.bool;
            default = false;
          };
          assbox = lib.mkOption { type = lib.types.attrs; };
          system.build.toplevel = lib.mkOption { type = lib.types.str; };
        };
        config = {
          assbox = {
            selectedComponents = [ "vim" ];
            componentPackagePaths = {
              vscode = [
                (toString (import ../../nix/vscode-gui.nix { pkgs = packages config.nixpkgs.config.allowUnfree; }))
              ];
              vim = [ "/nix/store/selected-vim" ];
            };
          };
          system.build.toplevel =
            assert !config.nixpkgs.config.allowUnfree;
            "/nix/store/original-system";
        };
      })
    ];
  };
  expected = toString (import ../../nix/vscode-gui.nix { pkgs = packages true; });
  audit = import ./component-closure.nix {
    inherit machine;
    name = "license-regression";
    pkgs = {
      inherit lib;
      python3 = "/nix/store/python";
      closureInfo =
        args:
        assert args.rootPaths == [ "/nix/store/original-system" ];
        "/nix/store/closure";
      writeText =
        _: text:
        assert builtins.fromJSON text == { vscode = [ expected ]; };
        "/nix/store/identities";
      runCommand =
        _: _: script:
        script;
    };
  };
in
assert !machine.config.nixpkgs.config.allowUnfree;
assert
  !(builtins.tryEval (builtins.head machine.config.assbox.componentPackagePaths.vscode)).success;
assert lib.hasInfix "/nix/store/closure/store-paths /nix/store/identities" audit;
true
