# SPDX-License-Identifier: GPL-3.0-or-later
{
  pkgs,
  tools,
  nixpkgs,
  sourceRevision,
  releasePolicy,
}:
let
  check = pkgs.mkShell {
    packages =
      tools.packages
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
        wrangler
        openssl
        cargo-llvm-cov
        cargo-audit
        vulnix
      ]);
    ASSBOX_NIX_LIB = "${nixpkgs}/lib";
    GI_TYPELIB_PATH = pkgs.lib.makeSearchPath "lib/girepository-1.0" [
      pkgs.networkmanager
      pkgs.glib
    ];
    ASSBOX_TOOL_PATH = tools.path;
    ASSBOX_SOURCE_REVISION = sourceRevision;
    ASSBOX_REPOSITORY_ID = toString releasePolicy.repositoryId;
    ASSBOX_OWNER_ID = toString releasePolicy.ownerId;
    ASSBOX_CA_BUNDLE = "${pkgs.cacert}/etc/ssl/certs/ca-bundle.crt";
    RUST_SRC_PATH = "${pkgs.rustPlatform.rustLibSrc}";
    # Nix's Rust compiler has no rustup llvm-tools-preview component.
    # Coverage profiles must be read by its matching LLVM toolchain.
    LLVM_COV = "${pkgs.rustc.llvmPackages.llvm}/bin/llvm-cov";
    LLVM_PROFDATA = "${pkgs.rustc.llvmPackages.llvm}/bin/llvm-profdata";
  };
in
{
  release-check = check;
  release-tools = pkgs.mkShell {
    packages = with pkgs; [
      python3
      nix
      git
      jq
      curl
      gnupg
      gnutar
      gzip
    ];
  };
}
