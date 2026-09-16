# SPDX-License-Identifier: GPL-3.0-or-later
{
  description = "Assbox — a NixOS assistant appliance substrate";
  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-26.05";
    chatgpt-packages.url = "github:numtide/llm-agents.nix";
    opencode-packages.url = "github:numtide/llm-agents.nix";
    openclaw-packages.url = "github:numtide/llm-agents.nix";
  };
  outputs = { self, nixpkgs, chatgpt-packages, opencode-packages, openclaw-packages, ... }:
    let
      systems = [ "x86_64-linux" "aarch64-linux" ];
      eachSystem = nixpkgs.lib.genAttrs systems;
      releasePolicy = builtins.fromJSON (builtins.readFile ./release/policy.json);
      releaseContext = if builtins.pathExists ./release-context.json
        then builtins.fromJSON (builtins.readFile ./release-context.json) else null;
      sourceRevision = if releaseContext != null then releaseContext.coreCommit else self.rev or "";
      # Resolve packages from the consuming machine's architecture, never from a
      # developer's workstation or a captured x86-only package set.
      module = { pkgs, ... }: {
        imports = [ ./modules ];
        _module.args.assboxPackage = self.packages.${pkgs.stdenv.hostPlatform.system}.assbox;
        _module.args.assboxApplications = {
          chatgpt = chatgpt-packages.packages.${pkgs.stdenv.hostPlatform.system};
          opencode = opencode-packages.packages.${pkgs.stdenv.hostPlatform.system};
          openclaw = openclaw-packages.packages.${pkgs.stdenv.hostPlatform.system};
        };
      };
      platform = eachSystem (system:
        let
          pkgs = import nixpkgs { inherit system; };
          tools = import ./nix/tool-environment.nix { inherit pkgs; };
          assbox = pkgs.callPackage ./nix/package.nix { inherit pkgs sourceRevision releasePolicy; };
          fixture = args: nixpkgs.lib.nixosSystem {
            inherit system;
            modules = [ module ./tests/nix/fixture.nix args ];
          };
          matrix = import ./tests/nix/matrix.nix { inherit fixture pkgs; };
        in { inherit pkgs tools assbox matrix; });
    in
    {
      nixosModules.default = module;
      packages = eachSystem (system: let p = platform.${system}; in { inherit (p) assbox; default = p.assbox; });
      # Exposed data for trusted release jobs; no source mutation is required.
      assboxReleasePolicy = releasePolicy;
      formatter = eachSystem (system: platform.${system}.pkgs.nixfmt);
      devShells = eachSystem (system:
        let p = platform.${system}; in {
          default = p.pkgs.mkShell {
            packages = p.tools.packages ++ (with p.pkgs; [
              cargo rustc rustfmt clippy (python3.withPackages (ps: [ ps.pyyaml ])) shellcheck actionlint
              just nodejs wrangler openssl cargo-llvm-cov cargo-audit vulnix
            ]);
            ASSBOX_TOOL_PATH = p.tools.path;
            ASSBOX_SOURCE_REVISION = sourceRevision;
            ASSBOX_REPOSITORY_ID = toString releasePolicy.repositoryId;
            ASSBOX_OWNER_ID = toString releasePolicy.ownerId;
            ASSBOX_CA_BUNDLE = "${p.pkgs.cacert}/etc/ssl/certs/ca-bundle.crt";
            RUST_SRC_PATH = "${p.pkgs.rustPlatform.rustLibSrc}";
          };
        });
      nixosConfigurations = nixpkgs.lib.foldl' (all: system:
        all // platform.${system}.matrix.configurations) { } systems;
      checks = eachSystem (system:
        let p = platform.${system}; in p.matrix.checks // {
          workspace = p.assbox;
          policy-vm = import ./tests/nix/policy-vm.nix { inherit module; inherit (p) pkgs; };
          management-vm = import ./tests/nix/management-vm.nix { inherit module; inherit (p) pkgs; };
        });
    };
}
