# Implementation and validation status

## Scope and release status

**Architecture: accepted controller/worker model. Source: integrated implementation candidate. Native and end-to-end qualification: outstanding.**

Protected local Code uses a trusted, thin Linux controller with one managed headless KVM worker. The outer Assbox configuration generates and manages the worker; the user does not install a second Assbox. Native None can be staged without a worker and requires exact no-local-execution verification. Sensitive controller selection cannot place coding-agent CLIs on that controller. Standalone execution remains the normal default.

This tree uses **direct QEMU/KVM and the existing pinned nixpkgs**. It does not add microvm.nix or require a new flake input.

| Area | Implemented in this source |
| --- | --- |
| Product architecture | Catalog placement capabilities, Rust and Nix validation, derived controller profile, controller/worker installer selection, managed-package rejection and no silent controller-execution fallback |
| Managed worker | Image generation, private network, runtime SSH identities, persistent home disk, disposable root overlay, service lifecycle, authentication and shell helpers |
| Optional agents | Independent worker selection of Codex, Claude Code, Grok, Antigravity CLI, Cursor Agent, OpenCode, Pi and OMP; one shared filesystem and credential trust domain |
| Artifact retention | Self-contained packed system/kernel/initrd/boot manifest, size limits, native runtime-reference gate and separate build-only worker audit closure |
| Health isolation | Root validates local policy; network-facing SSH runs as the dedicated unprivileged controller `assbox-health-probe` account with cleared supplementary groups/environment; separate immutable worker health identity |
| Disabled-state ownership | Locked non-login infrastructure identities retained while Assbox is enabled; no worker resources or VMM `kvm` membership while disabled; admission before reactivation can verify existing ownership |
| State directory integrity | Create-only provisioning; unexpected existing directory ownership or permissions are refused, not normalized by tmpfiles or preparation |
| Storage admission | Actual built manifest and current storage checked before candidate publication, on the installation target before bootloader activation, and again before VM preparation; malformed or ambiguous existing state refused |
| Maintenance acceptance | Worker health enforced before acceptance, pending-state removal and cleanup; generation/boot-ID receipt; failed acceptance retries; retry timer stops after success while routine health remains periodic |
| Transport | Fixed launcher, non-root VMM, constrained service, no configured controller filesystem or credential-socket shares, pinned SSH identities and standard SSH/Git/rsync access |
| Networking | Explicit normal/internet/offline choice, matching DNS, controller and unsolicited-inbound denial in every mode; permitted egress is not an exfiltration barrier |
| Release audit | Separate vulnerability scanning of image-contained worker closures, including configured worker-enabled release targets |
| Native gates | Module/worker assertions, artifact closure, effective worker `sshd -T` policy, boot-state behavior, networking, disabled-state activation/reboot and actual-KVM acceptance procedures |
| Git onboarding | Recommended fine-grained PAT limited to selected agent/staging repositories, independently reviewed CI, and human promotion from a separate trusted workstation or service |
| Password backend | Existing backend retained; libsecret migration is deferred and no optional patch is shipped |

The source includes the Rust management and installer integration, not merely Nix examples. However, presence of these code paths is not evidence that they compile, build or execute successfully on the target. A controller's final SSH-project selection in Desktop remains a documented one-time user step; Assbox does not edit undocumented application databases.

No automatic `worker reset`, `backup`, `copy`, `git-login` or `enable` command is supplied. Standalone Assbox is now an explicit installer arrangement with independent workload SSH, optional manual Chromium/X11/Wayland and additional tools. The Parallels guide covers an external macOS ChatGPT controller without nested KVM. Assbox does not manage that external controller, guest GUI automation, or multiple workers. Use [operations](operations.md) for the actual command interfaces.

## Routing contract and terminology

Operator documentation uses controller, worker and mobile client. Upstream
Desktop/app host maps to the controller; SSH host maps to the worker. Stable
Nix options, SSH directives and diagnostic keys keep their existing spelling;
[terminology](terminology.md) maps them explicitly.

The [client-routing procedure](client-routing.md) treats worker execution as the
expected SSH-project behavior and tests reconnects, failures, handoffs and every
enabled capability for worker execution or unavailability. These are required
regression observations, not evidence that upstream documentation assigns
controller tools to a remote project. No adapter is runtime-qualified by this
source package.

## Candidate checks — October 2, 2026

The current product tranche uses the purpose-first wizard, eight curated coding
CLIs, independent provider service contracts and strict native activation gates.
See [candidate status](../implementation-status.md) and the complete
[qualification ledger](../../qualification/README.md). Earlier baseline test totals
are not acceptance results for this source. The small Rust core, bounded identity
and native-policy fixtures, cached module tests and static checks are distinct
from package builds, runtime networking and authenticated Desktop routing.

## Deferred qualification

Heavy checks are deliberately deferred while other work runs on the development
machine. No Actions runs, production activation or provider logins are part of
this integration. Do not interpret deferred checks as absent requirements.

- Full static suite, release-closure compilation/tests, mutation checks and refreshed coverage.
- Nix evaluation, system and image builds, artifact closure and separate worker vulnerability scans.
- Native worker policy, SSH-server, networking, boot-acceptance and lifecycle VMs.
- Real KVM worker boot, persistent home, shutdown under load, disable/re-enable,
  interruption recovery, update/rollback and retained-generation GC.
- Resource measurements and physical Intel MacBook qualification.
- Actual Linux Desktop/SSH/mobile routing and provider authentication with synthetic data.

The current development host lacks `/dev/kvm`. Emulated test VMs can exercise
some gates later, but cannot establish production-worker KVM behavior. Tests using
synthetic sparse disks or an immutable fixture health checker must remain labeled
as such. Source assertions do not replace actual lifecycle or packet tests.

Prior successful Assbox results apply only where their inputs are unchanged.
Worker placement and maintenance integration affect existing gates; the old green
matrix is not a pass for this candidate. Follow [acceptance](acceptance.md) and
[client routing](client-routing.md) before recommending unattended production use.

## Boundaries that remain conditional

**Placement is not application sandboxing.** The worker-targeted session is expected to use the worker, not controller-local tools. Verify that every enabled executable integration stays in the worker or is unavailable, and that failures/reconnects do not change this. An observed route to controller commands or authenticated controller data fails acceptance. Human administration outside that session is distinct from agent authority. A generic use of “host” in product documentation does not establish a controller-execution route.

**VM separation is not an account-level authorization guarantee.** The worker contains sensitive Codex and other provider credentials. This implementation does not prove that a stolen credential cannot authorize additional account-side resources. It removes ordinary worker filesystem/process access to the controller session, not every possible route to cloud chat history.

**One worker is one compromise domain.** Optional agents, PATs, repository contents and home state can be exposed together. A read-only upstream token still exposes readable source. PAT repository scope does not neutralize CI secrets, privileged runners or deployment capabilities reachable from a writable staging repository. Native GitHub forks also have shared-network permission and object behavior; follow the [Git guide](git-workflow.md).

**Persistent state is not reset by restarting.** Only the worker system overlay is discarded. Home-based malware, shell settings, credentials and suspect repositories survive. Rollback selects an older OS/artifact, not an older home disk, Git push or provider action. Revoke exposed tokens outside the worker and use the documented suspect-state recovery procedure.

**Admission and health are limited controls.** Disk checks are not reservations, quotas or protection against subsequent consumption. Health is readiness/generation compatibility, not attestation; worker root can forge a response. Direct network isolation does not rule out indirect public proxies/tunnels. Internet-enabled workers can exfiltrate data they can read.

See the [canonical model](controller-model.md), [technical proposal](proposal.md), [security contract](security.md), [operations](operations.md) and independent [password-backend qualification](password-storage.md).
