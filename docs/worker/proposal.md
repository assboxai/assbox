# Assbox isolated execution worker

## Decision

**Adopt a trusted controller and a managed execution worker. ChatGPT Desktop requires worker-only agent placement; selected coding agents, repositories, toolchains and credentials live inside one headless KVM worker.** The [controller/worker product contract](controller-model.md) defines component enforcement, installation and generalization. Standalone execution remains a separate deployment profile without a sensitive controller, not a ChatGPT controller fallback.

The implementation included with this proposal uses Assbox's existing pinned nixpkgs, NixOS image builder, QEMU/KVM and systemd. It does not introduce microvm.nix, libvirt, a new flake input, a credential broker, a remote desktop stack, or a separate distribution. Every optional worker agent remains independently selectable.

This is a complete design and source integration candidate, **not a claim that the NixOS image, hardware lifecycle or authenticated Desktop/mobile workflow has been executed successfully**. The available Python checks have run; the native and provider acceptance gates are explicit in [implementation status](implementation-status.md) and [acceptance](acceptance.md).

Linux ChatGPT Desktop Remote availability is a deployment premise for this proposal. It is not rejected on the basis of obsolete platform statements. The exact combination of the installed Desktop build, SSH project support, mobile Remote, account permissions and unattended keyring behavior still needs end-to-end qualification.

## 1. What this solves—and what it does not

The motivating problem is a valuable ChatGPT account whose subscription is needed for coding, while an agent receives broad execution privileges. Giving that agent arbitrary execution in the same OS account as an authenticated Desktop session creates an avoidable local credential exposure. A dedicated physical appliance alone does not separate those two functions.

The proposed boundary makes the dangerous capability “arbitrary commands inside the worker” rather than “arbitrary commands as the desktop-session owner.” A worker-root compromise should not provide ordinary access to the controller home, Desktop process state, controller keyring, administrative credentials or hypervisor management interface. This remains conditional on the controller, hypervisor and transport clients not themselves being compromised.

There are two important limits.

**A worker Codex login is still a credential.** No verified authorization contract in this proposal establishes that it can never obtain ChatGPT account-side data. Treat worker compromise as theft of every credential placed there. Isolating Desktop removes the direct local-session-theft route; it does not prove that sharing an OpenAI account is harmless. Separate accounts are an additional boundary, not something the VM renders logically unnecessary. [S2]

**SSH-project routing is a client contract to verify.** In this topology the Desktop/app host is the controller and the SSH host is the worker. Project commands and file operations are expected to run in the worker; the terminology does not imply that a remote session inherits controller-local tools. Assbox verifies other executable capabilities as worker-resident or unavailable, and refuses any regression that grants the worker-targeted agent controller-local authority. This is a negative routing test, not an unresolved choice of VM architecture. Package placement alone is not proprietary application sandboxing. See [client routing](client-routing.md) and [terminology](terminology.md). [S1]

The proposal requires neither moving chat history nor changing, canceling, downgrading or transferring any subscription. It deliberately uses normal ChatGPT authentication for the worker Codex client rather than substituting independently billed API access. [S2]

## 2. Requirements

The desired user experience is an appliance, not an exercise in administering several unrelated operating systems. Once configured, one Assbox release should build the controller and worker system, keep their references together, recreate the disposable worker system layer, retain project storage, and expose straightforward health and recovery commands.

The functional requirements are:

* Preserve the user's mobile Remote workflow when the actual Desktop build supports the full phone → controller → SSH project path.
* Support an arbitrary explicit selection of eligible headless components without installing other agent applications as a convenience dependency.
* Maintain a real worker-kernel boundary, dedicated runtime SSH identities, and a controller firewall that a worker administrator cannot change.
* Fail visibly when KVM, resources, networking, image boot, authentication or remote routing is unavailable; do not quietly change the execution location.
* Integrate through ordinary `local.nix`, the component catalog and the existing verification pipeline. Keep source updates and hardware configuration in the existing Assbox model.

Availability is subordinate to the isolation contract. A controller that must automatically fall back to running an injected command locally is not an isolated appliance.

## 3. Repository fit

The catalog's `controllerAllowed`, `workerAllowed` and `requiresWorker` capabilities are enforced by Rust selection and `modules/controller.nix`. Placement cannot be disabled. First installation creates the worker selection in the outer settings; there is no separate worker installer. Only reviewed controller components are supported on a thin controller; arbitrary managed controller package additions are refused. See [placement and onboarding](controller-model.md).

The supplied tree already provides most of the application composition machinery. `modules/components.nix` owns explicit component selection, dependencies, presentation requirements and consent. `applications.nix`, `remotes.nix` and `editors.nix` implement applications and supporting services. `maintenance.nix` and `generation.nix` handle the controller lifecycle and generation metadata. `scripts/verify` provides static, Rust, mutation and native Nix stages.

The worker therefore imports the reusable component/application modules into a separate NixOS evaluation. It does **not** import the complete controller configuration into the worker. That avoids recursively creating another worker, enabling a graphical login, installing a physical-machine bootloader, inheriting controller administrative access, or running a second independent Assbox updater.

The controller retains the existing `agent` username as its controller. The worker also has an `agent` username, but it belongs to a different kernel, user database and filesystem. Renaming the controller user is not necessary for the security boundary and would add migration risk. Documentation consistently calls them **controller account** and **worker agent**.

A new controller system user, `assbox-vmm`, runs QEMU. It is not the graphical user and has no sudo grant. Administrative provisioning and TAP creation run in narrowly purposed root-owned systemd services; the VMM itself does not run as root.

Desktop password-backend migration is independent of worker deployment. The main source preserves `basic`; an unapplied libsecret patch and its own migration/reboot/rollback qualification procedure are supplied in [password storage](password-storage.md). Neither backend choice establishes a boundary against arbitrary same-user execution. The VM separates the execution domain instead. [S3]

The `chatgpt-remote` catalog entry is selectable with its Desktop dependency and X11 presentation. Its obsolete Linux blocker is removed from catalog metadata, generated Rust metadata, selection tests and user-facing documentation. Other unrelated blocked integrations remain blocked.

## 4. Architecture and trust

```text
Trusted phone / mobile ChatGPT
            |
            | Remote session
            v
Linux Assbox controller
  agent: ChatGPT Desktop, approvals, SSH client, Desktop account session
  root: Assbox configuration, release updates, firewall, provisioning
  assbox-vmm: constrained QEMU/KVM process
            |
            | controller-initiated SSH to a pinned worker identity
            v
Headless NixOS execution worker
  agent: explicitly selected agents, repositories, toolchains, provider logins
  optional worker-only sudo
  disposable system overlay + persistent /home volume
```

The single worker is one shared trust domain. Selecting Codex, Claude Code and Gemini in that worker separates them from Desktop, **not from each other**. A hostile agent can steal the other worker agents' credentials. Separate per-agent or per-project guests are a possible extension, not an implemented property.

SSH protects and authenticates the connection. It does not make worker output trustworthy. The worker controls responses, file contents, filenames, terminal sequences and app-server messages. Keep controller OpenSSH, Desktop, QEMU and the controller kernel updated; avoid controller-side evaluation of worker output. The bundled health helper bounds response size and duration and compares a narrow expected response. That check is liveness and compatibility, not cryptographic attestation.

The controller must not be used as a second unconstrained worker. Avoid controller repository checkouts that can trigger automatic tasks, local agent sessions, broad personal browser sessions, controller-side project plugins and shared Desktop/worker credential directories. Trusted administration remains possible. Development editing, editor servers and plugins belong in the worker; unqualified GUI controllers are not a supported thin-controller selection.

## 5. Why QEMU/KVM using the existing nixpkgs

A real VM is preferred over a container for this particular contract: the controller kernel should not directly be the agent's normal system-call target. This does not make a hypervisor invulnerable; it creates a different containment boundary that can be tested and maintained. QEMU's own guidance emphasizes unprivileged operation, restrictive controller resources and protecting management interfaces. [S4]

The implementation builds a complete worker system image with nixpkgs' `make-disk-image.nix`. The runner boots its kernel and initrd directly using KVM. It does not reuse a developer convenience VM that shares the controller Nix store. The worker has its own image-contained store and no 9p, virtiofs, controller-home or project-directory shares. [S5, S6]

Using the existing stack has concrete integration benefits: there is no new upstream input to add to Assbox's release authentication schema, no independent VM configuration database, no libvirt authorization surface, and no desktop virtualization application to install. The controller configuration directly references the self-contained worker artifact.

The cost is a fuller image, additional disk use, image-build work and responsibility for a small lifecycle adapter. That tradeoff is intentional. A later switch to microvm.nix could be evaluated against the same security and lifecycle tests, but is not necessary to express this first worker design. Firecracker, cloud-hypervisor, passthrough GPUs and nested desktop VMs are not required.

The supported profiles are QEMU q35 on x86_64 and virt with host GIC on AArch64. Both require native qualification. A virtualized controller must expose usable nested KVM; ordinary Assbox operation in Parallels does not establish that its worker can run. No software-emulation fallback is provided.

## 6. Storage and identity lifecycle

Controller infrastructure account lifetime follows `assbox.enable`, not worker
execution. The locked non-login VMM and health-probe accounts remain resolvable
while the worker is disabled, without worker services or VMM `kvm` membership.
This preserves reliable ownership admission before reactivation. Existing data
directory modes/owners are inspected, never normalized by tmpfiles or preparation.
[Lifecycle](lifecycle.md) specifies disablement, re-enable and recovery; S12/S13
in [sources](sources.md) document the account and directory primitives.


The immutable controller generation retains **one self-contained worker artifact**: a compressed QCOW2 base, copied regular kernel/initrd files, a bounded command line and a manifest of sizes and SHA-256 digests. The artifact has no registered runtime references to the worker's ordinary Nix closure. Internal store paths in its blobs resolve inside the worker image/initrd, not by mounting the controller store.

The build uses Nix structured output checks and `unsafeDiscardReferences` specifically for this self-contained-image case, with an empty allowed-reference set and a hard per-artifact size cap. This is justified only while every component remains self-contained: no external backing file, executable controller wrapper or symlink may be added. The native artifact gate requires a one-path runtime closure, regular files, valid hashes and no QCOW backing dependency. [S9]

The worker build closure remains separately available as `system.build.assboxWorkerAudit` for vulnerability scanning. It is **not** linked into the controller generation. Release checks scan a Codex worker explicitly because scanning the controller closure cannot inspect packages embedded in an opaque image. Additional deployed worker selections require their own scan; provider-downloaded mutable code needs separate provenance/qualification.

A SHA-256 build identifier derived from the worker system identity is embedded in the image, manifest and controller receipt. Readiness compares that identifier, not a retained controller path to the worker closure. Every worker service start creates a fresh qcow2 overlay over that base. Runtime modifications outside `/home`, including worker-root changes to system configuration or the Nix store, disappear on the next service start. The base image remains read-only by location and VMM permissions; the overlay is owned by the VMM.

The persistent disk is a sparse raw ext4 volume with fixed virtual capacity mounted at worker `/home`. It contains projects, agent state, selected provider credentials, shell configuration and ordinary caches. It is created only when absent. An existing file with unexpected size, ownership, link count or permissions is refused rather than formatted, repaired or resized. An interrupted `.new` allocation is left for an administrator to inspect.

This choice is intentionally more conservative than adopting arbitrary existing disks. It also makes changes to `stateGiB` administrative storage work rather than implicit destructive operations. Disk images are never automatically mounted or filesystem-repaired by the controller. A compromised worker filesystem must be treated as hostile data, including during recovery.

**Persistent `/home` is not a clean-room boundary.** A malicious `.bashrc`, project hook, executable or agent configuration survives reboot. Retaining `/home` after a compromise is not equivalent to reinstalling from clean sources. Incident recovery uses a new state disk and selective recovery of reviewed project data inside an isolated environment.

Worker `/nix/store` changes outside the base image are disposable. Consequently, a persistent user profile or environment pointing to store paths created after boot may become stale after restart. Durable tool requirements belong in the selected worker system or reproducible project definitions, not an assumption that every interactive `nix profile install` persists. Re-enter a project development environment after a restart. This limitation is documented rather than hidden behind a writable controller store share.

SSH identities are created at runtime, never encoded in Nix:

| Material | Controller placement | Worker availability |
| --- | --- | --- |
| Dedicated SSH client private key | Controller-owned mode 0600, in a root-owned control directory | Never supplied |
| Corresponding client public key | Used to build the provisioning ISO | `agent.pub` authorized key |
| Dedicated health private key | Root canonical copy; dedicated unprivileged health-probe copy, never owned by the Desktop account | Never supplied |
| Health public key | Used to build the provisioning ISO | Restricted key for `assbox-health` |
| Worker SSH host private key | Root-only identity directory | Read-only provisioning ISO, private file permissions |
| Pinned worker public host key | Root-managed known-hosts file | Public information |
| ChatGPT Desktop credentials | Controller Desktop/keyring state | Never copied by this subsystem |
| Codex/provider credentials | Not provisioned by the controller helper | Created by deliberate worker login; persistent `/home` |

The read-only seed ISO contains only the worker SSH identity and the authorized public controller/health keys. The worker health account has no persistent home, a fixed immutable shell, a forced command, no user RC file, no PTY and no forwarding. It does not execute the agent’s shell configuration. Worker root can still forge its answer; this is bounded readiness, not remote attestation. Its directory is traversable so OpenSSH can read the authorized-key file as the worker user; the worker private host key is root-readable only. It is normal that worker root can read that host key. Its purpose is endpoint identity, not a secret from the worker.

A compromised worker can retain its identity. Reusing the same identity during incident recovery is therefore not proof of cleanliness. Ordinary updates preserve it for predictable operation; incident recovery should explicitly rotate both dedicated transport identities and revoke affected provider credentials.

## 7. Network contract

The worker is attached to one routed TAP interface, not bridged onto the LAN. Defaults are `ab-worker0`, controller `10.77.0.1`, worker `10.77.0.2`, and a `/30` subnet. The administrator can choose another ordered pair within `10.0.0.0/8`. Existing overlapping controller routes or an already-present unknown interface cause setup refusal.

The controller creates firewall tables before bringing the TAP up. Independent input/forward chains drop worker IPv6, unexpected worker source addresses, unsolicited worker-to-controller traffic, traffic toward configured denied destination ranges and unsolicited forwarded ingress to the worker. Controller-initiated SSH replies are permitted. Stopping the controller nftables service also stops dependent worker/network units; an atomic reload is covered by the network test design.

Internet mode requires explicit physical uplink interface names. It permits public IPv4 egress through those uplinks and applies NAT to the worker's exact address. Built-in destination denials cover private ranges, loopback, link-local/metadata, carrier-grade NAT/Tailscale space, documentation, benchmarking, multicast and reserved ranges. Controller public addresses remain controller-local input and are blocked. Organizations using public prefixes internally must add those prefixes to `additionalDeniedCidrs`; the default cannot infer every protected destination.

`offline` mode keeps controller-initiated access but permits no forwarded internet traffic. It is useful for infrastructure testing or non-cloud tools, not normal cloud Codex use. Resolver addresses are validated against the selected policy; offline requires none. There is no controller DNS proxy, automatic tailnet enrollment, worker agent forwarding or worker access to controller port-forward management.

`normal` mode additionally permits private IPv4 and CGNAT destinations and private
resolvers. Direct controller input, unsolicited outside inbound, spoofed sources,
worker IPv6 and reserved/link-local ranges remain denied. Online modes require
explicit uplinks. Interactive setup requires an explicit policy choice; legacy
`--uplink` commands and the Nix default retain `internet` semantics.

**Online modes are not exfiltration filters.** A compromised worker can send its own secrets to allowed public services, including an attacker-controlled endpoint. Destination isolation blocks direct worker initiation to the controller and configured protected prefixes, not data intentionally placed in the worker. An allowed public relay, reverse proxy, VPN tunnel or hairpin route can provide indirect access to another system; the firewall does not infer the ultimate destination behind an allowed service. A strict domain allowlist or application proxy would be a different product mode with provider, package-manager, redirect, DNS and development-workflow compatibility costs. It is not partially implemented under a misleading “secure internet” label.

## 8. Desktop, CLI and mobile workflow

The normal connection method is a concrete `assbox-worker` entry in the controller's SSH configuration. The helper prepends a managed block without copying credentials into the worker or modifying unrelated SSH identities. Host-key checks are strict; forwarding of the controller authentication agent and X11 is disabled. The worker permits necessary controller-initiated loopback forwarding but no reverse tunnels or public app-server listener.

The SSH block is explicitly installed as the controller user. This is not undocumented editing of Desktop's private settings database. The user then selects the SSH host and a worker project directory through Desktop. The phone continues controlling the controller application. An installed application version may change its labels or requirements, so the acceptance procedure records actual versions and behavior. [S1]

`assbox-worker login` runs the worker Codex device-code login over SSH. The user completes authentication on a trusted device and verifies the intended account and workspace. No controller `auth.json`, cookie jar, keyring or browser profile is copied. Provider login is a human action, not a boot-time operation or a CI secret. [S2]

The example does not automatically enable unrestricted execution. Worker Codex starts from its own normal policy or a provided non-overwriting example configuration. Deliberately enabling full agent access, and optionally worker-only sudo, changes authority inside the worker; it must not change controller placement. The threat model already assumes a worker compromise and therefore does not depend on the worker remaining non-root.

Desktop must not be allowed to solve a disconnected-worker problem by running a task under “This computer.” That behavior is an acceptance criterion, not a property inferred from a successful SSH check. If the deployed client cannot enforce it, that client configuration fails the protected-controller acceptance requirement; select a client or additional containment mechanism that actually prevents the route. Do not advertise a hard controller-execution prohibition that the code does not implement.

## 9. Configuration surface

The standalone default has no worker; selecting a sensitive controller requires explicitly enabling one. `sudo assbox worker setup` supplies an interactive planning flow; `assbox worker recommend` observes RAM, CPU availability, free storage, existing state size, KVM usability and default-route interfaces. Observation never selects agents or changes the isolation mode. The normal installer is not given a second storage partitioning workflow.

`sudo assbox worker configure codex --uplink enp3s0` plans explicit placement; adding `--apply` validates the evaluated result, builds through the existing transaction and stages it for reboot. The implementation has separate domain/policy/config/system/engine/CLI responsibilities. Controller curated execution packages are removed from the managed controller selection, while only explicitly selected worker components are enabled. It does not copy any application state or infer missing component consent. Conflicting `local.nix` overrides cause refusal, not silent precedence changes.

After removing the sensitive controller selection, `sudo assbox worker disable --apply` stages a disabled worker without moving any agent back onto the controller or deleting worker data. Disabling a mandatory worker while retaining ChatGPT Desktop is rejected. The full Nix surface remains available through [`examples/worker/codex.nix`](../../examples/worker/codex.nix) and human-owned `local.nix`. Read [operations](operations.md) for migration and command details.

| Option under `assbox.worker` | Default | Meaning |
| --- | --- | --- |
| `enable` | `false` | Instantiate the worker and controller lifecycle services |
| `components` | `[]` | Explicit eligible headless catalog IDs; required when enabled |
| `allowMutableCodeFor` | `[]` | Explicit consent for selected components that download helpers |
| `allowGuestSudo` | `false` | Optional passwordless sudo in the worker only |
| `maxArtifactMiB` | `16384` | Hard cap on each immutable runtime artifact |
| `memoryMiB` | `3072` | Fixed worker RAM, bounded 2048–65536 |
| `hostReserveMiB` | `2048` | Additional physical-RAM admission reserve, bounded 1024–16384 |
| `vcpus` | `2` | Worker CPU count, bounded 1–32 |
| `stateGiB` | `null` | Required concrete capacity in hand-written Nix; CLI resolves auto after builds; existing disks retain capacity |
| `scratchGiB` | `8` | Extra capacity in the worker system image |
| `interface` | `"ab-worker0"` | Dedicated controller TAP name |
| `hostAddress` / `guestAddress` | `10.77.0.1` / `10.77.0.2` | Ordered `/30` controller pair in `10/8` |
| `uplinkInterfaces` | `[]` | Required explicit egress devices in either online mode |
| `egress` | `"internet"` | Legacy Nix default; interactive choice of `normal`, `internet`, `offline`; no content filtering |
| `nameservers` | `1.1.1.1`, `9.9.9.9` | IPv4 permitted by policy; must be empty offline |
| `happyBackends` | `[]` | Required explicit selected Codex/Claude backends for Happy Remote |
| `additionalDeniedCidrs` | `[]` | Additional protected IPv4 networks |
| `extraGuestConfig` | `{}` | Administrator-controlled worker NixOS module for toolchains/settings |

Unfree consent remains the existing machine-wide `assbox.acceptUnfree`; it is not a second ambiguous worker licensing flag. Mutable-code acknowledgements remain explicit per selected worker component. Dependencies must be selected as well; the module does not secretly install an agent because an adapter might use it.

The placement check permits only reviewed controller components (currently ChatGPT Desktop/Remote) on the thin controller, and rejects curated execution components and unqualified front ends. Managed controller package additions are also refused. This is not a whole-closure proof that no executable or bundled agent exists: administrative dependencies and Desktop itself still execute code.

There is no automatic RAM-based change of security mode. The CLI recommends 2048 MiB at 5–under-6 GiB controller RAM, 3072 MiB at 6–under-10 GiB, 4096 MiB at 10–under-14 GiB and 8192 MiB at 14 GiB or more. These thresholds use observed physical memory, not the marketed DIMM size. The administrator explicitly opts into the VM; an override must still leave the controller reserve and VMM allowance. CPU defaults retain one observed CPU where possible and cap the recommendation at four. An existing state disk must match the requested size and is never resized automatically; its still-unallocated capacity remains part of admission budgeting. On an 8 GiB machine, 3 GiB worker RAM is a trial configuration, not a measured performance guarantee. A 16 GiB machine has more room for compilation and Desktop, but still needs representative workloads tested. KVM and physical-RAM admission checks refuse insufficient setups.

## 10. Release, update and recovery behavior

The controller evaluation constructs the worker from the same nixpkgs and application inputs. Controller generation references keep its matching single runtime artifact reachable by Nix garbage collection, without pinning the ordinary worker closure alongside it. New controller generations therefore carry their own worker system rather than downloading an unrelated latest worker image at boot.

The worker does not independently run `nixos-rebuild`, an Assbox updater or image pulls. The controller remains the release authority. Assbox's existing boot-staging workflow is preferred for changes that restart the worker; a live switch can interrupt a job. Persistent project data survives, but in-flight process state does not.

Every generated controller has an immutable `assbox-worker-policy.json` receipt saying whether a worker is mandatory. The Rust engine checks that receipt against the activated runtime configuration and expected build ID, then calls its store-bound checker through an independent 110-second deadline. The helper bounds SSH responses and retries to a 90-second transport window and runs SSH under the dedicated unprivileged controller health-probe identity, not root, the controller or the worker agent shell.

Worker passwords remain locked and password-based SSH is disabled. Since authorized public keys arrive from the runtime seed rather than static Nix declarations, the worker intentionally sets `users.allowNoPasswordLogin = true` to suppress NixOS's static root/wheel lockout assertion; it does not grant passwordless SSH. The dedicated health shell is an executable subpath in a script package, not an invalid bare script derivation supplied as a NixOS shell package. The native policy gate evaluates the worker assertions and toplevel, not just controller option wiring. [S10]

Boot acceptance, maintenance's already-booted fast path and cleanup all require worker health. A failed required worker does not clear pending reboot state or prune fallback generations. The engine records a bounded root-only outcome in `/var/lib/assbox/worker-boot-status`; errors remain visible to service logs. That file is diagnostic, never authorization to skip a later check. Compatibility with a pre-worker generation is allowed only when no worker runtime is present. A dangling/unknown authority refuses.

Systemd provides startup ordering but does not suppress execution of the boot engine on a failed health-service dependency. The periodic health timer is supplementary. An acceptance retry timer, quiesced after success, re-enters the authoritative Rust boot check after transient startup or lock failures, even when updates are disabled. It never treats provider login failure as permission for local execution. The root-owned `/var/lib/assbox/boot-acceptance` receipt is published only after complete successful acceptance; it binds the exact generation and kernel boot ID. A retry can skip repeat work only with that matching receipt, no pending intent, no unresolved transaction and agreeing booted/active/selected systems. Ordinary manual checks and cleanup still require fresh health. Missing or stale receipts trigger full validation; malformed receipts refuse automatic acceptance. Readiness does not prove provider login, app-server compatibility, mobile reachability, worker integrity or entitlements. The native boot-gate test exercises failed boot checks, failed maintenance acceptance, pending-state preservation, timer-driven recovery, idempotent receipt handling, stale or damaged receipts, cleanup refusal and a replaced runtime pointer. Full update, recovery, hardware and power-loss tests remain required.

A controller rollback selects the matching older worker base. It does not roll back `/home`, external Git pushes, cloud-side actions, account settings or credential revocation. Do not couple worker data migrations to OS activation without a compatibility and backup strategy. The included layout has no automatic schema migration or automatic factory-reset feature.

## 11. Resource and availability behavior

QEMU receives fixed RAM and vCPU parameters. Its systemd cgroup limits memory to worker RAM plus a 1 GiB overhead allowance, disables VMM swap, caps CPU quota to the configured vCPU count, bounds task count and disables core dumps. These are engineering defaults requiring measurement, not promises that a large compile cannot affect controller responsiveness.

The admission check requires physical RAM for worker RAM, the controller reserve and the overhead allowance. It is not a reservation against every other controller application. A worker memory exhaustion should fail worker work rather than justify granting controller execution. Avoid double-counted controller/worker zram pools; worker zram is disabled.

The persistent home disk is sparse. After building the provisional system/image, CLI auto sizing assigns remaining space after the entire writable root, controller recovery reserve (max 32 GiB or 20% of filesystem size), and 1 GiB for final configuration derivations. Capacity stays within 8–2048 GiB. Admission checks unallocated home capacity plus the full root and reserve before publication and preparation; it does not reserve physical blocks. Writable QEMU drives stop on I/O errors for controlled administrator recovery. Retained generations still accumulate complete compressed artifacts: the design removes duplicate worker-closure retention, not the cost of storing different images. Budget persistent state + writable root virtual size + retained artifacts + peak intermediate build outputs + controller reserve. A 16 GiB artifact cap and eight retained generations can still imply up to roughly 128 GiB of worker artifacts alone. The CLI free-space floor is not this full bound and is not a filesystem quota. Nix build outputs/derivations remain until normal GC; administrators enabling `keep-outputs` or extra GC roots can deliberately retain more than the runtime closure. Disk exhaustion remains an availability risk. Qualify peak build storage and retention on the intended drive; consider a dedicated quota-controlled controller filesystem for worker data as a deployment hardening option. The proposal does not quietly repartition the user's disk.

The VM restarts after exit. Both supported profiles use bounded QMP power-button shutdown and QEMU `-no-reboot`. Require clean filesystem shutdown under load before promotion; systemd imposes a final timeout. An explicit operator stop also stops the worker health and boot-acceptance retry timers. Disabling the Nix option is persistent; interrupted writes still require the documented recovery handling.

“Set it and forget it” means managed operating-system lifecycle and observable failures, not guaranteed perpetual vendor authentication. MFA, device approval, token revocation, provider incompatibility or a password-protected keyring can require human action. No repeated paid model call runs as a health probe.

## 12. Implementation inventory

| File | Responsibility |
| --- | --- |
| `modules/worker/default.nix` | Options, separate evaluation, image references, SSH template, VMM user, firewall, systemd units and immutable boot-health receipt |
| `modules/worker/guest.nix` | Minimal worker, component selection, storage mounts, seeded OpenSSH, unprivileged agent and optional worker sudo |
| `nix/worker-image.nix` | Self-contained compressed artifact and independent audit output |
| `crates/*/*/src/worker.rs` | Worker domain, resource policy, settings renderer, observations and command flow |
| `assbox-engine/src/manage.rs` | Atomic staging, boot/maintenance/cleanup acceptance |
| `tests/nix/worker-artifact.nix` | One-path runtime closure, regular layout and hashes |
| `tests/nix/worker-boot-gate-vm.nix` | Actual engine failure/success and pending-state checks |
| `scripts/worker/worker.py` | Bounded fixed-purpose lifecycle, identity provisioning, disk refusal logic, SSH setup and readiness checks |
| `examples/worker/*.nix` | Codex, explicitly multi-agent, and offline configurations |
| `tests/worker/test_worker.py` | Python functional, refusal, bounded-output and source-contract tests |
| `tests/nix/worker-policy.nix` | Native module assertions and rejection scenarios |
| `tests/nix/worker-network-vm.nix` | Controller production firewall rules exercised against a root-capable peer |
| `tests/worker/kvm-acceptance.py` | Operator-triggered test of the actual production QEMU worker, persistence and basic separation |
| `flake.nix`, `scripts/verify` | Native worker checks and Python tests added to the existing gate |

The user-facing `assbox worker` hierarchy plans/configures the subsystem through Rust. It delegates fixed runtime operations to the separately packaged `assbox-worker` executable, also used by systemd. The core worker specification, resource policy and managed settings renderer have Rust regression tests; hardware observations and immutable receipt checks remain in the imperative shell. Privileged internal commands are invoked by systemd; the controller is not granted arbitrary service management, root helpers with user-chosen paths, or hypervisor access. The file is small enough to review as an explicit trust boundary and uses standard-library Python plus fixed store-path executables.

## 13. Acceptance and rollout

Begin with `vim` in an offline worker on a disposable native-KVM controller. Verify image construction, boot, SSH identities, controller isolation, state persistence and failure behavior without introducing a provider credential. Then validate the public-egress policy in the automated hostile-peer network test and on the physical target. Only then authenticate Codex and qualify Desktop/mobile routing.

The normal qualification sequence is: static and metadata checks; native module evaluation; image build; automated network VM checks; the actual KVM lifecycle test; representative x86_64/AArch64 hardware where supported; authenticated Desktop/SSH/mobile approval and restart tests; update/rollback/GC fault tests. All are enumerated with expected evidence in [acceptance](acceptance.md).

Opt-in availability is appropriate before making this the suggested configuration for all capable hardware. A default recommendation should require measured memory/disk behavior and a demonstrated remote-only execution workflow. Controller compatibility mode must remain visibly different. No automatic migration, data deletion, identity rotation or subscription change belongs in enabling the option.

The proposal is successful when an Assbox owner can use their desired mobile workflow with a clearly identified remote execution location, tolerate unattended OS updates, recover a broken worker without exposing controller secrets, and understand the remaining account-token and local-tool risks. It is not successful merely because a VM process appears in `systemctl`.

## 14. Release blockers and explicit non-goals

Native Nix evaluation/build, architecture-specific KVM execution, boot-engine failure integration, keyring reboot behavior, provider authentication and mobile routing require empirical qualification. The package includes code and procedures to obtain that evidence; it does not supply a passing result for unexecuted gates.

A hard policy that prevents every Desktop-local agent action is not implemented here. Multiple isolated workers, GPU/USB passthrough, controller↔worker shared folders, domain-allowlisted egress, transparent credential brokers, automatic account migration, automatic state-disk expansion, encrypted unattended key unsealing, and unattended compromise detection are also not included. Each would need a separate design rather than a permissive shortcut through this boundary.

**Recommendation: integrate this controller/worker architecture, qualify it against the included gates, and describe its security benefit precisely: agent execution can be separated from the authenticated Desktop OS session. Do not turn that into an unsupported guarantee about all account-side access or every tool available inside Desktop.**

## References

[S1]–[S6] and the repository evidence index are in [sources](sources.md). Detailed operating procedures, the threat model, gate definitions and observed validation status are separate companion documents to keep the proposal usable as an implementation decision record.

## Controller integration and operational guarantees

Root validates local policy, then the SSH health child drops to controller `assbox-health-probe` with no supplementary groups and a cleared environment. The health key is accessible only to that account and administrative provisioning, not the graphical controller or VMM. This minimizes a malicious worker's protocol-parser attack surface without pretending the worker's answer is attestation.

The boot-retry timer stops after successful acceptance; its generation/boot receipt prevents repeated cleanup. Failed readiness remains retryable on the same boot. The routine health timer continues. Built-artifact disk admission runs before transaction publication and activation, and runtime preparation repeats it. Fresh installation measures the target filesystem after build. These checks do not prevent another process consuming disk space afterward.

`worker-sshd-policy-vm` evaluates the actual worker-generated configuration with OpenSSH `sshd -T -C` for both users. It checks the health forced command, no PTY/forwarding/RC, agent loopback-only forwarding and global password/root login restrictions. It is a defined native gate, not an observed pass in the delivered validation record.

The preferred repository and credential model is [selected staging repositories and a fine-grained PAT](git-workflow.md). Native GitHub forks have additional shared-network semantics; do not promise an account or repository boundary without inspecting effective permissions and CI integrations. Promotion remains outside both worker and controller.
