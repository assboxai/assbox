# Worker security contract

The [controller/worker model](controller-model.md) is the normative product policy: sensitive controllers require a worker, curated controller agent packages are rejected, and there is no supported placement bypass. This is not a sandbox for Desktop's built-in tools. The [staging-repository guide](git-workflow.md) covers the independent credential and promotion boundary.


## Scope and status

This document specifies the boundary the worker implementation is designed to enforce and the evidence required to accept it. Source inspection and unit tests are not proof that the compiled deployment enforces every statement. Native gates and manual provider tests are listed in [acceptance](acceptance.md); observed results are in [implementation status](implementation-status.md).

The security objective is **local separation of an authenticated Desktop session from arbitrary worker code**, not a claim of complete account isolation. The OpenAI account may still be shared, and the worker contains its own provider credential. Its full server-side authority is outside the VM boundary.

## Threat model

Assume an attacker can inject instructions through a repository, webpage, dependency, generated artifact, message or other agent input, and eventually obtain arbitrary worker code execution. Model worker root as compromised even when the worker agent normally has no sudo. The attacker can modify worker files, read every worker credential available to that authority, run services, forge application responses and send packets allowed by the controller firewall.

The trusted computing base includes controller firmware and CPU virtualization, the controller kernel, QEMU/KVM, controller systemd and firewall configuration, root-owned Assbox configuration and updates, the controller's OpenSSH client, Desktop and any controller tools permitted to process worker data. The phone and account sign-in flow are also trusted for user approvals. This design does not provide protection from compromised controller root, a malicious controller administrator, an already-compromised Desktop application, hypervisor escapes, a compromised update signing authority, physical disk theft or provider-side authorization flaws.

Worker state is untrusted whether returned over SSH, copied as a Git patch, displayed in a terminal, or stored in a disk image. The worker's statement that it is clean, on a particular generation or still using a particular policy is not attestation. Health reporting must not imply otherwise.

## Assets and intended controls

| Asset | Intended protection | Residual risk |
| --- | --- | --- |
| Controller Desktop login and private history cache | Separate worker kernel; no controller-home/display/keyring mounts; VMM not Desktop user | Desktop-local execution, controller compromise, client vulnerabilities, provider credential authority |
| Controller administrator access | No worker-controller login key or sudo grant; no forwarded SSH agent | Trusted admin errors, controller vulnerabilities, social engineering |
| Controller network services and selected denied prefixes (direct traffic) | Dedicated TAP; independent controller input/forward drops; no LAN bridge | Normal explicitly permits LAN; public organizational prefixes require explicit denial |
| VM management | Controller-private QMP socket; no libvirt/Docker/management sockets in worker | VMM/controller compromise |
| Worker provider and repository credentials | Explicit login and limited intentional provisioning | Assumed stolen after worker compromise; permitted internet can exfiltrate them |
| Controller availability | VM RAM/CPU/task ceilings; bounded probes; finite sparse home capacity with admission headroom | Storage growth, I/O pressure, kernel/hypervisor bugs, excessive controller builds |
| Worker project durability | Persistent `/home`; refusal to reformat unexpected existing disks | Worker corruption/ransomware, interrupted writes, stale profiles, insufficient backups |

## Invariants to qualify

The production VM must have no virtiofs, 9p, controller-home, project or Nix-store shares. It must have no USB/GPU passthrough, shared clipboard, controller browser profile, controller D-Bus/display socket, SSH-agent forwarding, QMP socket or hypervisor control access inside the worker. The QEMU process must run as `assbox-vmm` with the declared controller restrictions, not as root or the Desktop user.

The worker uses exactly the system and immutable base selected by the controller generation. The matching worker references stay alive while that controller generation is retained. Runtime state contains only the writable overlay, the persistent home disk and generated transport material, not a second unverified worker release channel.

The controller controls the network boundary. Worker root can alter the worker firewall but cannot change controller nftables policy or attach another virtual device. New traffic from the worker into controller services is blocked independently of whether an unrelated module opens those services generally. Internet access, where enabled, uses only explicitly selected controller uplinks. IPv6 and unrecognized worker source addresses are blocked on the dedicated link.

KVM or resource failures must refuse the worker. The helper never invokes local Codex as recovery and never appends a TCG fallback. An app-level fallback must be tested separately; the helper cannot forbid undisclosed Desktop behavior.

## Credentials are not a transferable security theorem

OpenAI documents both subscription sign-in and usage-billed API sign-in, and describes the CLI's credential cache as sensitive. This proposal uses the former for the user's desired entitlement. It does not inspect a personal token, enumerate the user's chats, or experimentally probe unrelated account endpoints. No such probe is necessary to install the VM. [S2]

The absence of Desktop cookies inside the worker does not prove the worker credential has no route to sensitive cloud data. A valid argument would need authoritative scope, audience, exchange and endpoint-authorization guarantees covering the actual issued credentials. They are not established here. Treat the account-side blast radius as a residual uncertainty and prefer narrowly scoped credentials if the provider eventually offers an appropriate supported personal-subscription mechanism.

Local file mode 0600 protects against other unprivileged principals, not against the same user or worker root. A worker keyring also does not turn an unrestricted worker into a safe place for broad secrets. File-based worker credential storage is chosen transparently for headless restart persistence, not described as hardened against worker compromise. Backups of `/home` inherit its credential sensitivity.

The dedicated controller-to-worker SSH private key is controller-owned and not stored in the worker. Stealing the worker host key gives the attacker that worker's SSH identity, not the controller's authorization key. Do not grant the worker host key authority on any other machine. On incident recovery, rotate the dedicated keys rather than assuming a fresh OS with a retained identity is a fresh trust relationship.

## Client routing is an acceptance contract

The Desktop/app host is the controller; the SSH host is the worker. For a project
selected on `assbox-worker`, shell and project files belong to the worker.
Capability descriptions using the word host must be read in that context, not
interpreted automatically as access to the controller. See
[terminology](terminology.md) and [upstream evidence](sources.md#s1--openai-remote-connections).

Qualify the exact Desktop/mobile builds with the
[client-routing regression procedure](client-routing.md). A worker-targeted
session must either run an enabled skill, MCP server, browser/Computer Use
operation or sub-agent in the worker, or report that capability unavailable.
The existence of a human-operated local-project selector is not itself evidence
that a worker agent can invoke it. Test agent-initiated handoff separately, with
no controller project registered for the worker repository. Do not treat a
model's refusal, a prompt instruction or a missing tool discovered in one turn
as complete enforcement evidence.

A worker failure, missing tool or reconnect must not cause execution to move to
the controller. An observed route to controller commands, local session material
or its authenticated browser/desktop fails the protective profile. Keep the
configuration unapproved until that route is disabled or independently
contained. Do not count a merely manually avoided dangerous route as a pass.
A normal SSH shell to the worker remains an operational alternative; it is not
approval of the Desktop integration.

The placement policy rejects unsupported curated controller packages, not code
bundled in Desktop or arbitrary administrative software. These limitations do
not imply that OpenAI documents automatic controller execution for SSH projects.
The default keeps controller Computer Use, browser automation and local agent
integrations disabled or unconfigured. Application updates and changes to tools,
permissions or pairing require the affected routing checks again.

## Keyring and disk-at-rest policy

The source does not couple a password-backend change to worker enablement. A libsecret migration is deferred; the appliance baseline retains `basic` pending separate qualification. Chromium can fall back when a backend is unavailable, and a password-protected keyring can require human unlock. Read [password storage](password-storage.md). No backend flag is a boundary against all arbitrary same-user processes, and no encryption/unattended-unlock guarantee is made. [S3]

Full-disk encryption is a separate physical-security decision. Unattended reboot requires a reviewed unlock method and recovery story; this implementation does not add one. The same distinction applies to the worker image, home disk, seed, controller SSH key and backups. Filesystem permissions are not disk-theft protection.

## Network meaning and exceptions

The `internet` policy is a direct controller/protected-prefix containment policy, not a data-loss-prevention policy. Public DNS, HTTPS, package registries, repository services and attacker-controlled public destinations are potentially usable channels. An attacker may also exploit allowed service features to relay traffic. Do not describe public egress as “no exfiltration” merely because private network ranges are denied.

The explicit `normal` policy additionally permits private IPv4 LAN and CGNAT
destinations, including private DNS/Git. It does not open controller services:
controller-local input drops apply independently, including its LAN/public
addresses. It also keeps the worker source check, outside-inbound denial, IPv6
denial, reserved/link-local/metadata denial and explicit uplinks. `offline` permits
no external forwarding. The interactive flow forces a choice; legacy CLI/Nix
internet policies remain unchanged. See [operations](operations.md#capacity-and-network-policy).

Use `additionalDeniedCidrs` for organizational prefixes that should remain
unreachable. Normal mode intentionally makes more services reachable, including
services on other LAN hosts. It is not a LAN-isolation claim. The worker does not
inherit the controller's Tailscale identity. None of these controls prevents
indirect access through an allowed external proxy or compromised service.

Controller-initiated SSH still carries worker-originated responses. Automatic fetching of remote URLs, local command interpolation from worker strings and indiscriminate controller-side file opening can reintroduce execution paths. Treat patches and terminals as untrusted inputs, disable agent/X11 forwarding and do not add arbitrary user-controlled `ProxyCommand` shortcuts to the managed transport.

## Persistent compromise and recovery

Restarting resets the root overlay but preserves `/home`. That is useful for routine maintenance, not sufficient incident response. Shell startup files, agent instructions, project hooks and executables on the home disk can reinfect new sessions. A worker may also have used credentials before discovery; deleting a local token is not necessarily remote revocation.

For a suspected compromise, stop the worker and automatic health restart, revoke affected external credentials through their trusted provider interfaces, preserve necessary evidence as opaque disk bytes, and create a fresh state disk under administrator control. Inspect/recover selected data in a disposable isolated environment. Do not mount the suspect filesystem on the trusted controller, run its hooks, restore its entire home directory or copy its agent authentication cache into the clean worker.

An old controller generation or a stale disk backup can reintroduce vulnerable software or compromised credentials. Document the incident's trusted recovery point rather than relying on the phrase “rollback” as a security guarantee.

## Reporting and release language

Use claims such as “worker execution is separated from the Desktop controller by KVM with no configured controller filesystem shares,” accompanied by the qualified hardware/software versions. Do not use claims such as “prompt injections cannot reach your ChatGPT history,” “all credentials are encrypted,” “SSH is one-way,” “reboot removes compromise,” or “an isolated-worker checkbox disables every local agent capability.”

Sources: [source ledger](sources.md). Implementation and observable gate results: [status](implementation-status.md).

## Generation and health authority

A controller-retained artifact has no runtime Nix references outside itself. Only internally resolved worker paths may occur in its blobs. Any future external dependency requires redesigning this contract, not casually suppressing reference checks. Scan the independent worker audit closure because controller vulnerability scans cannot see inside the opaque disk. Never put secrets in the Nix store, derivation arguments or image manifest.

The VMM process has no access to the controller/health identity directories, controller home, D-Bus or common hypervisor/daemon sockets through its service namespace. Its view is narrower than the whole controller but is not a custom minimal root filesystem; ordinary nonsecret store/system paths remain visible. Protecting the VMM process after a hypothetical exploit does not make worker escape impossible.

The canonical health identity is provisioned by root. Only its dedicated controller `assbox-health-probe` account receives the network-facing private-key copy; the SSH child runs under that UID/GID with no supplementary groups or inherited credential environment. Its worker account has a fixed store shell, no persistent home, no RC hook and no forwarding. This removes dependency on the workload user's shell configuration, but worker root can still spoof readiness. The check authenticates an endpoint and compares a build ID, not worker integrity. All boot acceptance and cleanup paths consult current health rather than trusting the diagnostic outcome file.

Network isolation is **direct** worker-to-controller/protected-prefix isolation. Internet mode permits allowed public services that may themselves relay traffic to a LAN, tailnet or account resource. A public proxy, tunnel or hairpin route is not automatically recognized by this policy. It is not a general exfiltration prevention system.

## Infrastructure health and acceptance state

The health subprocess owns a separate process group. Its output and deadline are bounded even when the SSH leader closes its streams or exits before a descendant. Group cleanup happens before reaping the leader, so a still-live descendant is not mistaken for completed work and the leader PID is not recycled before signalling. This is subprocess lifecycle hygiene, not an execution sandbox against a process deliberately escaping its session.

The worker's health shell ignores command arguments and uses a nonpersistent home. All worker passwords remain locked; the runtime-key account-lockout exception disables only a static NixOS assertion, not SSH authentication. [S10] A successful probe or boot acceptance receipt cannot prove that worker root is uncompromised.

The separate boot-acceptance receipt is root-owned and bound to the system generation and kernel boot ID. Only the engine's retry route can reuse it without pending intent; manual validation and cleanup still check fresh health. Diagnostic `worker-boot-status` is never an acceptance authority. A paused worker does not get a local fallback, and an acceptance retry does not itself start a stopped worker.

## Health parser privilege and disk admission

An assumed-malicious worker speaks SSH to an unprivileged controller health process, not a root SSH client. The root parent validates immutable local metadata and bounds/checks the small response. A child parser compromise remains serious, but does not receive the parent's UID, supplementary groups, open descriptors or provider-session environment. Native testing must verify the actual child UID and absence of controller/session access.

The built root virtual size is used before candidate publication and again at runtime. Existing data is validated without parsing/mounting the worker filesystem. Admission is an availability guard, not a quota or a security-attestation mechanism. It cannot promise space against later consumption, nor clean compromised persistent state.

## Inactive ownership identities

The controller keeps its two locked, non-login infrastructure identities while
Assbox is enabled. Worker disablement removes the execution/network configuration
and VMM `kvm` membership, not those identities or the opaque stored data. This
allows pre-activation ownership checks on re-enable. State-directory provisioning
never normalizes existing ownership or permissions before validation. Missing or
unexpected ownership is a refusal/recovery condition, not permission to adopt the
disk. See [lifecycle](lifecycle.md) and its separate native and real-KVM gates.

The production health SSH child and the KVM acceptance script's SSH child both
run under unprivileged controller identities. Root remains responsible for
trusted local lifecycle and artifact checks, not hostile SSH protocol parsing.
