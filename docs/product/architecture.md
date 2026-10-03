# Deployment architecture and terminology

## Terms

**Assbox host** is the OS instance being configured, whether on physical hardware or in another VM. **Execution domain** is the unprivileged environment deliberately containing agent tools, repositories and credentials. **Controller** is a more-trusted local GUI/application environment kept outside that arbitrary-execution domain. **Managed worker** is the single QEMU/KVM guest whose lifecycle Assbox owns. **Provider VM** is a different guest managed by an application, such as a qualified local Cowork path. **External controller** is a separate trusted computer/phone controlling Assbox.

Do not use “worker” indiscriminately for every headless Assbox. Use **Codex via external Desktop SSH** or **Terminal / SSH** for a standalone SSH target; do not confuse the external controller's word “host” with an inner worker.

## Standalone

Assistant and Coder normally execute directly under an unprivileged account on the Assbox host. Root owns configuration, access policy and updates. Hosted remote interfaces or SSH connect to that execution environment. No inner VM is required simply because a person is remote.

Multiple agents in that account share a compromise boundary. Distinct services, worktrees and application profiles do not isolate their credentials from hostile same-account code. Dedicated/appropriately scoped account data belongs here; unrelated production/signing authority does not.

## Native kiosk and protected local execution

A native ChatGPT/Claude kiosk contains sensitive logged-in GUI state. Native chat/cloud defaults to requesting no local execution, not asserting it is already enforced. With a qualified and effectively applied native policy, it needs no Assbox worker. Pending, unsupported, ineffective or stale per-app controls keep that capability inactive; see the [activation contract](instance-types.md#native-kiosk-capability-selection). Selected arbitrary local Code execution must instead stay in the managed worker or another explicitly reviewed provider isolation boundary. The controller must not acquire broad execution components merely to make an integration convenient.

Assbox's existing worker remains one direct QEMU/KVM guest with persistent home, disposable root, dedicated SSH identities and admission/health/recovery policy. It is not a pool or a general orchestration service. An external controller can instead connect to a standalone Assbox without this inner guest.

A client offering SSH is not automatically safe as a controller. The exact Linux ChatGPT Desktop -> managed-worker SSH route is distinct from the upstream-documented external Mac route. Generic SSH documents, a Linux app package, or a macOS test cannot qualify the Linux client or Linux mobile-host behavior. [S19](sources.md#s19), [S53](sources.md#s53) Qualify effective local-execution disabling, startup/resume, preview, browser, connectors, MCP and fallback paths individually. Failure must not silently execute on the controller. Remote helper installation must use a supported pinned path or an explicit bounded client-managed-code exception with evidence.

## ChatGPT Work and Codex are separate authority surfaces

For a protected kiosk, no-local-execution must cover Codex Local, Work Local and Work Cloud local-computer access independently, plus browser/computer-use, plugin/MCP and helper routes. Workspace access, device enforcement and actual tool placement are different observations. A disabled Codex feature, browser policy or read-only sandbox is not proof that all local agent execution is blocked. Restricted browser/file bridges and cloud-only tasks remain separate explicitly selected capabilities. [S54](sources.md#s54), [S55](sources.md#s55)

Selecting a Code worker or SSH project does not redirect Work to it. Keep arbitrary controller-local Work and cloud-to-controller execution blocked unless a distinct supported placement/enforcement contract is implemented and qualified. Do not blindly revoke a broad workspace entitlement needed by remote Codex as though it were a per-device deny switch. Unknown or newly exposed locally acting features invalidate the relevant activation scope rather than inherit an old Codex result.

An eligible Work Cloud task can continue in a cloud container at a new turn when its local computer is unavailable; local executor restrictions do not transfer to that container. This is a separate documented behavior, not a Codex SSH fallback guarantee. Qualify selected location transitions and cloud authority; do not allow a cloud-only kiosk to acquire local execution on reconnect, claim that a cloud task obeys Assbox egress/filesystem policy, or replay uncertain side effects. [S19](sources.md#s19), [S55](sources.md#s55)

## Claude Code versus Cowork

Deployment starts on or after 6 October 2026. For new Pro/Max tasks the announced Cowork cloud path is the baseline; no earlier local-task migration is required. Observe actual account/build behavior and hold unexpected local execution rather than treating the date as a security mechanism. Local folders/browser/connector bridges still have separately reviewed authority. [S37](sources.md#s37)

Claude Code SSH is another route. A local Cowork provider VM is conditional on an entitlement/build actually offering it, with independent helper/device/share/resource gates. It is not the Assbox worker or a prerequisite for an otherwise qualified Claude chat/cloud kiosk. [S14–S15](sources.md#s14), [S50](sources.md#s50)

## External Desktop Coder

Mac Desktop -> SSH and phone -> Mac -> SSH are upstream-documented topologies; their exact Assbox/Parallels realization requires native qualification. The target uses macOS ChatGPT Desktop to control Codex in a standalone Assbox Parallels guest over SSH. [S19](sources.md#s19) The guest needs no Desktop and no inner managed worker. Assbox controls guest policy; owner-controlled Mac permissions and hypervisor sharing remain external prerequisites. Qualify guest-only operations, private egress denial, reconnect and no silent host fallback. Direct CLI relay is a separate experimental capability. See [Coder interfaces](coder-options.md).

## Displays

Physical presentation may be headless, X11/Openbox or a separately qualified Wayland session. Autonomous computer use is independent. Managed workload desktops must not inherit the protected physical display, session bus, accessibility bridge, browser cookies or keyring. Same-UID display separation is not a security sandbox; the controller/execution boundary supplies the relevant isolation.

## Configuration and lifecycle

Normal Nix remains the installed configuration authority; presets compile into explicit settings. Keep the six-crate pure-core/effectful-shell design and existing staged build/publication/admission mechanisms. Presets describe intended use, not security boundaries. Security properties derive from execution placement, OS identity, network policy, credentials, and display/device authority. Product labels do not bypass the kernel/placement policies. Upstream applications own their agent sessions; Assbox owns the system, package and supervised-service lifecycle.

See [implementation architecture](../architecture.md), [security/access](access-and-security.md) and [current status](../implementation-status.md) for the corresponding mechanisms and evidence.
