#!/bin/bash
set -euo pipefail
umask 077

evidence=$1
export CARGO_TARGET_DIR="$evidence/cargo-target"
export CARGO_BUILD_JOBS=2
export RUST_TEST_THREADS=2
printf '%s\n' "$(uname -sm)" > "$evidence/platform.txt"
sha256sum Cargo.lock scripts/release-check > "$evidence/release-inputs.sha256"
{
    for bin in cargo rustc cargo-llvm-cov cargo-audit; do
        printf '%s\t%s\n' "$bin" "$(command -v "$bin")"
    done
    printf 'llvm-cov\t%s\n' "$LLVM_COV"
    printf 'llvm-profdata\t%s\n' "$LLVM_PROFDATA"
} > "$evidence/release-tools.tsv"
coverage=0
cargo llvm-cov --package assbox-domain --package assbox-policy --package assbox-config \
  --all-targets --locked --fail-under-lines 90 --json --output-path "$evidence/core-coverage.json" \
  > "$evidence/core-coverage.log" 2>&1 || coverage=$?
printf 'coverage\t%s\t%s\n' "$coverage" "$(date -u +%FT%TZ)" > "$evidence/stages.tsv"
audit=0
cargo audit --file Cargo.lock > "$evidence/cargo-audit.log" 2>&1 || audit=$?
printf 'audit\t%s\t%s\n' "$audit" "$(date -u +%FT%TZ)" >> "$evidence/stages.tsv"
if test -d "$HOME/.cargo/advisory-db"; then
    git -C "$HOME/.cargo/advisory-db" rev-parse --verify HEAD > "$evidence/advisory-db-head.txt" || true
fi
test -z "$(git status --porcelain)"
test "$coverage" -eq 0 && test "$audit" -eq 0
