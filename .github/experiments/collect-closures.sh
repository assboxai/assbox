#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
set -euo pipefail
assbox_audit_dir=$1
architecture=$(nix eval --impure --raw --expr builtins.currentSystem)
test "$architecture" = aarch64-linux
printf "system\t%s\ngateSha256\t%s\n" "$architecture" "$(sha256sum scripts/release-check | cut -d' ' -f1)"
test -z "$(git status --porcelain)"
export XDG_CACHE_HOME="$assbox_audit_dir/cache"
mkdir -m 0700 -- "$XDG_CACHE_HOME"
vulnerability_reports=()
closure_targets=()
scan_closures() {
  local report=$1
  shift
  local result
  (($# > 0))
  set +e
  vulnix --cache-dir "$XDG_CACHE_HOME" "$@" --closure --json > "$report"
  result=$?
  set -e
  printf "%s\n" "$result" > "$assbox_audit_dir/vulnix.exit"
  case "$result" in
    0|2) ;;
    *) echo "Vulnix failed with status $result for release closures" >&2; exit "$result" ;;
  esac
  vulnerability_reports+=("$report")
}
mapfile -t systems < <(nix eval --json --no-update-lock-file --no-write-lock-file .#nixosConfigurations --apply builtins.attrNames | jq -r --arg prefix "$architecture-" '.[] | select(startswith($prefix))')
((${#systems[@]} > 0))
for system in "${systems[@]}"; do
  printf "Collecting system %s\n" "$system" >&2
  path=$(nix build --no-link --print-out-paths --no-update-lock-file --no-write-lock-file ".#nixosConfigurations.$system.config.system.build.toplevel")
  # Preserve every raw finding. The exact lock-bound policy below adjudicates
  # patched and false product matches without hiding them from Vulnix.
  closure_targets+=("$path")
  printf "%s\t%s\t%s\n" "$system" toplevel "$path"
  worker_enabled=$(nix eval --json --no-update-lock-file --no-write-lock-file ".#nixosConfigurations.$system.config.assbox.worker.enable")
  if [[ "$worker_enabled" == true ]]; then
    worker_audit=$(nix build --no-link --print-out-paths --no-update-lock-file --no-write-lock-file ".#nixosConfigurations.$system.config.system.build.assboxWorkerAudit")
    closure_targets+=("$worker_audit")
    printf "%s\t%s\t%s\n" "$system" worker "$worker_audit"
  elif [[ "$worker_enabled" != false ]]; then
    echo "Invalid worker audit selection for $system" >&2; exit 1
  fi
done
if [[ "$architecture" == x86_64-linux ]]; then
  checkpoint_iso=$(nix build --no-link --print-out-paths --no-update-lock-file \
    --no-write-lock-file ".#packages.$architecture.physical-checkpoint-iso")
  closure_targets+=("$checkpoint_iso")
  printf "%s\t%s\t%s\n" "$architecture" checkpoint "$checkpoint_iso"
fi
# The runtime artifact intentionally has no guest closure references. Scan the
# independently evaluated guest closure even when the host matrix has no worker.
audit_expr='let f = builtins.getFlake (toString ./.); s = f.inputs.nixpkgs.lib.nixosSystem { system = builtins.currentSystem; modules = [ f.nixosModules.default ./tests/nix/fixture.nix { assbox.updates.enable = false; assbox.worker = { enable = true; components = [ "codex" ]; egress = "offline"; nameservers = [ ]; }; } ]; }; in s.config.system.build.assboxWorkerAudit'
guest_audit=$(nix build --impure --no-link --print-out-paths --no-update-lock-file --no-write-lock-file --expr "$audit_expr")
closure_targets+=("$guest_audit")
printf "%s\t%s\t%s\n" "$architecture" offline-worker "$guest_audit"
# Most configurations share nearly their entire runtime closure. Scan the
# deduplicated union once so the exact closure check does not reparse the same
# thousands of store paths for every matrix variant.
mapfile -t closure_targets < <(printf '%s\n' "${closure_targets[@]}" | sort -u)
printf '%s\n' "${closure_targets[@]}" > "$assbox_audit_dir/vulnerability-closure-roots.txt"
scan_closures "$assbox_audit_dir/vulnix-$architecture-release-closures.json" "${closure_targets[@]}"
nixpkgs_source=$(nix eval --impure --raw --expr 'let f = builtins.getFlake (toString ./.); in f.inputs.nixpkgs.outPath')
application_nixpkgs_source=$(nix eval --impure --raw --expr 'let f = builtins.getFlake (toString ./.); in f.inputs.chatgpt-packages.inputs.nixpkgs.outPath')
printf "nixpkgs\t%s\napplicationNixpkgs\t%s\n" "$nixpkgs_source" "$application_nixpkgs_source" > "$assbox_audit_dir/source-paths.tsv"
test -z "$(git status --porcelain)"
