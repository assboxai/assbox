# Controller and execution-worker architecture

**Decision: accepted product architecture. Implementation: native qualification required.**

## Names and topology

Use **controller**, **worker**, and **mobile client** for the three roles. The
controller runs Desktop and the hypervisor; the worker is its isolated VM and
SSH server; the mobile client controls Desktop. In OpenAI terminology, the
Desktop/app host maps to the controller and the SSH host maps to the worker.
The worker is not the machine containing the Desktop session merely because
both are sometimes called a host. See [terminology](terminology.md) for the
mapping and stable configuration names.

## The product contract

Assbox manages a trusted controller and an untrusted execution environment. Protected Code uses a native Linux controller connected over a private SSH link to one generated KVM worker. ChatGPT and Claude routes require independent native qualification. A None kiosk can be staged without a worker and still requires the exact native gate. The mobile client continues to use Desktop Remote. Linux Remote availability is the deployment premise; actual routing and permissions must be qualified on the installed client.

The user installs and administers **one Assbox**. The outer configuration builds, provisions, starts, updates, checks and replaces the headless worker. There is no worker installer, nested desktop, separate update subscription, second editable Assbox configuration, or user-managed QEMU command. The worker is a separate NixOS evaluation owned by the controller release, not an independently enrolled Assbox controller.

```text
Mobile client: ChatGPT Remote
          |
Trusted controller: Desktop + Assbox management + KVM/QEMU + SSH
          |
          | private, controller-initiated SSH
          v
Execution worker: Codex + selected other CLIs + tools + repos + scoped credentials
          |
          v
Selected agent/staging repositories
          |
          | human review / trusted promotion OUTSIDE the worker and controller
          v
Trusted upstream repositories
```

The controller is not a development workstation. Project files, Git credentials, provider CLIs, language toolchains and builds belong in the worker. The controller necessarily retains operating-system dependencies, administrative tools and private updater/build dependencies; “thin” does not mean their bits cannot appear in the controller Nix store. A trusted browser for account enrollment may also be present. Do not use it to browse arbitrary agent-provided links or open suspect project files.

## Enforced selection, and its limits

The catalog records three placement capabilities for every component: `controllerAllowed`, `workerAllowed`, and `requiresWorker`. Rust validation and Nix evaluation use these capabilities. They do not attempt to infer security from an application's name.

A sensitive controller rejects curated execution components on the controller. Protected ChatGPT Code requires worker Codex; protected Claude Code requires worker Claude Code. Native None can be staged without a worker but is inactive until exact policy verification. Managed controller `package add` is also refused; durable custom toolchains are declared through `assbox.worker.extraGuestConfig`. Unprivileged controller users are not admitted to the controller Nix daemon. Administrative builds still use the privileged management path.

Only `chatgpt-desktop` and its `chatgpt-remote` integration are currently approved controller selections. Sensitive clients without a qualified adapter, including the catalog's Claude Desktop/Cowork integration, are rejected rather than represented as safe. IDE front ends, external controllers and additional transports can be qualified later. Their potential is not a claim that their local extension/tool execution is isolated today. Ordinary deployments without a sensitive controller and without a worker can continue using the standalone component model.

These rules cover **supported Assbox selection and management**, not arbitrary administrator edits or code shipped/downloaded by Desktop itself. The supported coding session targets `assbox-worker`. Its shell and project-file operations are expected to execute in the worker, not on the controller. This is the SSH-project contract, not an assumption that every upstream use of “host” means the hypervisor host.

The [client-routing acceptance procedure](client-routing.md) verifies that expectation, including reconnects, missing tools and worker failure. Skills, MCP, browser/Computer Use and other enabled integrations must execute in the worker or be unavailable to that session. A generic documentation reference to host capabilities is not evidence of a route back to the controller. Conversely, an observed route from the worker-targeted session to controller-local execution or authenticated controller data is a security acceptance failure. Package placement and prompt instructions cannot enforce proprietary application routing; record the actual client controls and observations. Human administration of the controller is distinct from authority granted to the coding agent.

## What is generic

The VM lifecycle, artifact format, persistent state, resource admission, private network, SSH transport, health identity, boot acceptance, rollback integration and placement metadata do not depend on ChatGPT. They can support other remotely executed agents, builds of untrusted projects, isolated dependency installation and remote editor backends.

What is adapter-specific is the controller's remote protocol, app-server expectations, authentication flow, project selection, remote permissions and ability to disable local capabilities. The first adapter uses Desktop's SSH projects and worker Codex authentication. Standalone Assbox is also selectable, headless or with a manual graphical session, and can serve an external SSH controller. For example, macOS ChatGPT can use a standalone Parallels guest without nested KVM. The external controller owns its own lifecycle; Assbox does not manage macOS or enforce its application routing. Managed external workers and multiple Assbox-owned workers remain deferred.

Do not create a universal “put any component anywhere” matrix. A new controller capability requires evidence and negative tests, not simply `controllerAllowed = true`.

## One shared worker, explicit agents

Codex can orchestrate selected subordinate CLIs in the same worker. `claude-code`, `grok`, `antigravity-cli`, `cursor-agent`, `opencode` `pi` and `omp` are independently selectable. Selecting one does not install or authenticate the others. Service/remote components have their own dependency, license and mutable-code requirements; installing a plain CLI does not silently enable its daemon or mobile relay.

Every program in this worker can potentially affect the same files and credentials. Assume a successful worker compromise exposes the Codex credential, Git PAT and every other provider credential present there. A separate process, prompt, worktree, branch or agent brand does not create a security boundary. Multiple workers would be a separate feature, not an implied property of sub-agents.

Optional delegation skills and orchestration conveniences are deferred. Selected worker CLIs remain independently usable; they share one compromise domain.

## Installation and daily use

The outer installer starts with purpose and application. Protected native Code is an explicit worker choice. Custom can place execution tools in a managed worker, with explicit resources and components. Neither selection nor successful SSH authorizes native controller-local execution.

An existing installation can use `sudo assbox worker setup` or `configure` once its selected Assbox source exports these options. Changes build and stage through the normal management transaction. Existing incompatible controller packages must be removed deliberately; credentials and repositories are never silently migrated. A release imposing the sensitive-controller policy can refuse an incompatible candidate build; it must not silently activate an unisolated fallback. Plan migration before deploying that policy to unattended existing installations.

After boot, the user installs the managed `assbox-worker` SSH alias as the controller account, performs worker Codex device login through a trusted browser, and chooses the worker project in Desktop. That final app connection remains a documented one-time client step, not an undocumented edit to Desktop's databases. OpenAI describes the SSH project/app-server arrangement [C1] and headless device authorization [C2].

Normal terminal access is `assbox worker shell` or ordinary `ssh assbox-worker`. Standard `scp`, `rsync`, Git and SSH-aware editors remain usable. No proprietary file transport is added. There are no implemented `worker copy`, `git-login`, `backup`, `reset` or `enable` commands; use the documented current commands and controlled recovery procedures rather than guessed interfaces.

## State and updates

One self-contained artifact contains the packed worker system, kernel, initrd, command line and manifest. It uses QEMU/KVM from the existing pinned nixpkgs, with q35 on x86_64 and virt on AArch64. No additional virtualization framework or flake input is introduced. Runtime qualification remains mandatory.

Every worker start makes a disposable writable system overlay. Only the dedicated `/home` disk persists by contract: projects, agent auth, PAT state, shell configuration and home caches. Interactive changes to `/nix/store` or other system paths are discarded at restart. Persistently referenced Nix profiles can therefore need reconstruction. Put durable tool requirements in the worker image or reproducible project definitions; do not promise arbitrary package installs survive.

The selected controller generation references its matching artifact and immutable boot policy. Admission uses the built manifest before candidate publication and again at worker preparation. Admission budgets the root volume's full virtual size, together with state allocation and headroom. First installation measures the target filesystem rather than live-media free space. This is not a quota, ongoing reservation, or guarantee against concurrent disk consumption. Retained images and build intermediates still need a substantial storage budget.

Rollback chooses the earlier OS/artifact, not earlier `/home` contents, provider actions or Git pushes. Restart is not incident recovery: compromised home files survive. Native acceptance must cover storage pressure, interrupted allocation, update/reboot/rollback and suspect-state handling.

## Health and trust

The root management helper validates local immutable configuration, then launches the network-facing SSH child as `assbox-health-probe`, with cleared supplementary groups and environment. It uses only its dedicated health key. The worker health account has an immutable forced command, no persistent home, no forwarding and no terminal. Controller root does not parse the SSH protocol from an assumed-hostile worker.

Health is bounded readiness/generation compatibility, not attestation: worker root can forge the response. The maintenance engine requires it before accepting mandatory worker boots or cleaning recovery generations. A generation/boot-ID receipt avoids repeating completed acceptance. The retry timer stops after acceptance; subsequent boots and explicit worker startup can arm it again. The separate routine health timer remains periodic.

The worker retains a sensitive Codex credential. No tested or contractual claim is made that this account credential cannot authorize other account-side resources. The VM removes ordinary filesystem/process access to the controller's Desktop session; it does not prove provider-side token isolation. Protecting chat history still depends on actual Desktop routing and credential authority.

## Recommended Git and promotion model

Use a fine-grained PAT for selected agent/staging repositories, preferably repositories whose permissions and CI are independently reviewed. The worker must not hold an upstream write credential. Human review and synchronization run from another trusted workstation/service, **not a new credential-bearing service on the thin controller**.

Native GitHub forks are not interchangeable with independent staging repositories: fork networks have visibility, permission and shared-object behavior [C4]. The [Git workflow](git-workflow.md) describes the preferred setup, credential handling, CI hazards, review and revocation. This is guidance, not a required forge or a claim that scoped tokens prevent exfiltration of readable source.

## Scope and release decision

The architecture is chosen; the native result is not presumed. Source includes management, installer integration, placement enforcement, health separation, admission, optional skill and verification gates. It includes independent standalone workload SSH and a macOS/Parallels setup guide. It does not manage an external controller, multiple workers, provider accounts, automatic reset, or a universal Desktop sandbox.

A release must pass Rust, Nix, artifact closure, effective SSH policy, real KVM, data lifecycle and the mobile/SSH routing regression tests. No controller adapter is runtime-qualified merely by being implemented or marked eligible in the catalog. Until then it is an implementation candidate, not an unattended-production recommendation. Follow [acceptance](acceptance.md) and [implementation status](implementation-status.md).

## External interface references

These sources describe upstream interfaces, not evidence that Assbox's implementation passed them. Checked September 24, 2026.

- [C1 — OpenAI SSH and Remote connections](https://developers.openai.com/codex/remote-connections)
- [C2 — OpenAI Codex authentication](https://developers.openai.com/codex/auth)
- [C4 — GitHub fork permissions and visibility](https://docs.github.com/en/pull-requests/reference/forks)

## Disabled worker lifecycle

Worker disablement is a resource/lifecycle change, not identity deletion or
state destruction. Inert `assbox-vmm` and `assbox-health-probe` accounts persist
while Assbox is enabled; the VMM loses `kvm` membership while disabled. The
worker image/runtime, services, timers and private network remain conditional
on worker enablement. Existing state and keys can therefore be validated before
a re-enabled candidate is activated. Unknown ownership is refused, never
adopted from a disk. See [lifecycle and recovery](lifecycle.md).
