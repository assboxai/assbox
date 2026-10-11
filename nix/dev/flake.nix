# SPDX-License-Identifier: GPL-3.0-or-later
{
  description = "Independent Assbox developer tooling";
  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-26.05";
  outputs =
    { nixpkgs, ... }:
    let
      each = nixpkgs.lib.genAttrs [
        "x86_64-linux"
        "aarch64-linux"
      ];
    in
    {
      packages = each (
        system:
        let
          pkgs = import nixpkgs { inherit system; };
        in
        {
          inherit (pkgs) just;
        }
      );
      devShells = each (
        system:
        let
          pkgs = import nixpkgs { inherit system; };
          tools = import ./tools.nix { inherit pkgs; };
          common = {
            packages =
              tools
              ++ (with pkgs; [
                cargo
                rustc
                rustfmt
                clippy
                (python3.withPackages (ps: [
                  ps.pyyaml
                  ps.pygobject3
                  ps.jsonschema
                ]))
                shellcheck
                actionlint
                just
                nodejs
                openssl
                cargo-llvm-cov
                cargo-audit
                vulnix
              ]);
            ASSBOX_TOOL_PATH = pkgs.lib.makeBinPath tools;
            ASSBOX_NIX_LIB = "${nixpkgs}/lib";
            ASSBOX_SOURCE_REVISION = "";
            ASSBOX_REPOSITORY_ID = "0";
            ASSBOX_OWNER_ID = "0";
            ASSBOX_CA_BUNDLE = "${pkgs.cacert}/etc/ssl/certs/ca-bundle.crt";
            GI_TYPELIB_PATH = pkgs.lib.makeSearchPath "lib/girepository-1.0" [
              pkgs.networkmanager
              pkgs.glib
            ];
            RUST_SRC_PATH = "${pkgs.rustPlatform.rustLibSrc}";
            LLVM_COV = "${pkgs.rustc.llvmPackages.llvm}/bin/llvm-cov";
            LLVM_PROFDATA = "${pkgs.rustc.llvmPackages.llvm}/bin/llvm-profdata";
          };
        in
        {
          default = pkgs.mkShell common;
          formatter = pkgs.mkShell {
            packages = [
              pkgs.rustfmt
              pkgs.nixfmt
            ];
          };
          repair = pkgs.mkShell (
            common
            // {
              packages = common.packages ++ [
                pkgs.qemu
                pkgs.openssh
              ];
            }
          );
        }
      );
    };
}
