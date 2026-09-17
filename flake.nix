# SPDX-License-Identifier: GPL-3.0-or-later
{
  description = "Assbox — a NixOS assistant appliance substrate";
  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-26.05";
    antigravity-packages.url = "github:numtide/llm-agents.nix";
    chatgpt-packages.url = "github:numtide/llm-agents.nix";
    claude-code-packages.url = "github:numtide/llm-agents.nix";
    claude-desktop-packages.url = "github:numtide/llm-agents.nix";
    codex-packages.url = "github:numtide/llm-agents.nix";
    cursor-packages.url = "github:numtide/llm-agents.nix";
    gemini-cli-packages.url = "github:numtide/llm-agents.nix";
    grok-packages.url = "github:numtide/llm-agents.nix";
    happy-packages.url = "github:numtide/llm-agents.nix";
    openclaw-packages.url = "github:numtide/llm-agents.nix";
    opencode-packages.url = "github:numtide/llm-agents.nix";
  };
  outputs =
    {
      self,
      nixpkgs,
      antigravity-packages,
      chatgpt-packages,
      claude-code-packages,
      claude-desktop-packages,
      codex-packages,
      cursor-packages,
      gemini-cli-packages,
      grok-packages,
      happy-packages,
      openclaw-packages,
      opencode-packages,
      ...
    }:
    let
      systems = [
        "x86_64-linux"
        "aarch64-linux"
      ];
      eachSystem = nixpkgs.lib.genAttrs systems;
      releasePolicy = builtins.fromJSON (builtins.readFile ./release/policy.json);
      releaseContext =
        if builtins.pathExists ./release-context.json then
          builtins.fromJSON (builtins.readFile ./release-context.json)
        else
          null;
      sourceRevision = if releaseContext != null then releaseContext.coreCommit else self.rev or "";
      # Resolve packages from the consuming machine's architecture, never from a
      # developer's workstation or a captured x86-only package set.
      module = { pkgs, ... }: {
        imports = [ ./modules ];
        _module.args.assboxPackage = self.packages.${pkgs.stdenv.hostPlatform.system}.assbox;
        _module.args.assboxApplications = {
          antigravity = antigravity-packages.packages.${pkgs.stdenv.hostPlatform.system};
          chatgpt = chatgpt-packages.packages.${pkgs.stdenv.hostPlatform.system};
          claude-code = claude-code-packages.packages.${pkgs.stdenv.hostPlatform.system};
          claude-desktop = claude-desktop-packages.packages.${pkgs.stdenv.hostPlatform.system};
          codex = codex-packages.packages.${pkgs.stdenv.hostPlatform.system};
          cursor = cursor-packages.packages.${pkgs.stdenv.hostPlatform.system};
          gemini-cli = gemini-cli-packages.packages.${pkgs.stdenv.hostPlatform.system};
          grok = grok-packages.packages.${pkgs.stdenv.hostPlatform.system};
          happy = happy-packages.packages.${pkgs.stdenv.hostPlatform.system};
          openclaw = openclaw-packages.packages.${pkgs.stdenv.hostPlatform.system};
          opencode = opencode-packages.packages.${pkgs.stdenv.hostPlatform.system};

        };
      };
      platform = eachSystem (
        system:
        let
          pkgs = import nixpkgs { inherit system; };
          tools = import ./nix/tool-environment.nix { inherit pkgs; };
          assbox = pkgs.callPackage ./nix/package.nix { inherit pkgs sourceRevision releasePolicy; };
          fixture =
            args:
            nixpkgs.lib.nixosSystem {
              inherit system;
              modules = [
                module
                ./tests/nix/fixture.nix
                args
              ];
            };
          matrix = import ./tests/nix/matrix.nix { inherit fixture pkgs; };
        in
        {
          inherit
            pkgs
            tools
            assbox
            matrix
            ;
        }
      );
    in
    {
      nixosModules.default = module;
      packages = eachSystem (
        system:
        let
          p = platform.${system};
        in
        {
          inherit (p) assbox;
          default = p.assbox;
        }
      );
      # Exposed data for trusted release jobs; no source mutation is required.
      assboxReleasePolicy = releasePolicy;
      formatter = eachSystem (system: platform.${system}.pkgs.nixfmt);
      devShells = eachSystem (
        system:
        let
          p = platform.${system};
        in
        {
          default = p.pkgs.mkShell {
            packages =
              p.tools.packages
              ++ (with p.pkgs; [
                cargo
                rustc
                rustfmt
                clippy
                (python3.withPackages (ps: [
                  ps.pyyaml
                  ps.pygobject3
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
            GI_TYPELIB_PATH = p.pkgs.lib.makeSearchPath "lib/girepository-1.0" [
              p.pkgs.networkmanager
              p.pkgs.glib
            ];
            ASSBOX_TOOL_PATH = p.tools.path;
            ASSBOX_SOURCE_REVISION = sourceRevision;
            ASSBOX_REPOSITORY_ID = toString releasePolicy.repositoryId;
            ASSBOX_OWNER_ID = toString releasePolicy.ownerId;
            ASSBOX_CA_BUNDLE = "${p.pkgs.cacert}/etc/ssl/certs/ca-bundle.crt";
            RUST_SRC_PATH = "${p.pkgs.rustPlatform.rustLibSrc}";
          };
        }
      );
      nixosConfigurations = nixpkgs.lib.foldl' (
        all: system: all // platform.${system}.matrix.configurations
      ) { } systems;
      checks = eachSystem (
        system:
        let
          p = platform.${system};
        in
        p.matrix.checks
        //
          nixpkgs.lib.genAttrs
            (map (family: "application-${family}-vm") [
              "antigravity"
              "claude-code"
              "claude-desktop"
              "codex"
              "cursor"
              "gemini-cli"
              "grok"
              "happy"
            ])
            (
              name:
              import ./tests/nix/component-family-vm.nix {
                inherit module;
                inherit (p) pkgs;
                family = nixpkgs.lib.removeSuffix "-vm" (nixpkgs.lib.removePrefix "application-" name);
              }
            )
        // {
          workspace = p.assbox;
          remote-lifecycle-vm = import ./tests/nix/remote-lifecycle-vm.nix {
            inherit (p) pkgs assbox;
          };
          editor-vm = import ./tests/nix/editor-vm.nix {
            inherit module;
            inherit (p) pkgs;
          };
          access-lan-vm = import ./tests/nix/access-vm.nix {
            inherit module;
            inherit (p) pkgs;
            exposure = "lan";
          };
          access-tailscale-vm = import ./tests/nix/access-vm.nix {
            inherit module;
            inherit (p) pkgs;
            exposure = "tailscale";
          };
          policy-vm = import ./tests/nix/policy-vm.nix {
            inherit module;
            inherit (p) pkgs;
          };
          management-vm = import ./tests/nix/management-vm.nix {
            inherit module;
            inherit (p) pkgs;
          };
          resources-vm = import ./tests/nix/resources-vm.nix {
            inherit module;
            inherit (p) pkgs;
          };
          install-boot-vm = import ./tests/nix/install-boot-vm.nix {
            inherit module;
            inherit (p) pkgs assbox;
            inputs = {
              inherit
                nixpkgs
                antigravity-packages
                chatgpt-packages
                claude-code-packages
                claude-desktop-packages
                codex-packages
                cursor-packages
                gemini-cli-packages
                grok-packages
                happy-packages
                openclaw-packages
                opencode-packages
                ;
            };
          };
          activation-recovery-vm = import ./tests/nix/activation-recovery-vm.nix {
            inherit module;
            inherit (p) pkgs assbox;
            inputs = {
              inherit
                nixpkgs
                antigravity-packages
                chatgpt-packages
                claude-code-packages
                claude-desktop-packages
                codex-packages
                cursor-packages
                gemini-cli-packages
                grok-packages
                happy-packages
                openclaw-packages
                opencode-packages
                ;
            };
          };
          authenticated-release-vm = import ./tests/nix/authenticated-release-vm.nix {
            inherit (p) pkgs assbox;
          };
          application-chatgpt-vm = import ./tests/nix/application-vm.nix {
            inherit module;
            inherit (p) pkgs;
            application = "chatgpt";
          };
          application-opencode-vm = import ./tests/nix/application-vm.nix {
            inherit module;
            inherit (p) pkgs;
            application = "opencode";
          };
          application-openclaw-vm = import ./tests/nix/application-vm.nix {
            inherit module;
            inherit (p) pkgs;
            application = "openclaw";
          };
        }
      );
    };
}
