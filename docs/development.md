# Native development

Use trusted Linux with Nix on either `x86_64-linux` or `aarch64-linux`. The flake
selects native packages/toolchains for the running system. ARM development in an
Apple Silicon host's Linux VM is covered in [Parallels](parallels.md); this is not a
Darwin build or cross-installation workflow.

## Use the committed toolchain

```sh
nix develop --no-update-lock-file --no-write-lock-file --command scripts/verify
```

The repository includes a genuine Nix-generated lock. Routine verification uses
those pins without changing them. Run `scripts/format` in the same development
shell when intentionally formatting source, then review the diff. Initial
`nix flake lock` is a bootstrap operation only for a new tree without a lock;
review and commit its real result before using the normal gates.

Provision the actual numeric repository and owner IDs in `release/policy.json`
under the cold-administrator procedure in [governance](governance.md). Zero IDs
permit source development but refuse release acceptance and publication.

Bootstrap is intentionally separate from verification. Never invent a `flake.lock`,
NAR hash, compiler result or release receipt. The [bootstrap maintenance workflow](automation.md) verifies candidate and
existing locks on both architectures before a bounded direct-to-master commit.
It never commits formatting changes.
Once a genuine lock is committed, gate invocations must not rewrite it.

## Rust and tools

The workspace uses Rust edition 2024 and declares minimum Rust 1.90. Its six internal
crates are non-publishable and forbid unsafe code. `Cargo.lock` is committed. Rust,
Cargo, rustfmt and Clippy come from the reviewed Nix lock, as do system tools.
Tooling tests use Python with PyYAML supplied by the Nix development shell.
The shell also supplies Node.js for dependency-free Worker tests and Wrangler for
explicit infrastructure deployment. These are development tools, not new installed
Assbox runtime dependencies.
The shell uses pinned `signal-hook` for cooperative cancellation and `rustix`
(with only `std` and `termios`) for safe terminal restoration and unread-password
flushing. Their MIT/Apache-compatible dependency graphs, versions and checksums
are explicitly reviewed in the architecture guard; Assbox itself still forbids unsafe code.
The functional core still uses only internal dependencies. Structured command output
uses the Nix-provided `jq`. Review dependency changes, including licenses and transitive graphs.

Use the Nix development shell even for Cargo:

```sh
nix develop
cargo test --workspace --all-targets --locked
cargo clippy --workspace --all-targets --locked -- -D warnings
cargo fmt --all -- --check
scripts/verify
```

`ASSBOX_TOOL_PATH` is a required compile-time variable supplied by the same shared
Nix tool environment for dev and packaged binaries. Privileged system commands do
not fall back to host `/usr/bin`, current-system PATH, or a caller's PATH. Nix embeds
the core source revision in the binary; the authenticated manifest supplies the
source NAR and dependency-lock hashes. An unidentified development binary cannot
silently apply an installation from a different core revision. Editor and
application onboarding use a separate narrow installed-program resolver, not the
privileged storage command path.

Native formatting is performed by `scripts/format`; verification uses check-only
formatting. Do not substitute a handwritten formatter. Compiler, type, formatting,
Clippy and actual Nix failures must be fixed with the real tools.

## Tests and promotion

The `Verify locked source` Actions workflow is manual-only (`workflow_dispatch`),
including in development copies. A push or pull request does not start verification.
Run it deliberately for the branch under review and check the resulting SHA before
using its status for promotion. Production release/bootstrap schedules are guarded
and can be disabled entirely in development copies; see [automation](automation.md).

Read [verification](verification.md) before interpreting results. Ordinary verification
runs the checks that exist; release promotion additionally requires named full
installation/boot, activation/recovery, authenticated-release and per-application
checks on each architecture. Missing
end-to-end tests deliberately block promotion rather than creating a successful
placeholder. CI uses native x86-64 and ARM runners; ARM QEMU tests can use software
emulation without assuming nested KVM availability.

The install/recovery gates build real systems in disposable guests and boot the
produced disks. Their test executable adds interruption checkpoints and controlled
release transport; neither is compiled into the installed CLI. See
[`tests/fixtures/README.md`](../tests/fixtures/README.md) for the public disposable
TLS material and fixture boundaries. These gates are expensive; syntax checking
and compiling their harness do not execute them.

Keep logs/coverage/scan outputs external to distributable source. Never include real
hardware profiles, credentials, build caches or machine-specific validation captures
in the repository. Maintain source, tests and durable product/engineering documentation;
keep delivery reports and environment-specific validation records outside it.

## Dependency release execution

`.github/workflows/release.yml` runs from `master` only through inputless
`workflow_dispatch` or its fixed daily GitHub schedule.
It authenticates a previous release, resolves candidate dependencies in temporary
state, probes each advancing application on both architectures, and re-tests the
composed final lock. Core source files must remain byte-for-byte identical to the
checked-out commit; only release lock/context data differ. The workflow does not
commit those files. Fresh privileged jobs validate all artifact bytes/evidence,
attest the manifest and publish immutable assets without evaluating candidate Nix.
Both native public-verification jobs run `scripts/release.py live-verify`. Each
builds the bootstrap client from the reviewed master lock, authenticates the exact
published tag, then builds the candidate client from that authenticated store tree
and its release lock. The candidate must independently verify the same public
release in a new directory and agree on manifest/lock/source identity before latest
can be advertised. No GitHub token is available to either client's child commands.

The bootstrap maintenance workflow does not configure rulesets, environments, numeric
IDs or immutable releases. Those are explicit cold-administrator tasks. Do not
remove missing-check guards or substitute placeholder passing derivations to get
a first release. Current tests, remaining acceptance and operational limits are in
[verification](verification.md), [release authentication](release-authentication.md)
and [governance](governance.md).

## External infrastructure source

The read-only monitor is a conventional JavaScript ES module under `infra/`.
It uses Web APIs and has no npm runtime dependencies. Run its tests without a
Cloudflare login:

```sh
node --test infra/release-monitor/tests/*.test.mjs
```

These tests mock GitHub observations; they do not establish deployed availability,
public attestation validity or provider resource consumption. Deployment and alert
routing are separate administrator operations. Do not commit Wrangler credentials,
`.dev.vars`, generated infrastructure state or account tokens.

## Component metadata

Edit `catalog/components.json`, then run `python3 scripts/component_catalog.py`
to regenerate typed Rust identifiers and release-family metadata. The static gate
checks drift. Integration behavior belongs in ordinary typed Nix/Rust adapters,
not executable catalog strings. New release families also require native VM exports
and both architecture entries in the release workflow; add coverage in the same change.
No prerelease application-schema compatibility layer is retained.

The Nix verification stage enumerates every native check and builds each in a
separate process, preserving failures and releasing evaluator memory between checks.
It does not set Nix job/core limits; each build retains normal parallelism.
