# Interactive installer repair loop

Use native Linux and the pinned Chainman repair profile. The loop drives the normal
`assbox install --apply --release r-1` CLI through a pseudoterminal, installs on
fresh disposable GPT/UEFI disks, then boots the resulting disk. It keeps the existing
installation/fault-injection, activation/recovery, component and authenticated-release
gates. A canonical pass covers one minimal headless selection, not every supported
application or real provider authentication.

## Start and inspect a session

First make the existing static, Rust, mutation and production gates green. Choose a
reviewed commit containing the canonical harness, then create an external session:

```sh
just repair-init --oracle-ref REVIEWED_COMMIT
just repair-preflight --session /absolute/private/session --json
just repair-status --session /absolute/private/session --json
```

`repair-init` prints the new absolute session path. Reusing a session path is refused.
Untracked source must be staged deliberately or selected with repeated
`--include-new relative/path`; the runner never modifies the caller's index. During
initial harness development, `--oracle-source /absolute/clean/external/export` can
freeze an explicitly selected independent source export. Its evidence says
`cooperative-external-snapshot`; a synthetic commit is never presented as a reviewed
public commit. Routine `just verify` defaults to the caller's committed HEAD oracle.
Use `--oracle-ref` or `--oracle-source` to select another reviewed judge.

The whole oracle is frozen, including imported fixtures, source mirrors, driver
expression, PTY controller, probes, policy and locked dependencies. Every attempt
rechecks its manifest. Existing tests (including crate integration tests), root flake
gate definitions, root/developer locks,
workflow authority, source admission and budgets are protected during a repair
session. Product files may change; new regression fixtures/tests may be explicitly
included. A judge or policy correction requires a separately reviewed new session.

Preflight and status never build a driver or start QEMU. Preflight checks native
architecture, available tools, KVM access, available memory/cgroup headroom, and
state/store free bytes and inodes. Shared storage is identified rather than counted
twice. The initial 10-GiB memory and 100-GiB storage guardrails are conservative
configuration, not measured minimum requirements. It does not run sudo, repair
permissions, collect credentials or garbage-collect the Nix store.

## Build, run and finalize

```sh
just repair-build --session /absolute/private/session
just repair-once --session /absolute/private/session
just repair-status --session /absolute/private/session --json
just repair-finalize --session /absolute/private/session
```

The reviewed driver dependency boundary contains a no-worker minimal seed, the
ordinary CLI build, build/source closures and a non-running NixOS `.driver` output.
`repair-build` compiles that output and records `built`, with `vm_executed=false`.
`repair-once` launches its program directly; a cached successful Nix test cannot
satisfy the attempt. Each run gets a new source snapshot, disk images, EFI state,
nonce, fixture state and disposable SSH key. The installer releases its writable
target image before the target starts. No host block device or credential mount is
accepted. The virtual network is isolated, with only declared mirror/SSH fixtures.

The synthetic release contains exact candidate source plus a listed generated
`release-context.json`. It binds the actual candidate commit/content, root lock,
version, archive SHA-256 and genuine NAR hash. Only curl, gh, time queries and
password delivery are fixture adapters. Nix, mounts, filesystems, SSH, builds and
bootloaders remain real. The narrow transport is synthetic evidence; the separate
authenticated-release gate exercises real cryptography.

After the CLI finishes, the harness applies a declared machine-local module using
a second real `nixos-install`. This supplies test-driver access, static eth1/mirror
trust and timer control while preserving locked root and account/storage policy.
Evidence records the module digest and original/instrumented system identities.
The installed CLI is the normal candidate production package; closure assertions
reject the fixture-linked installer and transport adapters. This instrumented boot
does not claim an entirely fixture-free appliance or production network behavior.

All P01–P14 observations in [the scenario](../development/canonical-scenario.json)
must pass, including complete installation/backup identities, boot, private state,
empty failed-unit list, admin-key SSH, denied root/workload SSH and denied workload
sudo/raw-disk/secret access. Unexpected wizard states, retry prompts or changed
disk confirmation fail the fresh-run scenario. Passwords/hashes and private keys
are not exported. Disposable password delivery does not qualify the real helper UI.

Finalization requires a current canonical pass and runs the full gate again against
the already frozen candidate and oracle. It reports the actual native system;
an x86-64 run cannot qualify ARM. It never commits, publishes or enables automation.

## Evidence and limits

Private session state defaults to `$XDG_STATE_HOME/assbox/repair` (or
`~/.local/state/assbox/repair`), outside source. Each numeric run has its manifest,
deterministic candidate receipt, runtime/preflight facts, build/driver logs,
guest artifacts, cleanup record and final summary. A ledger start without a final
summary is incomplete. Inspection marks an older success stale if source changed.
Do not upload VM disks, private keys, password hashes or full guest state.
Disposable qcow2 images are removed after the owned group drains. Explicit
`repair-init --retain-disks` retains images privately for diagnosis; they remain
excluded from CI uploads. Cleanup uncertainty preserves them for investigation.

Budgets are frozen at creation: eight attempts, three identical failures without
progress, six cumulative driver hours, three hours per run, and ten-minute boot
and post-boot bounds. Logs are bounded. Signals preserve partial evidence and
terminate the owned process group with a grace period. A host Nix daemon's builder
cancellation is explicitly not proven by the client exiting. Cleanup never kills
unrelated QEMU/Nix processes or deletes external evidence to make space.

Run results use exits 0 passed, 1 failed, 2 invalid, 3 blocked, 4 controller error,
130/143 cancelled. Inspection may exit zero without a VM pass. A driver build,
fixture simulation or static test is not execution evidence.

The initial isolation is cooperative single-user protection against accidental
judge edits. A same-user process with arbitrary host shell access can interfere.
Higher assurance requires a separately owned controller/oracle and restricted run
interface on an expendable worker. Native compatibility gates do not establish
that candidate dependencies or intentionally deceptive product code are benign.
