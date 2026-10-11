# Worker verification and release acceptance

## Evidence levels

Roles are [controller, worker and mobile client](terminology.md). In upstream
SSH instructions the SSH host is the worker, not the controller. The local
managed-KVM architecture is fixed; actual client routing remains an explicit
regression/security gate, not a presumption that the controller supplies tools.

Use separate results for configuration review, Python tests, Nix evaluation, image construction, VM networking, production KVM lifecycle, provider authentication and mobile use. A pass at one level does not establish a pass at another. Record exact source revision, lock hash, architecture, controller kernel, QEMU version, Desktop version, Codex version, RAM, storage, network setup and result date.

The current observed status is in [implementation-status.md](implementation-status.md). The code is not presented as a production-qualified release. Unexecuted gates remain requirements, not green placeholders.

## Automated gates included

| Gate | Implemented mechanism | What it does not establish |
| --- | --- | --- |
| Worker helper tests | `python3 -m unittest discover -s tests/worker -v` | Native Nix option validity, firewall behavior or worker boot |
| Python syntax | `python3 -m py_compile` on helper and tests | Runtime integration |
| Component metadata | Existing catalog checks; Remote dependency/availability test | Authenticated Linux Remote success |
| Native module policy | `checks.<system>.worker-policy` | Booting the resulting image |
| Self-contained artifact | `checks.<system>.worker-artifact` | Booting that artifact, production storage pressure or a completed vulnerability scan |
| Maintenance state integration | `checks.<system>.worker-boot-gate-vm` | A real nested KVM worker or provider readiness |
| Effective worker SSH policy | `checks.<system>.worker-sshd-policy-vm` | Actual provider auth or Desktop tunnel compatibility |
| Controller network policy | `checks.<system>.worker-network-vm` | Production QEMU lifecycle or proprietary app behavior |
| Disabled-state lifecycle | `checks.<system>.worker-lifecycle-vm` | Nested KVM execution or a real worker filesystem; fixture uses synthetic state |
| Nix-packaged helper tests | `checks.<system>.worker-tools` | Native QEMU boot |
| Actual worker lifecycle | `tests/worker/kvm-acceptance.py` on configured controller | Comprehensive escape resistance, provider auth or mobile routing |
| Complete repository checks | Existing `scripts/verify` and release gate | Provider acceptance without an actual account/device test |

The worker check names are also required by `scripts/release-check`. That prevents accidental removal of worker checks from the advertised matrix. The full native verifier enumerates all checks, preserving existing coverage. Name presence is not treated as a passing execution result.

### Local/source checks

From the `assbox` source directory:

```sh
python3 -m unittest discover -s tests/worker -v
python3 -m py_compile scripts/worker/worker.py tests/worker/test_worker.py tests/worker/kvm-acceptance.py
python3 scripts/architecture.py
python3 scripts/workflow_policy.py
python3 scripts/model_check.py
```

Use the pinned Chainman entrypoints for the full toolchain:

```sh
just setup
just verify-static
just verify-rust
just verify-mutations
just verify-nix
```

Formatting must pass the repository's normal `cargo fmt`/`nixfmt` checks. Use `scripts/format` to format source changes, review its output, and rerun the gate. See the integration status for checks actually executed on this candidate.

The helper tests exercise fixed paths and arguments, KVM-only refusal, physical-RAM refusal, explicit network configuration, disk non-destruction, symlink/hardlink refusal, idempotent SSH configuration, output limits and selected source-level policies. Source-string assertions are supporting regression tests, not a Nix interpreter or a packet filter proof.

### Native Nix checks

Run on the native architecture; repeat on every architecture to be advertised:

```sh
system=$(nix eval --impure --raw --expr builtins.currentSystem)
nix build --no-link --no-update-lock-file --no-write-lock-file ".#checks.$system.worker-tools"
nix build --no-link --no-update-lock-file --no-write-lock-file ".#checks.$system.worker-policy"
nix build --no-link --no-update-lock-file --no-write-lock-file ".#checks.$system.worker-artifact"
nix build --no-link --no-update-lock-file --no-write-lock-file ".#checks.$system.worker-boot-gate-vm"
nix build --no-link --no-update-lock-file --no-write-lock-file ".#checks.$system.worker-sshd-policy-vm"
nix build --no-link --no-update-lock-file --no-write-lock-file ".#checks.$system.worker-network-vm"
nix build --no-link --no-update-lock-file --no-write-lock-file ".#checks.$system.worker-lifecycle-vm"
```

The policy check evaluates the real controller/worker modules with an offline `vim` worker. It checks normal assertions and rejection of incompatible controller placement or missing internet uplinks. Check the resolved worker component selection and ensure `codex`, other optional agents and remote editor downloads are absent unless selected.

The network gate uses the production controller nftables rules with a separate attacker VM, rather than pretending an ordinary NixOS test-driver worker is the production worker. It proves that a deliberately reachable controller listener is denied from the worker link, while a trusted outside peer can reach it; a live IPv6 listener is also denied. It switches the actual production configuration between internet, normal and offline. It checks private-network denial/permission, public and private DNS resolution, a simulated public destination, allowed controller-initiated traffic, outside-inbound denial, source-address spoofing refusal and atomic firewall reload.

The test's `8.8.8.8` address belongs to its isolated fixture; it is not a probe against an actual external DNS operator. Test-driver filesystem sharing is not evidence for the production worker's no-share contract. That is why the actual runtime gate below is separate.

These fixture VMs permit software emulation on AArch64, consistent with the existing repository gates. They exercise host policy and service integration without starting a production worker. The production worker always requires KVM; passing emulated fixtures cannot qualify its runtime.

### Actual production worker test

First configure the subsystem on a disposable native-KVM Assbox machine, preferably offline with only `vim`. Build and boot the exact image and inspect the real unit properties and QEMU command line. From the source directory, run:

```sh
sudo python3 tests/worker/kvm-acceptance.py --acknowledge-worker-restart
```

This intentionally restarts the real worker, temporarily suspends its health and boot-acceptance retry timers, and uses the generated SSH transport. It checks the running VMM is non-root and KVM-only, tests absence of a random controller-home canary in the worker, checks basic role and no-share properties, writes a disposable worker nonce, restarts, verifies a new boot ID and surviving nonce, and checks the expected generation. It cleans its test files and restores each timer's original active state. It refuses to disrupt a still-running boot-acceptance engine instead of killing a possible maintenance transaction.

The canary test is evidence of filesystem separation for the tested paths, not a proof that no covert channel or hypervisor vulnerability exists. The test does not authenticate OpenAI or enumerate chat history. Its JSON explicitly reports provider and mobile tests as not tested. Local
lifecycle inspection runs as root, but worker-facing SSH is dropped to the
unprivileged controller account; test tooling must not parse hostile worker
SSH traffic as controller root.

## Required negative and fault tests

Complete these on disposable state. Do not use production credentials or valuable uncommitted work.

| Scenario | Expected result and required evidence |
| --- | --- |
| Missing or denied `/dev/kvm` | Worker refuses; no TCG process and no local agent starts |
| Inadequate RAM | Clear admission failure; no controller-execution fallback |
| Existing unknown TAP or overlapping route | Network setup refuses without adopting/reconfiguring another interface |
| Missing uplink/DNS policy mismatch | Clear refusal or connectivity failure; no automatic broader network access |
| Worker root changes its firewall and IP | Direct controller/protected-prefix denial still holds; unauthorized source addresses do not escape |
| Firewall stopped | Worker/TAP dependency stops; no surviving route without policy; restore and recheck |
| Firewall reload | No transient permission widening observable in repeated connection attempts |
| Private/home/metadata/tailnet targets | Connection refusal under the production policy, including controller alternate addresses |
| Unrelated controller service opens a new port | Worker still cannot initiate access to it |
| Worker reboots, exits or hangs | Bounded shutdown/restart; persistence preserved; controller remains manageable |
| Worker root modifies `/etc` or system-layer executable | Fresh root overlay on restart; preserve evidence that `/home` was not reset |
| Worker malicious shell file under `/home` | It persists; documentation/incident procedure must not claim reboot disinfects it |
| Existing state file size mismatch, hardlink or symlink | Refuse without reformatting, resizing or following it |
| Interrupted initial disk allocation | Refuse ambiguous `.new` state; require deliberate administrator handling |
| Worker fills persistent disk and root overlay | No controller credential exposure; qualify controller disk exhaustion/recovery behavior |
| Worker emits oversized/unterminated/hostile readiness output | Bounded failure; no shell evaluation, unbounded logging or ready status |
| Controller SSH private key inspection from worker | Both controller and health private keys absent; no agent socket; only authorized public keys on seed |
| Altered worker SSH identity | Strict verification failure, no TOFU/automatic acceptance |
| Persistent keyring requires unlock after reboot | Correctly reported human-action requirement, not a false Remote-ready status |

The automated tests cover a subset of these scenarios. For the remainder, record explicit manual results or add dedicated tests before advertising the corresponding behavior. Do not relabel a checklist as completed coverage.

## Update, rollback and storage gates

Through the **real Assbox management engine**, stage a changed worker component/image generation and reboot. Verify that the controller receipt, artifact manifest and worker build marker agree, and that a retained controller generation roots one self-contained artifact with no external runtime references. The worker audit closure must not be a controller-generation symlink or runtime JSON field. Ensure the existing controller boot receipt is still valid and no worker updater has been activated.

The `worker-policy` gate must force evaluation of the worker's own assertions and toplevel. Confirm that root and agent passwords are locked, password SSH/root SSH are disabled, the runtime-key lockout exception is intentional, and the health shell resolves to its executable subpath. Its native OpenSSH fixture uses `ssh -G` on the actual generated configurations: unrelated hosts retain leading global defaults, the worker stays on port 22 with its dedicated identity, and the separate health identity uses no proxy or user command. Python source-presence checks are not equivalent to this gate.

Inject a worker boot failure and a version mismatch before the health gate. Verify that the normal `assbox-boot-check` service path does not mark the deployment successful and that the engine's pending/recovery state remains accurate. Exercise direct administrative checks as well as timer/service paths; the boot check, maintenance already-booted path and cleanup all need to refuse correctly. The native `worker-boot-gate-vm` exercises those entry points using an immutable controlled checker; it does not stand in for a real nested KVM worker.

With unattended updates disabled, make the controlled health checker fail, leave a valid pending reboot record, and enable the boot-acceptance retry timer. Restore health without manually invoking the boot check; require the timer/engine route to clear pending state and write a matching generation-and-boot acceptance record. Repeated successful retries must not re-run health or collection. Reintroducing pending intent, rebooting, changing the selected generation or having an unresolved transaction must invalidate the shortcut. Test missing, stale and malformed receipt handling separately. Verify the public worker stop/start operations pause and resume both timers without terminating an already-running engine; direct manual cleanup must still require fresh health even after a matching acceptance receipt exists.

Boot the previous controller generation and verify its worker image selection, persistent project data and version compatibility. Confirm that worker data is not silently rolled back, malformed state is not formatted, and external actions are not represented as reversible. Run the normal GC path with retained/current/pending generations and verify each referenced worker artifact is retained appropriately.

Test abrupt controller power interruption during initial provisioning, image startup and normal worker writes. Test controlled service shutdown under load. Recovery must not run controller filesystem repair against the untrusted worker disk. Record peak disk use during generation builds and retention, not just the initial installed size.

## Disable / re-enable with a real worker

Use disposable state and a worker-only/headless controller profile for this
lifecycle test; protected local Code must not remain requested without its
worker. Native None is a separate, independently gated selection. Remove sensitive controller selections through a valid transaction,
not by bypassing placement validation. See [lifecycle](lifecycle.md).

1. Configure and boot a worker with known resource settings. Write a unique
   marker inside `/home/agent` and create a throwaway Git repository. Record the
   worker SSH fingerprint, the controller's infrastructure UID/GID values and
   the state-disk size. Do not record actual provider tokens or private keys.
2. Disable through the normal Assbox transaction and reboot the controller.
   Require no QEMU worker process, TAP, worker nftables table, worker runtime
   configuration or active worker health/retry units. The infrastructure
   accounts must still exist with non-login shells and locked passwords, and
   `assbox-vmm` must no longer belong to `kvm`. Preserved state must have the
   same verified ownership and size. No agent is relocated to the controller.
3. Request the original worker selection and state size. Require its built
   candidate's storage admission to succeed before activation. Verify this
   step neither formats/replaces the home disk nor rotates the transport keys.
4. Commit/reboot through the normal process. Require the same marker and Git
   repository in the worker, the same SSH fingerprint, a successful bounded
   health check, and worker-only execution. Provider reauthentication, when
   actually required by the provider, is not permission to copy Desktop tokens.
5. Repeat with disposable malformed-state fixtures: missing infrastructure
   account, unexpected owner or permissions, mismatched disk size, interrupted
   allocation and symlink. Require a non-destructive refusal with a useful
   diagnosis. Restore only known test fixtures; never automatically repair a
   suspect disk or adopt its numerical owner as authority.

The native `worker-lifecycle-vm` isolates the account/activation/admission portion
of this sequence, including a disabled-state reboot. Its sparse disk and keys
are synthetic and it never starts a nested QEMU worker. The real-worker sequence
above remains necessary even when that native gate passes.

## Artifact retention, health isolation and machine profiles

```sh
sudo python3 tests/worker/retention-acceptance.py
```

The read-only retention probe enumerates retained controller generations, verifies each selected worker artifact's registered Nix references and hashes, and reports unique artifact bytes. It fails on a retained standalone worker-system link. Build two distinct worker generations, retain both, and verify that the old and new controller each select the right artifact. Exercise normal Assbox GC after acceptance and show that unrooted intermediate worker build outputs can be collected without breaking the retained artifacts. Additional administrator roots and `keep-outputs` settings must be recorded, not blamed on the runtime artifact contract.

The native artifact gate verifies file layout, hashes, no external backing and a one-path runtime closure; the release scanner separately builds/scans the Codex worker audit closure. For each other advertised worker selection, build `config.system.build.assboxWorkerAudit` from that deployment flake and run the same `vulnix` check. Dynamic provider downloads require separate provenance and security review.

On a disposable real worker, back up the agent's shell startup files inside the worker, set them to fail or emit noise, and prove that the root-only controller health probe still succeeds while the ordinary agent shell misbehaves. Restore the files in the worker recovery environment. Verify that the worker health account cannot run arbitrary commands or forward sockets; worker-root spoofing is outside the readiness guarantee, not an expected test failure.

Qualify q35 on x86_64 and virt on AArch64 independently. Verify graceful shutdown under write load without timeout/SIGKILL, a new worker boot ID on restart, surviving home data, and matching controller/worker generations. Source-string assertions are not runtime evidence.

The independent Desktop password-storage patch has its own [migration gate](password-storage.md). It is not a prerequisite for the worker architecture and must not be silently applied during its tests.

## Authenticated Desktop and mobile gate

Use a deliberately small throwaway repository and the actual intended account; do not change subscriptions or expose private chat content. Record application versions, workspace and authorization method without recording secret tokens.

The acceptance evidence must show:

* Worker Codex is independently authenticated using the intended subscription login, starts from the SSH login-shell PATH and is launched through Desktop's remote project interface.
* Desktop and mobile can start a worker task, review its diff, receive and approve a command, continue the same task and recover after a worker and controller restart.
* A file change and its build/test run occur in the worker, not a similarly named controller directory. The run location remains explicit after reconnect, resume and any app update.
* Worker disconnection, app-server incompatibility, failed authentication or missing tools do not trigger silent controller execution. Deliberate handoff/local tools, Computer Use, browser integrations and controller plugins are reviewed as separate capabilities.
* The chosen keyring configuration and session startup behavior permit the intended unattended use or accurately require an unlock. Backend flags alone are not evidence of encrypted or automatically available credentials.

If mobile can control Desktop but Desktop cannot execute the intended SSH project, the chained workflow fails this gate. If a worker-targeted agent can reach controller execution or authenticated controller state, this protective profile is **not approved**. A manually avoided route is not a passing substitute; a separately described operational workaround does not change this acceptance result.

No paid model request belongs in a periodic boot-health loop. Provider authentication expiry is an operational state, not grounds to fall back to a more privileged environment.

The detailed [client-routing procedure](client-routing.md) provides the
capability/location matrix, non-sensitive canaries, negative failure cases and
an unapproved evidence-record template. Use it for both Desktop and mobile
sessions. A disabled feature is recorded as disabled, never as a tested
worker capability. One prompt-injection attempt alone cannot prove absence of
an execution route.

## Release decision

Before promoting the worker as a supported security feature, require native passing code/image/network/lifecycle gates, update/rollback fault evidence, application routing evidence, resource measurements on advertised hardware, a reviewed operational recovery path and no unresolved claims that exceed the implementation.

The old-PC use case is tested with representative repositories and builds, not only an idle worker. Advertise x86_64 and AArch64 separately; a passing architecture or hypervisor combination does not qualify another. The ordinary standalone Assbox installation remains available without claiming the VM boundary.

See [proposal](proposal.md) for design decisions and [security](security.md) for permissible security claims.

## Controller-policy go/no-go record

Record exact release, nixpkgs/agent package pins, client versions, hardware, resource budget, transport and account/workspace class. Leave every unexecuted item unapproved. No credentials or personal chat contents belong in the record.

| Required observation | Pass evidence |
| --- | --- |
| Fresh installer creates one outer configuration with an explicit worker selection | Generated settings and a single managed update lifecycle |
| ChatGPT without worker, mixed controller CLI selection, missing Codex and placement bypass are refused | Rust and Nix negative gates; no mutation of running deployment |
| All six example worker CLIs can be selected independently | Positive/negative package closure and per-command version checks |
| Unqualified sensitive controller adapters are refused | Native selection rejection; no claim that their UI smoke test passed |
| Health SSH is non-root with no supplementary groups | Actual child UID/GID/cgroup evidence while probing the worker |
| Effective health/agent sshd policies match intent | `worker-sshd-policy-vm` log plus production worker `sshd -T` inspection |
| Worker becomes ready after an initial boot failure | Pending state retained, same-boot retry eventually accepts |
| Disable/re-enable preserves state without enabling controller execution | Inert stable IDs while disabled; pre-activation admission; post-reboot worker marker and SSH fingerprint |
| Acceptance quiesces retry | Timer inactive after receipt; next boot/start can rearm it |
| Candidate's actual root virtual size exceeds remaining disk budget | Pre-commit refusal; current profile and configuration remain unchanged |
| First install's target, not live medium, is space constrained | Refusal before bootloader activation |
| PAT reaches only intended staging repositories | Allowed disposable branch push and denied unrelated/private/upstream authority |
| Staging has no privileged CI/publishing route | Repository automation and integrations reviewed independently of PAT permissions |
| Optional sub-agent skill runs only worker-selected tools | No implicit package/login/billing permission; bounded delegation |
| Worker unavailable or malicious instructions request controller access | No Desktop controller shell, local file read, browser/session use or controller handoff |
| Mobile Remote reconnects without changing execution location | Tested task, approval, restart and network-loss evidence |

The worker-targeted session's routing regression test is a **security go/no-go**, not a documentation checkbox. The expected outcome is worker execution or unavailable capability, not controller tool inheritance. Package-placement tests cannot substitute for it. A successful attempt to reach controller account/session state through an intended client tool invalidates the protective claim even when QEMU never escapes.

## Capacity and disk pressure

Pure policy tests cover reserve arithmetic, small-disk refusal and the capacity
ceiling. The helper tests create actual sparse files, preserve existing data,
refuse interrupted allocation and check QEMU I/O-stop configuration. These are
not evidence of native ext4/QEMU disk-full recovery.

Run the following on a disposable native-KVM controller with independently backed
up test state. Record observations; every row is pending for this tranche.

| Case | Required result |
| --- | --- |
| Fresh auto installation | Build provisional system/image, measure the installed target filesystem, resolve a concrete 8–2048 GiB state size using the documented reserves, activate only the final system |
| Auto on existing installation | Existing disk size and nonce unchanged after configuring `auto`, including disable/re-enable; explicit different size refuses before publication |
| Smaller prepared disk | Insufficient space after provisional build refuses before bootloader activation; durable record identifies incomplete installation and preserves requested/final digests when resolved |
| Later build consumes headroom | Final admission refuses publication if resolved state/root/reserve no longer fits; no disk reformat or automatic smaller capacity |
| Sparse first boot | `stat` virtual bytes match selected capacity, allocated blocks are substantially smaller, ext4 mounts and remains writable; a real restart preserves a nonce and SSH identities |
| Interrupted provisioning | An interrupted `.new` file causes bounded refusal on retry; it is neither adopted nor silently deleted |
| Host disk full under guest writes | Use a separate bounded disposable filesystem for worker data, fill that filesystem while writing a guest nonce, observe QMP `io-error`/paused state and failed health; controller remains reachable and data is not recreated |
| Controlled recovery | Free the disposable filler, explicitly resume through private QMP, verify completed writes and nonce, then clean shutdown/restart; if recovery fails, preserve opaque disks and test the documented isolated recovery path |

Keep host/guest root, boot backup and personal data off the deliberately filled
test filesystem. Stop normal health/retry timers during fault injection and restore
their original state afterward; do not interrupt a maintenance transaction. Filling
a real controller root or macOS host disk is not an acceptable substitute fixture.
Repeat native behavior on each advertised runtime architecture. A provisioned
sparse file or a source assertion about `werror=stop` alone does not pass these rows.
