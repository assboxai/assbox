# Worker installation, operation and recovery

## Before enabling

**Roles:** controller = Linux system running Desktop/QEMU; worker = managed VM
running the SSH server and agents; mobile client = phone/tablet controlling
Desktop. The normal user manages only the outer Assbox installation. See
[terminology](terminology.md).

The [controller/worker policy](controller-model.md) applies when protected local Code or an explicit worker is selected. Native None can be staged without a worker but still requires exact native-policy qualification. First installation proposes and confirms protected execution resources in the outer wizard. The procedures below cover explicit administration of the same controller-owned subsystem, not installing a second OS manually. [Scoped Git onboarding](git-workflow.md) is the recommended repository workflow.


Read the [security contract](security.md). Use a disposable test appliance first. The NixOS module and actual KVM image have not been runtime-qualified by the artifact's Python test run.

The Assbox release selected by `/etc/nixos/flake.nix` must contain this worker subsystem. Editing `local.nix` against an older release that does not export `assbox.worker` will correctly fail with an unknown-option error. For development, follow the repository's ordinary local-source workflow; for deployment, use a release that has passed the worker acceptance gates. Do not substitute an unsigned local source into an unattended production update path without explicitly taking responsibility for that change.

Confirm usable native KVM, enough RAM and disk capacity, and the real network interface names:

```sh
ls -l /dev/kvm
free -h
df -h /var/lib /nix/store
ip -brief link
ip -4 route
```

A controller running inside another VM needs nested virtualization that actually exposes `/dev/kvm`. The worker will not emulate a worker in software or execute on the controller instead. Native AArch64 support is conditional on its KVM and worker device acceptance tests.

The default 3 GiB worker requires at least worker RAM + 2 GiB controller reserve + 1 GiB VMM allowance in the physical-RAM check. That is an admission minimum, not a responsive-workload guarantee. Persistent home has a fixed virtual capacity and sparse physical allocation; worker images, overlays, retained generations and builds require additional space.

Worker disablement retains inert infrastructure identities as well as existing
worker data. The accounts do not keep worker services or device privileges
active. Read [disable/re-enable and ownership recovery](lifecycle.md) before
retiring or restoring a worker; disabling is not a reset or token revocation.

## Plan and configure through Assbox

```sh
sudo assbox worker recommend
sudo assbox worker setup
```

The setup flow asks for explicit component IDs, networking, memory, persistent state and any required consent. Its first step is a plan; a separate affirmative answer is required to build and stage. It does not automatically choose Codex, authenticate it or copy controller files.

For repeatable noninteractive use (replace `enp3s0` with the intended observed interface):

```sh
sudo assbox worker configure codex --network normal --uplink enp3s0 --memory auto
sudo assbox worker configure codex --network normal --uplink enp3s0 --memory auto --apply
```

The first command prints a plan only. `--apply` uses the ordinary Assbox candidate/build/boot transaction. Reboot through the normal procedure before expecting the worker tools. Incompatible curated controller selections must be explicitly removed before configuring the worker; this command does not remove them automatically. Managed additional controller packages must be removed first. Unqualified sensitive desktop applications stay staged and cannot launch through their managed entry points. The specified worker IDs are not an implicit copy of the old selection. Existing repositories and credentials are untouched. This does not disable an editor's or Desktop's bundled local tools.

Happier uses `happier,happier-daemon` with independently selected coding CLIs. There is no backend-list option. Consent to client-managed helpers is scoped to the selected components; pairing and provider authentication remain separate.


### Capacity and network policy

New worker capacity is computed after building the provisional controller/image
closure. From available filesystem space, reserve the full writable root size,
**the larger of 32 GiB or 20% of filesystem capacity** for controller builds and
recovery, and another GiB for final configuration derivations. The remaining whole
GiB become `/home` capacity, within the existing 8–2048 GiB supported bounds.
Insufficient capacity is refused. The final system is built and admitted before
publication/bootloader activation. The extra provisional toplevel is never booted;
its worker artifact and packages are reused by the final build.

`home.raw` is sparse: it grows physically as the guest writes, up to its fixed
virtual capacity. This is not ongoing automatic resizing, a quota or a space
reservation. Admission still budgets its unallocated capacity and the full root
overlay, plus a fixed 8 GiB emergency floor. The larger sizing reserve is usable
for subsequent controller generations and other growth; admission does not require
it to remain untouched. Other controller writes, retained builds, and the outer
hypervisor disk can exhaust storage later. Existing state is never resized or reformatted by
`auto`; an explicit different size is refused. Hand-written Nix requires a concrete
`stateGiB`, rather than observing live disk space during evaluation.

The interactive installer/setup requires a network choice without silently
selecting one:

| Policy | Direct outbound IPv4 | DNS |
| --- | --- | --- |
| `normal` | Internet and LAN through explicit uplinks | Public or reachable private resolvers |
| `internet` | Public destinations; protected ranges denied | Public resolvers |
| `offline` | No external forwarding; controller-initiated SSH remains | Empty resolver list |

Online policies require explicit uplink interfaces. `--dns ADDRESS` can be repeated;
public defaults are `1.1.1.1` and `9.9.9.9`. Normal permits private Git/services/DNS,
but all policies still block unsolicited traffic into controller services, inbound
connections from outside, spoofed worker addresses and worker IPv6. Link-local,
metadata and other reserved ranges remain denied. Resolver addresses on the worker
link are refused. None of these policies prevents exfiltration through allowed
services, and indirect access through an external relay is not ruled out.

Compatibility is deliberate: old `--uplink NAME` commands without `--network`
continue to mean `internet`; `--offline` remains an alias for `--network offline`.
Existing generated Nix policies and capacities are not broadened or resized by an
update. For a fresh normal network, use `--network normal --uplink NAME` explicitly.

The worker uses q35 on x86_64 and virt on AArch64. KVM and placement restrictions are mandatory; no experimental machine or isolation-bypass switch is exposed.

The CLI writes only its bounded managed block in `assbox-settings.nix` and the standard controller component selection. It refuses ambiguous edits and checks the evaluated candidate for conflicting local placement/resource/consent overrides. Keep handwritten Nix in `local.nix`. Protected local Code cannot retain its requested mode while its worker is disabled. First change the native policy to None or remove the sensitive selections through an explicit configuration transaction, then use `sudo assbox worker disable --apply`. Native None remains independently gated. No controller execution fallback is enabled and no worker state is deleted.

## Configure through `local.nix`

Merge [`examples/worker/codex.nix`](../../examples/worker/codex.nix) into the machine's existing `/etc/nixos/local.nix`. Do not overwrite hardware configuration, storage binding, existing local customizations or account state. Set `uplinkInterfaces` to the actual physical interface or interfaces, not a placeholder, the TAP, or an assumed `eth0`.

A typical selection is:

```nix
{ lib, ... }:
{
  assbox.presentation = "x11";
  assbox.acceptUnfree = true;
  assbox.components.chatgpt-desktop = {
    enable = true;
    allowMutableCode = true;
  };
  assbox.components.chatgpt-remote.enable = true;
  assbox.session.autostart = [ "chatgpt-desktop" ];
  assbox.components.codex.enable = lib.mkForce false;

  assbox.worker = {
    enable = true;
    components = [ "codex" ];
    memoryMiB = 3072;
    vcpus = 2;
    stateGiB = 128; # Example only; choose a capacity that leaves recovery space.
    egress = "normal"; # Deliberate internet + LAN access.
    uplinkInterfaces = [ "enp3s0" ]; # Replace with the appliance's real device.
  };
}
```

The example makes an explicit choice to accept the existing unfree/mutable-code requirements. It is not a recommendation to bypass an organization's licensing policy. Worker agent selection and controller Desktop selection are separate. An existing controller selection of other coding agents will fail the default placement assertion until deliberately moved. Placement cannot be disabled.

Use the normal administrative workflow:

```sh
sudo assbox config edit
sudo assbox check
sudo assbox rebuild --boot
```

Complete the controlled reboot through the normal Assbox procedure. `--boot` is preferred for this change because a live switch can restart the worker and interrupt tasks. Ordinary `nixos-rebuild` is still supported as documented in [configuration](../configuration.md), but do not run it concurrently with Assbox management operations or assume it creates Assbox's pending/recovery markers.

An offline infrastructure-only selection is provided in [`examples/worker/offline.nix`](../../examples/worker/offline.nix). Qualify that without any provider credential before testing a paid agent workflow.

## First boot and transport setup

The controller starts provisioning, firewall/TAP setup, the VMM and health checks. Inspect as the administrator:

```sh
sudo systemctl status assbox-worker.service assbox-worker-health.service
sudo journalctl -b -u assbox-worker-provision -u assbox-worker-network -u assbox-worker --no-pager
sudo assbox-worker check
assbox-worker status
```

Provisioning does not log into OpenAI. A successful health check means the expected worker is reachable over the dedicated SSH transport, not that Codex is authenticated or Desktop has selected it.

Install the SSH alias as the **controller account**, not as root or the worker user:

```sh
sudo -H -u agent /run/current-system/sw/bin/assbox-worker setup-ssh
sudo -H -u agent /run/current-system/sw/bin/ssh -G assbox-worker
```

Check that the resolved worker address, port 22, user, identity, known-hosts path and forwarding settings match `/etc/assbox/worker-ssh-config`. The helper preserves unrelated text, rejects a conflicting explicit alias and refuses suspicious symlink/hardlink state. The managed block restores `Host *` before existing text, so leading global defaults retain their scope. Setup checks OpenSSH’s effective configuration, including the system configuration, before installing the alias. Accumulated identities, certificates and automatic forwarding cause refusal; scope unrelated settings under other aliases or `Host * !assbox-worker`. Doctor repeats the check as the unprivileged controller, even when invoked by root. Controller-authored Include/Match rules can execute commands as that user during inspection; they are never evaluated as root. The application may add its deliberate loopback tunnel at invocation; the helper does not use `ClearAllForwardings` to silently break that transport. This configuration merge is not a sandbox for arbitrary controller-authored SSH configuration. Do not weaken strict host-key checking or answer a changed host key by disabling verification.

The controller directory `/var/lib/assbox-worker-control` is root-owned. Its private client key is owned by the controller and mode 0600. The worker receives only the client public key, the health public key and its own SSH server identity. No authorized reverse path into the controller is installed.

## Authenticate Codex in the worker

Start login from the trusted controller session:

```sh
sudo -H -u agent /run/current-system/sw/bin/assbox-worker login
```

This executes `codex login --device-auth` inside the worker. Open the printed authorization URL in a trusted browser on the controller, mobile client or another computer, sign in to the intended account/workspace, and enter the worker-displayed one-time code on that page. Codex waits for authorization; there is no returned code to paste into the TUI. The relevant device authorization feature may need to be enabled in the account. Do not type the account password into an untrusted worker page, copy controller cookies into the worker, or copy the controller's complete Codex auth cache. [S2]

Check the worker directly:

```sh
sudo -H -u agent /run/current-system/sw/bin/assbox-worker shell
```

Inside that shell:

```sh
hostname
cat /etc/assbox/worker-role
id
command -v codex
codex login status
mkdir -p ~/projects
```

Expected hostname is `assbox-worker`, role is `execution-worker`, and user UID is 1000. These are operating checks, not proof that an already-compromised worker is honest.

The sample `/etc/assbox/codex-example.toml` is provided for inspection. It does not overwrite an existing configuration. For a new worker profile, it can be copied deliberately with private permissions:

```sh
install -d -m 700 ~/.codex
# Only for a new configuration; retain/review an existing file instead.
test -e ~/.codex/config.toml || install -m 600 /etc/assbox/codex-example.toml ~/.codex/config.toml
```

Credentials persist in worker `/home`; the design treats them as exposed if the worker is compromised. Do not place provider tokens in `local.nix`, environment text in the Nix store, the provisioning ISO, commits or diagnostics.

## Connect Desktop and then mobile

On the controller, sign into ChatGPT Desktop normally. Add or enable `assbox-worker` through the application's SSH connections settings and choose a project under the worker's `/home/agent/projects`. The worker `codex` executable must be on the login-shell PATH; the app starts its remote app server over SSH. Do not publish an app-server TCP listener on the LAN. [S1]

Pair the mobile app through the actual Desktop Remote setup. Confirm the desired account and workspace. Do not edit undocumented Desktop storage or invent command-line pairing endpoints. The Linux app's actual labels and permissions may differ across builds; the target's working Linux Remote capability is accepted, but the entire chained route must be demonstrated.

For the first task, use a disposable repository and ask for a trivial file change plus a harmless identity check. Verify the file exists **inside the worker**, review its diff and complete a command approval from the phone. Then disconnect the worker and verify the task does not move to controller execution. Avoid private chat history in test prompts.

Keep controller Computer Use, browser automation, local plugins and local agent tasks disabled or unconfigured for this operating mode. An SSH project is expected to use the worker; a generic reference to host tools is not evidence that Desktop supplies controller tools to it. Run [client-routing acceptance](client-routing.md) to verify every enabled tool is worker-resident or unavailable, including reconnects and failure handling. Do not register a controller-side project for the worker repository or manually hand the coding chat back to the controller.

## Normal operations

| Command | Run as | Purpose |
| --- | --- | --- |
| `assbox worker status` | Controller or admin | Service state, selected worker components, expected generation; no auth claim |
| `sudo assbox worker check` | Root | Bounded transport/generation probe |
| `assbox worker shell` | Controller account | Interactive SSH into worker |
| `assbox worker login` | Controller account | Explicit worker Codex device login |
| `assbox worker setup-ssh` | Controller account | Install/update the concrete alias |
| `sudo assbox worker stop` | Admin | Stop worker, health timer and boot-acceptance retry |
| `sudo assbox worker start` | Admin | Start worker, health timer and boot-acceptance retry |

`sudo assbox worker doctor` checks artifact hashes, service state and the dedicated health transport without opening provider credentials. Inspect `/var/lib/assbox/worker-boot-status` as root for the latest bounded health-gate outcome; service logs contain the error. A ready infrastructure probe does not establish provider/mobile readiness.

The `internal-*` commands are systemd implementation entry points, not a supported arbitrary privileged API. No new sudo or polkit privilege is granted to the controller or worker.

Stopping only `assbox-worker.service` while leaving its health timer active can cause a later check to start it again. Use the public `stop` command for an administrative pause. While an enabled worker is intentionally stopped, required-worker acceptance and cleanup will fail closed rather than waive its health requirement. A pause is not permanent across every controller reboot or activation; retire the sensitive controller selection and disable `assbox.worker.enable` in a deliberate configuration change for a persistent policy change.

If nftables is deliberately stopped, the dependent worker/TAP services stop as well. After restoring the firewall, use the normal start command and recheck readiness. Atomic reload is the preferred ruleset update path; it has a separate network acceptance test. Never temporarily turn off the controller firewall to make a worker connection succeed.

## Automatic boot acceptance recovery

The ordinary `assbox-boot-check.timer` remains a one-shot boot trigger. With worker boot acceptance enabled, `assbox-worker-boot-retry.timer` invokes `assbox internal boot-check --retry` after approximately three minutes and then five minutes after the preceding run ends. It also works when unattended updates are disabled. The engine uses the same nonblocking operation lock, generation agreement, pending-reboot checks and bounded health gate as an explicit boot check. A transient lock collision or unready worker remains unaccepted and is retried; the retry service itself has no dependency that starts the worker.

Only after a successful full boot acceptance does the engine write `/var/lib/assbox/boot-acceptance` atomically with mode 0600. It binds success to the exact system generation and kernel boot ID. A retry may avoid repeating health/cleanup only while that record matches, no pending intent exists, and no unresolved transaction or generation disagreement is present. Ordinary health, manual boot checks and cleanup do not use this shortcut. The record is a historical acceptance result, not current service health, worker attestation, or provider authentication.

Inspect this path when a boot remains unaccepted:

```sh
sudo systemctl status assbox-worker-boot-retry.timer assbox-worker-boot-retry.service
sudo journalctl -b -u assbox-worker-boot-retry --no-pager
sudo cat /var/lib/assbox/worker-boot-status
sudo cat /var/lib/assbox/boot-acceptance
```

A missing or stale acceptance record triggers full validation. A malformed record is refused on the retry route; diagnose the state rather than editing it into a success marker. After resolving the underlying fault, `sudo assbox internal boot-check` performs full validation and can publish a valid record. Never remove an unresolved transaction or pending-reboot file merely to suppress an error. The public worker stop/start commands manage both timers so an intentional pause is not confused with a transient boot failure. A stop does not terminate an already-running acceptance engine, which may own a durable transaction; that operation finishes or fails normally. Do not kill it to accelerate a pause.

## Development tools and multiple agents

Durable toolchains belong in a project definition and/or `extraGuestConfig.environment.systemPackages`. They do not require a controller Nix-store mount. Recreating the root overlay removes worker `/nix/store` additions made after boot. A saved user profile can therefore reference store paths that are gone after restart. Rebuild/re-enter the reproducible project environment instead of depending on such paths surviving.

Keep repository contents under the persistent worker home. There is no controller shared project directory. Clone from the source repository inside the worker using only intentionally scoped credentials. Review imported uncommitted work as data; do not run import scripts on the controller. Do not migrate the whole controller home, `.config`, browser profile, keyring, SSH directory, `.codex` directory or package-manager credential directory.

The multi-agent example selects each runtime and each remote-editor backend explicitly. These agents share the worker. Put only credentials whose combined exposure is acceptable in a shared worker; per-agent isolation is not provided. Optional IDE controller adapters are not qualified by installing their worker backends and are not part of the thin ChatGPT controller profile.

## Storage admission and retained generations

A controller generation retains only its runtime artifact, not also the full worker build closure. Each different artifact is still a complete compressed image plus kernel/initrd. Intermediate build outputs and explicit audit results can remain in the store until GC, and additional administrator GC roots/`keep-outputs` policies can retain them longer. The artifact cap is not a global disk quota.

Measure build peak, steady state, a fully dirtied writable root, retained artifacts and backup capacity on the actual drive. Use `sudo python3 tests/worker/retention-acceptance.py` from the source tree to inspect retained runtime references and stored artifact bytes; it makes no deletions. The default maximum is 16 GiB per artifact, not an estimate of typical image size. Do not base a small-SSD recommendation on RAM alone.

## Updates, backups and storage changes

Stage controller changes with the ordinary Assbox workflow. The new controller generation carries its matching self-contained worker artifact and immutable worker-health receipt. Keep old generations until the documented update and rollback tests pass. A generation rollback changes the OS base; it never reverses `/home` data or external actions.

For a consistent worker-state backup, use `sudo assbox worker stop` to stop the worker and both health/acceptance timers, confirm the service is inactive and the QEMU process is gone, then copy `home.raw` as an **opaque file** into appropriately protected backup storage. Do not mount it on the controller or run filesystem tools against it there. Include the transport identity directories only when the backup policy deliberately requires identity continuity, and protect those private keys accordingly. Never publish backups in build artifacts.

The proposal does not implement an automatic backup service, encrypted backup backend, online filesystem snapshot or retention scheduler. Existing project remotes are useful but do not replace a backup for uncommitted data. Choose and test a backup policy before relying on the worker for valuable work.

Changing `stateGiB` will refuse an existing differently sized disk. There is no automatic resize. For routine growth, prefer a planned offline migration: create a new worker state disk of the desired size, copy selected verified data within a disposable migration VM, reauthenticate and validate, then retain the old disk until recovery has been tested. Never point the helper at a controller block device as a shortcut.

An interrupted `home.raw.new` is a deliberate stop condition. Confirm no worker process is running and establish whether the file is only an incomplete allocation before an administrator removes or quarantines it. The helper cannot safely infer whether an unexpected file is expendable.

## Incident response

1. From the trusted controller administrator, run `sudo assbox-worker stop`. Confirm that the VM, health timer and boot-acceptance retry timer are inactive. Preserve relevant controller-side service logs without publishing tokens or worker content.
2. Treat all provider, Git, package, SSH and cloud credentials that existed in the worker as compromised. Revoke or rotate them through trusted provider interfaces. Clearing a worker login file is not proof of remote revocation. Consider the broader OpenAI account risk; this design has no verified token-scope guarantee.
3. Quarantine the persistent disk and transport identities as sensitive opaque files, without controller mounting or executing their contents. Build a fresh worker state from the approved controller generation, rotate its dedicated transport identities, and recover only reviewed project data inside an isolated recovery environment. Re-pair/reselect the worker as needed and complete the acceptance checks before reuse.

A normal OS rebuild with the same `/home` is not this recovery procedure. There is intentionally no one-command destructive reset in the supplied helper. Administrative manual quarantine/recreation must be deliberate, offline and backed by a recoverable copy. Do not delete a disk merely because it has the expected filename, or reuse an entire compromised home for convenience.

## Troubleshooting without weakening the boundary

A missing KVM device, disabled firmware virtualization or unavailable nested virtualization requires fixing the deployment target, not switching to controller execution. A route-overlap error requires choosing an unused `/30`. A DNS/egress failure requires reviewing resolvers permitted by the chosen network policy and actual uplinks, not adding the TAP to a globally trusted firewall list. A host-key mismatch requires investigating identity lifecycle, not `StrictHostKeyChecking=no`.

A correct infrastructure health result with failed Desktop tasks may indicate worker login-shell PATH, provider auth, app-server version, account permissions or application routing. None is diagnosed by dumping the controller keyring. A keyring prompt after reboot may be expected when a password is set; changing password-backend flags does not prove unattended unlock. Read [acceptance](acceptance.md) and keep the failure classified accurately.

Sources: [S1] and [S2] in [sources](sources.md).

## Explicit multi-agent selection

[`multi-agent.nix`](../../examples/worker/multi-agent.nix) selects Codex, Claude Code, Grok, Antigravity CLI, Cursor Agent, OpenCode, Pi and OMP inside the same worker. It is an example for a user who deliberately wants those tools, not the default. Each provider requires its own appropriate login and may have independent billing/limits. Assbox does not automatically authenticate sub-agents or forward the primary agent's credentials.

Optional delegation skills and orchestration conveniences are deferred. Selected worker CLIs remain independently usable; they share one compromise domain.

## Acceptance retry and capacity

The boot-retry timer is temporary: it stops once the engine has published a generation/boot-ID acceptance receipt. The ordinary worker health timer stays periodic. Explicit `start` and subsequent controller boots can arm retry again; routine successful retries do not wake forever. A failed health check must preserve pending state and retry rather than authorize controller execution.

Candidate admission runs after the image build and before publication/profile activation. It uses actual root virtual bytes, allocated persistent-state requirements and free space. The live installer checks its target filesystem before activating the bootloader. Preparation repeats the check at start. Leave additional capacity for concurrent builds and retained generations; these are checks, not reserved space or disk quotas.
