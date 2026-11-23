#!/usr/bin/env bash
set -euo pipefail
umask 077
unset GH_TOKEN GITHUB_TOKEN ACTIONS_RUNTIME_TOKEN ACTIONS_ID_TOKEN_REQUEST_TOKEN ACTIONS_ID_TOKEN_REQUEST_URL

evidence=$1
test "$RUNNER_ENVIRONMENT" = github-hosted
test "$(uname -m)" = aarch64
test "$(git rev-parse HEAD)" = "$PRODUCT_COMMIT"
test "$(git rev-parse 'HEAD^{tree}')" = "$PRODUCT_TREE"
test -z "$(git status --porcelain)"
test -d "$evidence"
export XDG_STATE_HOME="$RUNNER_TEMP/assbox-arm-native-nix-state"
mkdir -m 0700 "$XDG_STATE_HOME"

accel=tcg
if test -r /dev/kvm && test -w /dev/kvm; then accel=kvm-available; fi
{
    printf 'architecture\taarch64-linux\n'
    printf 'acceleratorAvailability\t%s\n' "$accel"
    printf 'workflow\t%s\nrun\t%s\nattempt\t%s\n' "$GITHUB_SHA" "$GITHUB_RUN_ID" "$GITHUB_RUN_ATTEMPT"
    printf 'source\t%s\ntree\t%s\n' "$PRODUCT_COMMIT" "$PRODUCT_TREE"
    printf 'started\t%s\n' "$(date -u +%FT%TZ)"
} > "$evidence/native-scope.tsv"
sha256sum flake.lock nix/dev/flake.lock scripts/verify scripts/release-check > "$evidence/native-inputs.sha256"
nix eval --json --no-update-lock-file --no-write-lock-file .#checks.aarch64-linux \
    --apply builtins.attrNames > "$evidence/native-checks.json"
python3 -I -B - "$evidence/native-checks.json" <<'PY'
import json
import sys

with open(sys.argv[1], encoding='utf-8') as stream:
    checks = json.load(stream)
assert checks and checks == sorted(set(checks))
PY

status=0
nix develop .#release-check --no-update-lock-file --no-write-lock-file --command scripts/verify nix \
    2>&1 | tee "$evidence/verify-nix.log" || status=$?
printf 'verify_nix\t%s\t%s\n' "$status" "$(date -u +%FT%TZ)" > "$evidence/native-result.tsv"
test -z "$(git status --porcelain)"
exit "$status"
