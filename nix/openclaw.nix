# SPDX-License-Identifier: GPL-3.0-or-later
{ pkgs, raw }:
let
  oldNode = builtins.any (
    package: (package.pname or "") == "nodejs" && package.version == "24.20.0"
  ) raw.nativeBuildInputs;
  applicationBase =
    if oldNode then
      # The locked application recipe selects Node before the October
      # security release. Use Assbox's reviewed Node 24 build for the
      # application and its normal launcher.
      assert pkgs.lib.versionAtLeast pkgs.nodejs_24.version "24.22.3";
      raw.override { nodejs = pkgs.nodejs_24; }
    else
      raw;
  # The signed release includes the gateway lease fix and the approval fix
  # from GHSA-pw3x-g8v8-fvj2.
  application =
    if applicationBase.version == "2026.9.5" then
      applicationBase.overrideAttrs (
        final: previous:
        let
          pnpm = import ./openclaw-pnpm-build-tool.nix pkgs;
          # The sealed worker build uses the Darwin addons from this exact
          # fs-safe release. Stage the upstream cache entries from its lock.
          fsSafeVersion = "0.27.1";
          workerAssets =
            pkgs.lib.mapAttrsToList
              (
                target: integrity:
                let
                  package = "fs-safe-${target}";
                in
                {
                  archive = pkgs.fetchurl {
                    url = "https://registry.npmjs.org/@openclaw/${package}/-/${package}-${fsSafeVersion}.tgz";
                    hash = integrity;
                  };
                  cachedName = "${target}-${fsSafeVersion}-${builtins.hashString "sha256" integrity}.tgz";
                }
              )
              {
                darwin-arm64 = "sha512-RXheLSPD8K0IiJ4p6KW8JVlrLd148OM84Z6wDerEmiF3/RbiiBUerNJ+LIzjyxDesZoCQIr8okq6zLdjSZkvdg==";
                darwin-x64 = "sha512-2CfUUGJc4dwaTuvo4xiKq5zbF9p6p6Cp+zS+M0hTg2E8RLPH/i2+CtF1MOeeMY6q/7FlpS4AOBcf4NNQmLCZFA==";
              };
          pnpmDeps = pkgs.fetchPnpmDeps {
            inherit (final) pname version src;
            inherit pnpm;
            hash = "sha256-vh+JmLJn9fT/jQRjBWFyT2GlT4GfKq2DcXDI07DYnZA=";
            fetcherVersion = 4;
            prePnpmInstall = ''
              cat >> pnpm-workspace.yaml <<'EOF'

              supportedArchitectures:
                - linux-x64
                - linux-arm64
              EOF
            '';
          };
        in
        {
          version = "2026.11.7";
          src = pkgs.fetchFromGitHub {
            owner = "openclaw";
            repo = "openclaw";
            rev = "e31bbf056de321127988ec5c1a36ff1b59297de0";
            hash = "sha256-mNApehyzd0o5SELkvOyFPsaPD85Bvu4JPin3mAWgvnI=";
          };
          # Keep all upstream patches and verify the published lockfile with
          # the same pnpm release during dependency fetching and offline build.
          postPatch = "";
          nativeBuildInputs =
            builtins.filter (
              input:
              !(builtins.elem (pkgs.lib.getName input) [
                "pnpm"
                "pnpm-config-hook"
              ])
            ) previous.nativeBuildInputs
            ++ [
              pnpm
              pkgs.pnpmConfigHook
            ];
          inherit pnpmDeps;
          preBuild = (previous.preBuild or "") + ''
            mkdir -p .artifacts/worker-native-assets
            ${pkgs.lib.concatMapStringsSep "\n" (
              asset: "install -m 0600 ${asset.archive} .artifacts/worker-native-assets/${asset.cachedName}"
            ) workerAssets}
          '';
          # The current Control UI publishes its build identity in the
          # HTML bootstrap so it is available before the first JS chunk loads.
          postInstallCheck = ''
            node --input-type=module - "$out/lib/openclaw/dist" <<'NODE'
            import assert from "node:assert/strict";
            import { readFileSync } from "node:fs";
            import { join } from "node:path";

            const dist = process.argv[2];
            const runtime = JSON.parse(readFileSync(join(dist, "build-info.json"), "utf8"));
            const html = readFileSync(join(dist, "control-ui", "index.html"), "utf8");
            const bootstrap = /<script\b[^>]*\bid="openclaw-control-ui-build-info"[^>]*>globalThis\.OPENCLAW_CONTROL_UI_BUILD_INFO=(\{[^<]*\});<\/script>/u.exec(html);
            assert.ok(bootstrap, "Control UI build info bootstrap missing");
            const controlUi = JSON.parse(bootstrap[1]);
            assert.ok(typeof runtime.buildId === "string" && runtime.buildId.length > 0, "Runtime build ID missing");
            assert.equal(controlUi.version, runtime.version);
            assert.equal(controlUi.buildId, runtime.buildId);
            NODE
          '';
          disallowedRequisites =
            (previous.disallowedRequisites or [ ])
            ++ [
              pnpm
              pnpmDeps
            ]
            ++ map (asset: asset.archive) workerAssets;
        }
      )
    else
      applicationBase;
  healthClient = pkgs.writeText "assbox-openclaw-health.mjs" (
    builtins.readFile ./openclaw-health.mjs
  );
  wrapper = pkgs.writeShellScriptBin "openclaw" ''
    case " ''${NODE_OPTIONS-} " in
      *" --disable-warning=ExperimentalWarning "*) ;;
      *)
        export NODE_OPTIONS="--disable-warning=ExperimentalWarning''${NODE_OPTIONS:+ $NODE_OPTIONS}"
        ;;
    esac

    # The full CLI imports every command before dispatch. On the one-vCPU
    # appliance acceptance machine, that cold import can starve a newly ready
    # gateway indefinitely. Use OpenClaw's narrow RPC runtime for the fixed
    # appliance health endpoint. The upstream runtime still performs the real
    # authenticated health request; all other commands keep the full CLI.
    if [[ ''${1-} == gateway && ''${2-} == health ]]; then
      for argument in "$@"; do
        case "$argument" in
          ws://127.0.0.1:18789|--url=ws://127.0.0.1:18789)
            exec ${pkgs.nodejs}/bin/node \
              ${healthClient} \
              ${application}/lib/openclaw/dist/gateway-rpc.runtime.js \
              "$@"
            ;;
        esac
      done
    fi
    exec ${application}/bin/openclaw "$@"
  '';
in
wrapper.overrideAttrs (old: {
  name = "${application.name}-assbox-entrypoint";
  inherit (application) meta;
})
