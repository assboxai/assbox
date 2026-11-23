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
    happier-packages.url = "github:numtide/llm-agents.nix";
    hermes-packages.url = "github:numtide/llm-agents.nix";
    pi-packages.url = "github:numtide/llm-agents.nix";
    omp-packages.url = "github:numtide/llm-agents.nix";
    grok-packages.url = "github:numtide/llm-agents.nix";
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
      happier-packages,
      hermes-packages,
      pi-packages,
      omp-packages,
      grok-packages,
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
      buildAssbox =
        pkgs: pkgs.callPackage ./nix/package.nix { inherit pkgs sourceRevision releasePolicy; };
      chatgptPackages =
        system:
        let
          recipes = chatgpt-packages.packages.${system};
          original = recipes.chatgpt;
          appPkgs = import chatgpt-packages.inputs.nixpkgs { inherit system; };
          cups = import ./nix/reviewed-cups.nix { pkgs = appPkgs; };
          pipewire = import ./nix/reviewed-pipewire.nix { pkgs = appPkgs; };
        in
        recipes
        // {
          chatgpt = original.override {
            chatgpt-unwrapped = original.unwrapped.override { inherit cups pipewire; };
          };
        };
      claudeDesktopPackages =
        system:
        let
          recipes = claude-desktop-packages.packages.${system};
          original = recipes.claude-desktop;
          appPkgs = import claude-desktop-packages.inputs.nixpkgs { inherit system; };
          cups = import ./nix/reviewed-cups.nix { pkgs = appPkgs; };
          pipewire = import ./nix/reviewed-pipewire.nix { pkgs = appPkgs; };
          gzipVersion = "1.15";
          gzip = appPkgs.gzip.overrideAttrs (old: {
            version = gzipVersion;
            src = appPkgs.fetchurl {
              url = "mirror://gnu/gzip/gzip-${gzipVersion}.tar.xz";
              hash = "sha256-mqDMeA3sFWuCgoRIM7NCq3ywjCXSzZoYac3Q3zHe/0g=";
            };
            # The release includes both fixes, including the second upstream
            # change for CVE-2026-41992.
            patches = builtins.filter (
              patch:
              !builtins.any (suffix: nixpkgs.lib.hasSuffix suffix (toString patch)) [
                "CVE-2026-41991.patch"
                "CVE-2026-41992.patch"
              ]
            ) (old.patches or [ ]);
          });
          # Pass the replacement only to the FHS root builder's package list.
          # A package-set overlay would also change vendored bootstrap inputs.
          buildFHSEnv = appPkgs.buildFHSEnv.override {
            callPackage =
              recipe: args:
              appPkgs.callPackage recipe (
                args
                // {
                  pkgs = appPkgs // {
                    inherit gzip;
                  };
                }
              );
          };
        in
        recipes
        // {
          claude-desktop = original.override (
            {
              inherit cups pipewire;
            }
            // nixpkgs.lib.optionalAttrs (appPkgs.gzip.version == "1.14") { inherit buildFHSEnv; }
          );
        };
      codexPackages =
        system:
        let
          recipes = codex-packages.packages.${system};
          original = recipes.codex;
          hasOldTls = builtins.any (
            package: (package.pname or "") == "openssl" && package.version == "3.6.4"
          ) original.buildInputs;
          appPkgs = import codex-packages.inputs.nixpkgs { inherit system; };
          # Keep Codex on its locked application's toolchain and package set.
          # OpenSSL 3.6 has reached end of life; use the reviewed 3.5 LTS fix.
          openssl =
            assert appPkgs.openssl_3_5.version == "3.5.8";
            appPkgs.openssl_3_5.overrideAttrs {
              version = "3.5.9";
              src = appPkgs.fetchurl {
                url = "https://github.com/openssl/openssl/releases/download/openssl-3.5.9/openssl-3.5.9.tar.gz";
                hash = "sha256-YD9WAuLu8A13+9Qp003NWCK7MBdXobyc2yTGcPHrhZo=";
              };
            };
        in
        recipes // { codex = if hasOldTls then original.override { inherit openssl; } else original; };
      happierRecipes = pkgs: happier-packages.packages.${pkgs.stdenv.hostPlatform.system};
      buildHappier =
        pkgs:
        let
          recipes = happierRecipes pkgs;
          artifact = builtins.fromJSON (builtins.readFile ./nix/happier-source.json);
        in
        if recipes ? happier then
          recipes.happier
        else
          # Keep the fallback bound to the exact reviewed recipe snapshot.
          assert happier-packages.rev == artifact.reviewedPackageRecipeRevision;
          pkgs.callPackage ./nix/happier.nix { };
      # Resolve packages from the consuming machine's architecture, never from a
      # developer's workstation or a captured x86-only package set.
      module = { pkgs, ... }: {
        imports = [ ./modules ];
        _module.args.assboxPackage = buildAssbox pkgs;
        _module.args.assboxApplications = {
          antigravity = antigravity-packages.packages.${pkgs.stdenv.hostPlatform.system};
          chatgpt = chatgptPackages pkgs.stdenv.hostPlatform.system;
          claude-code = claude-code-packages.packages.${pkgs.stdenv.hostPlatform.system};
          claude-desktop = claudeDesktopPackages pkgs.stdenv.hostPlatform.system;
          codex = codexPackages pkgs.stdenv.hostPlatform.system;
          cursor = cursor-packages.packages.${pkgs.stdenv.hostPlatform.system};
          happier = happierRecipes pkgs // {
            happier = buildHappier pkgs;
          };
          hermes = hermes-packages.packages.${pkgs.stdenv.hostPlatform.system} // {
            hermes-agent = pkgs.callPackage ./nix/hermes.nix {
              raw = hermes-packages.packages.${pkgs.stdenv.hostPlatform.system}.hermes-agent;
              appPkgs = import hermes-packages.inputs.nixpkgs {
                inherit (pkgs.stdenv.hostPlatform) system;
              };
            };
          };
          pi = pi-packages.packages.${pkgs.stdenv.hostPlatform.system} // {
            pi = pi-packages.packages.${pkgs.stdenv.hostPlatform.system}.pi.override { useBun = false; };
          };
          omp =
            let
              inherit (pkgs.stdenv.hostPlatform) system;
              recipes = omp-packages.packages.${system};
              appPkgs = import omp-packages.inputs.nixpkgs { inherit system; };
              pipewire = import ./nix/reviewed-pipewire.nix { pkgs = appPkgs; };
            in
            recipes
            // {
              omp = recipes.omp.override { inherit pipewire; };
            };
          grok = grok-packages.packages.${pkgs.stdenv.hostPlatform.system};
          openclaw = openclaw-packages.packages.${pkgs.stdenv.hostPlatform.system} // {
            openclaw = import ./nix/openclaw.nix {
              inherit pkgs;
              raw = openclaw-packages.packages.${pkgs.stdenv.hostPlatform.system}.openclaw;
            };
          };
          opencode = opencode-packages.packages.${pkgs.stdenv.hostPlatform.system};

        };
      };
      platform = eachSystem (
        system:
        let
          pkgs = import nixpkgs { inherit system; };
          tools = import ./nix/tool-environment.nix { inherit pkgs; };
          # The standalone release installer needs the same security overrides
          # when it is built on a generic live or bootstrap system.
          installerPkgs =
            (nixpkgs.lib.nixosSystem {
              inherit system;
              modules = [
                ./modules/options.nix
                ./modules/security-overrides.nix
                { assbox.enable = true; }
              ];
            }).pkgs;
          assbox = buildAssbox installerPkgs;
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
      physicalCheckpoint =
        system:
        nixpkgs.lib.nixosSystem {
          inherit system;
          specialArgs = {
            assboxCodex = (codexPackages system).codex;
            inherit sourceRevision;
          };
          modules = [
            ./nix/physical-checkpoint-iso.nix
            (
              { pkgs, ... }:
              let
                checkpointSystemd = pkgs.systemd.override {
                  pname = "systemd-assbox-checkpoint";
                  withBootloader = false;
                  withCoredump = false;
                  withCryptsetup = false;
                  withEfi = false;
                  withFido2 = false;
                  withHomed = false;
                  withImportd = false;
                  withLibBPF = false;
                  withMachined = false;
                  withNspawn = false;
                  withPortabled = false;
                  withRemote = false;
                  withRepart = false;
                  withSysupdate = false;
                  withTpm2Tss = false;
                  withVmspawn = false;
                };
                # Use the system's security-overlaid packages, with only the
                # diagnostic tools available in the read-only image.
                checkpointTools = with pkgs; [
                  curl
                  cacert
                  git
                  jq
                  checkpointSystemd
                  util-linux
                  coreutils
                  findutils
                  gnugrep
                  gnused
                  gnutar
                  iproute2
                  pciutils
                  usbutils
                  openssh
                ];
                checkpointAssbox = (buildAssbox pkgs).overrideAttrs (_old: {
                  ASSBOX_TOOL_PATH = pkgs.lib.makeBinPath checkpointTools;
                  # The full package is tested by the ordinary native gates.
                  doCheck = false;
                  nativeCheckInputs = [ ];
                  GI_TYPELIB_PATH = "";
                });
              in
              {
                _module.args = {
                  assboxPackage = checkpointAssbox;
                  assboxHappier = buildHappier pkgs;
                  assboxCheckpointSystemd = checkpointSystemd;
                };
              }
            )
          ];
        };
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
        // nixpkgs.lib.optionalAttrs (system == "x86_64-linux") {
          physical-checkpoint-iso = (physicalCheckpoint system).config.system.build.isoImage;
        }
      );
      # Exposed data for trusted release jobs; no source mutation is required.
      assboxReleasePolicy = releasePolicy;
      formatter = eachSystem (system: platform.${system}.pkgs.nixfmt);
      devShells = eachSystem (
        system:
        import ./nix/release-environments.nix {
          inherit (platform.${system}) pkgs tools;
          inherit nixpkgs sourceRevision releasePolicy;
        }
      );
      nixosConfigurations =
        nixpkgs.lib.foldl' (all: system: all // platform.${system}.matrix.configurations) { } systems
        // {
          x86_64-linux-physical-checkpoint = physicalCheckpoint "x86_64-linux";
        };
      checks = eachSystem (
        system:
        let
          p = platform.${system};
          installBoot = import ./tests/nix/install-boot-vm.nix {
            inherit module;
            inherit (p) pkgs assbox;
            inputs = self.inputs;
          };
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
              "happier"
              "hermes"
              "pi"
              "omp"
              "grok"
            ])
            (
              name:
              import ./tests/nix/component-family-vm.nix {
                inherit module;
                inherit (p) pkgs;
                family = nixpkgs.lib.removeSuffix "-vm" (nixpkgs.lib.removePrefix "application-" name);
              }
            )
        // nixpkgs.lib.mapAttrs' (
          name: value: nixpkgs.lib.nameValuePair "install-boot-case-${name}" value
        ) installBoot.cases
        // {
          workspace = p.assbox;
          worker-policy = import ./tests/nix/worker-policy.nix {
            inherit module;
            inherit (p) pkgs;
          };
          worker-artifact = import ./tests/nix/worker-artifact.nix {
            inherit module;
            inherit (p) pkgs;
          };
          worker-boot-gate-vm = import ./tests/nix/worker-boot-gate-vm.nix {
            inherit module;
            inherit (p) pkgs;
          };
          worker-sshd-policy-vm = import ./tests/nix/worker-sshd-policy-vm.nix {
            inherit module;
            inherit (p) pkgs;
          };
          worker-network-vm = import ./tests/nix/worker-network-vm.nix {
            inherit module;
            inherit (p) pkgs;
          };
          worker-lifecycle-vm = import ./tests/nix/worker-lifecycle-vm.nix {
            inherit module;
            inherit (p) pkgs;
          };
          worker-tools =
            p.pkgs.runCommand "assbox-worker-tools-tests"
              {
                nativeBuildInputs = [
                  p.pkgs.python3
                  p.pkgs.openssh
                ];
              }
              ''
                cp -r ${./.} source
                chmod -R u+w source
                cd source
                python3 -m unittest discover -s tests/worker -v
                touch "$out"
              '';
          remote-lifecycle-vm = import ./tests/nix/remote-lifecycle-vm.nix {
            inherit (p) pkgs assbox;
          };
          editor-vm = import ./tests/nix/editor-vm.nix {
            inherit module;
            inherit (p) pkgs;
          };
          desktop-services-vm = import ./tests/nix/desktop-services-vm.nix {
            inherit module;
            inherit (p) pkgs;
          };
          execution-loopback-vm = import ./tests/nix/execution-loopback-vm.nix {
            inherit module;
            inherit (p) pkgs;
          };
          computer-use-vm = import ./tests/nix/computer-use-vm.nix {
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
          radio-policy-vm = import ./tests/nix/radio-policy-vm.nix {
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
          install-boot-vm = installBoot.matrix;
          activation-recovery-vm = import ./tests/nix/activation-recovery-vm.nix {
            inherit module;
            inherit (p) pkgs assbox;
            inputs = self.inputs;
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
        // nixpkgs.lib.optionalAttrs (system == "x86_64-linux") {
          physical-checkpoint-iso = (physicalCheckpoint system).config.system.build.isoImage;
          physical-checkpoint-boot =
            let
              checkpoint = physicalCheckpoint system;
              kernel = checkpoint.config.boot.kernelPackages.kernel;
            in
            import ./tests/nix/physical-checkpoint-boot.nix {
              inherit sourceRevision;
              inherit (checkpoint.config.system.build) isoImage;
              inherit (p) pkgs;
              kernelConfig = "${kernel.dev}/lib/modules/${kernel.modDirVersion}/build/.config";
            };
        }
      );
    };
}
