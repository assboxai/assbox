# Native development

Use trusted Linux with Nix on either `x86_64-linux` or `aarch64-linux`. The flake
selects native packages/toolchains for the running system. ARM development in an
Apple Silicon host's Linux VM is covered in [Parallels](parallels.md); this is not a
Darwin build or cross-installation workflow.

## Use the committed toolchain

```sh
just setup
just verify
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
After changing reviewed component/preset data, regenerate with
`python3 scripts/component_catalog.py`, `python3 scripts/preset_catalog.py` and
`python3 scripts/product_docs.py`. The last command also renders the dated Linux
evidence matrix from `qualification/linux-computer-use.json`. Static verification
checks these artifacts for drift without fetching provider websites.

The purpose-flow transcript test runs the same selection code through a scripted
terminal adapter, without hardware probes, login, enrollment or configuration
writes. It covers all preset branches, Back, exclusions, dependency refusal,
cancellation and per-app native policy states. Review intentional UI changes in
`tests/fixtures/selection_transcripts.txt`; regenerate that file with
`ASSBOX_UPDATE_SELECTION_GOLDENS=1 cargo test -p assbox-cli purpose_flow_matches`
in the pinned development shell. Running the test normally never rewrites it.
These fixtures do not substitute for a real terminal/install or native account test.
The shell and package check environment also supply PyGObject and libnm's type
metadata for the Wi-Fi renderer's real-parser regression test. Missing bindings
fail that test; they do not silently skip it. No NetworkManager daemon is needed.
The environments supply Node.js for dependency-free Worker tests. Explicit
infrastructure administration can use Wrangler from the root `release-check`
environment. These tools do not become installed Assbox runtime dependencies.
The workspace uses pinned `signal-hook` for cooperative cancellation and `rustix`
(with only `std` and `termios`) for safe terminal restoration and unread-password
flushing. Their MIT/Apache-compatible dependency graphs, versions and checksums
are explicitly reviewed in the architecture guard; Assbox itself still forbids unsafe code.
The functional core still uses only internal dependencies. Structured command output
uses the Nix-provided `jq`. Review dependency changes, including licenses and transitive graphs.

Use the Nix development shell even for Cargo:

```sh
just test
just verify-rust
just format-check
just verify
```

`ASSBOX_TOOL_PATH` is a required compile-time variable. The independent developer
flake supplies its own unidentified test environment; the root production flake
supplies the authenticated package and compiler environment. Privileged system commands do
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
using its status for promotion. Production release/bootstrap/development-maintenance schedules are guarded
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
can be advertised. The candidate also imports the public default kernel into a
fresh isolated store on each native architecture before advertising. No GitHub
token is available to any client's child commands.

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

## Chainman and environment ownership

Install Nix and Just on the Linux host, then use the root Justfile. Its verified Git
bootstrap loads exactly `chainman.lock`; ordinary commands never check for updates.
The committed runtime is `4a48222bdfe1036891c73627923cd22d4e7ccb4b`. This repository
admits only Chainman's `host-nix` mode on Linux. `just explain verify --json`,
`just doctor`, `just deps-check`, `just deps-coverage` and `just deps-policy-report`
inspect the configuration. `just setup` installs owned staged-format hooks; use
`just setup --no-hooks` in CI. Hook ownership and partially staged files follow the
pinned runtime's protocol. Do not replace someone else's hook or run a second
handwritten hook manager.

On a fresh host with Nix and no installed Just, run
`nix run path:./nix/dev#just -- setup --no-hooks`. Public recipes reuse the invoking
Just executable, including when `nix run` has not added it to `PATH`.

The pinned CI Nix installer persists the job's GitHub token in `/etc/nix/nix.conf`.
Every installation immediately runs the reviewed inline cleanup, restarts the
daemon and checks that the effective access-token setting is empty before running
candidate code. Child environment scrubbing alone does not remove that file.

Before installing Nix, hosted Linux jobs reclaim the unused Android, .NET,
hosted-tool-cache and GHCup directories. The fixed inline controller refuses local
and self-hosted contexts, redirected directories and nested mounts, and validates
the entire set before deletion. It records actual free bytes before and after;
these observations do not waive the frozen canonical resource guardrails.

`nix/dev` is self-contained with a genuine independent lock and default, formatter
and repair profiles. It initially shares the production Nixpkgs revision. The root
flake has explicit `release-tools` and `release-check` shells and no default
developer shell. Production workflows never bootstrap Chainman. For a direct
production check use `nix develop .#release-check --command scripts/release-check`
on a clean committed tree. The developer adapter creates an independent clean
snapshot before calling that unchanged production gate.

`just build`, `just test`, `just generate`, `just format-write` and
`just format-check` are ordinary developer operations. `just verify-lite` runs static
and Rust checks. `just verify-prepare` adds mutations and configuration inspection,
without Nix builds, a VM, or an update transaction. `just verify` freezes source
once, checks development tooling, runs every existing production gate including
coverage/audit, then executes a fresh canonical interactive installation. Targeted
stages and driver builds are not full verification. See [the repair loop](repair-loop.md).

Untracked source needs an explicit repeated `--include-new PATH` when taking a
candidate snapshot; the runner never stages files for you. Tracked working bytes,
modes and intentional deletions are captured, and index/HEAD remain unchanged.
Generated `.cache/toolchain`, `.chainman`, Cargo targets and reports are not source.
Tracked developer code and both developer locks remain part of the authenticated
whole-repository core: changing them can rebuild the appliance and select a later
release. The flake split does not create a filtered production tree.

`just deps-update commit=off` verifies in a disposable transaction before applying
changes locally without committing. Untargeted updates include the exact canonical
upstream Chainman default-branch SHA and mature developer Nixpkgs releases. The
project dependency maturity window is 30 days; it does not apply to Chainman.
`just chainman-update` selects runtime-only maintenance. `just deps-propose-rust`
and `just deps-propose-actions` are explicit verified previews; a preview can run
VMs. They cannot change dependency approval guards to authorize themselves. Cargo,
Actions, production `flake.lock`, artifact pins and release authority have separate
review/ownership. [Scheduled maintenance](development-maintenance.md) starts disabled
and can write only the two developer lock files after both native gates pass.
