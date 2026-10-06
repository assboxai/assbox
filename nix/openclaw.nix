# SPDX-License-Identifier: GPL-3.0-or-later
{ pkgs, raw }:
let
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
              ${raw}/lib/openclaw/dist/gateway-rpc.runtime.js \
              "$@"
            ;;
        esac
      done
    fi
    exec ${raw}/bin/openclaw "$@"
  '';
in
wrapper.overrideAttrs (old: {
  name = "${raw.name}-assbox-entrypoint";
  inherit (raw) meta;
})
