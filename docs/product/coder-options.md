# Coder interfaces and external controllers

This document defines accepted route semantics, not completed qualification. See [implementation status](../implementation-status.md), [component acceptance](../component-acceptance.md) and the existing [Parallels operations guide](../parallels.md).

## Choose the interface, then qualify its actual route

| Interface | Intended Assbox role | Important distinction |
|---|---|---|
| Happier | General remote multi-agent machine | Recommended Coder default; `happier-daemon`, explicit pairing and per-adapter evidence |
| Codex from external ChatGPT Desktop | Minimal Codex/OpenSSH execution host | Desktop starts remote Codex over SSH; no guest GUI, inner worker or public app-server needed |
| Claude Remote Control | Native Claude phone/web-controlled execution | Provider relay and eligible Code login; not the Desktop SSH route |
| Claude Desktop SSH | External Desktop controls remote CLI/helper | First-connect helper provisioning and policies need independent qualification |
| Cursor My Machines | Provider-native self-hosted worker | Cloud agent loop, local tool execution; MCP placement varies by transport |
| Antigravity Remote | Native provider web-controlled daemon | Supported registered service; distinct from Happier's ACP bridge |
| OpenCode web/server | Authenticated private server | Requires a deliberate private HTTPS/tunnel route, not an assumed vendor relay |
| Terminal / SSH | Direct use of selected CLIs | Universal fallback without provider remote registration |
| Direct Codex CLI relay | Explicitly experimental Advanced route | Separate commands, client support, pairing, lifecycle and acceptance from Desktop SSH |

Primary evidence: [Codex SSH](sources.md#s19), [Claude](sources.md#s16), [Antigravity](sources.md#s20), [Cursor](sources.md#s40), [OpenCode](sources.md#s41), [Codex developer commands](sources.md#s38). These mutable provider facts are not evidence that a particular installed Assbox combination works.

Coder should present Happier, Codex and Claude directly, with Cursor/Antigravity/OpenCode grouped as More native options. Terminal/SSH remains available. A local-Desktop choice reuses Kiosk with explicit protected local Code. Do not install every remote service just because all CLI packages are selected.

Grok's dashboard is a terminal interface, Pi RPC is a machine interface, and OMP collaboration shares an active session. None requires Assbox to create another universal remote service. Use actual frontend integrations or SSH; manual collaboration remains an upstream feature rather than an Assbox scheduler. [S46–S49](sources.md#s46)

## Platform-specific evidence boundary

<!-- BEGIN REVIEWED CONTROLLER ROUTES -->
**Upstream evidence reviewed on 2026-10-02.** Assbox qualification records an exact route.

| Route | Upstream evidence | Assbox status | Assbox qualification |
|---|---|---|---|
| macOS ChatGPT Desktop → standalone Assbox over SSH | Desktop SSH topology documented. The reviewed Assbox target uses a Parallels guest. [S19](sources.md#s19), [S45](sources.md#s45). | not run | Guest-only tasks, authorized reachability, and explicit handoff after a controller or guest outage. A099, A100, A101. |
| Phone → macOS ChatGPT Desktop → Assbox over SSH | The chained topology is documented and the Mac remains the coordinator. [S19](sources.md#s19). | not run | Actual phone, Mac, and Assbox workflow with coordinator and guest interruptions. A102. |
| Linux ChatGPT Desktop → Assbox managed-worker SSH | The reviewed sources document Desktop SSH and Linux app availability separately. [S19](sources.md#s19), [S53](sources.md#s53). | not run | Exact Linux client, account, helper, worker image, and policy. Verify each selected surface and failed SSH or resume. A059. |
| Phone → Linux Desktop → Assbox worker | The reviewed Remote-host documentation names macOS and Windows. [S19](sources.md#s19), [S53](sources.md#s53). | not run | Exact Linux Remote-host support and authenticated phone-to-Linux-to-worker execution. A111. |
| Independently enrolled direct Codex CLI relay | Experimental developer commands are documented. [S38](sources.md#s38). | not run | Supported client, independent enrollment, authority, and lifecycle on the explicitly selected experimental route. A104. |
<!-- END REVIEWED CONTROLLER ROUTES -->

The absence of explicit Linux route documentation is not a claim that the route cannot work. Keep implementation/qualification in scope and record an actual result. Likewise, “upstream documented” does not certify NixOS, a selected Parallels build or every tool/connector. [S19](sources.md#s19), [S38](sources.md#s38), [S53](sources.md#s53)

## Reference topology: Mac plus Parallels

```text
macOS ChatGPT Desktop (trusted controller)
              |
      authenticated SSH
              |
standalone Assbox Parallels guest
  root: configuration, administration, updates, network policy
  execution user: Codex, repos, scoped credentials and selected tools
```

The guest needs neither ChatGPT Desktop nor another managed KVM worker. It is the execution boundary for this setup. Match the guest architecture to the Mac and qualify actual CLI/native helper compatibility. Hardware support cannot be inferred from architecture names alone. [S45](sources.md#s45)

The current documented Desktop route starts Codex app-server through the remote login shell; install and authenticate the selected Codex CLI in the guest and make its intended path resolvable there. Do not expose a public app-server port or start a new relay daemon to solve an SSH PATH problem. Use a concrete SSH Host entry and verify host fingerprints independently. [S19](sources.md#s19)

Tailscale is optional for a working local Mac/guest route. “Minimal Codex SSH” permits common Assbox services and explicitly selected, unenrolled Tailscale support. A completely deselected variant must run the actual local SSH workflow without any Tailscale runtime/enrollment dependency. Shared/NAT networking is not isolation from guest-initiated Mac or LAN connections. Preserve authorized SSH replies while blocking new unapproved private destinations with the standalone execution-egress policy. Test the actual IPv4/IPv6/resolver/interface path. [S44](sources.md#s44)

Keep repositories in guest storage. Disable unnecessary host-home mounts, folder/clipboard/credential sharing, SSH-agent forwarding and device passthrough. Those Parallels settings and macOS app permissions belong to the owner, outside what the guest can enforce or attest. Explicit exceptions need their own scope.

A remote project routes its qualified command/file operations; it does not automatically relocate every browser, MCP, connector or computer-use capability. Inspect each selected tool. Silent host execution after guest failure is forbidden. Explicit user-selected handoff to another host is a different, disclosed data and execution-placement action.

Mobile continuation through the Mac uses the upstream-documented phone -> Mac -> SSH chain; exact Assbox qualification is outstanding. That path requires the Mac coordinator and guest to remain available. Test sleep, suspend, Desktop shutdown, guest restart and reconnect. Do not imply direct CLI relay provides the same behavior without independent evidence. [S19](sources.md#s19)

## Validation and responsibility

Use guest-only and host-only random canaries plus real tasks, filesystem/process observation and disconnect tests. Verify no unwanted shares, no fallback to macOS, no broad SSH identity/forward accumulation, and no replay of uncertain side effects. Record actual app, CLI, SSH, Parallels, OS and CPU versions and authentication type.

Claude Desktop SSH similarly needs no inner worker in an execution-only guest, but its remote helper can be installed by the client. Require a supported pinned override or an explicit versioned runtime exception. Native Claude relay uses another auth/service contract; neither name proves narrow account-token authority. [S14–S16](sources.md#s14)

SSH clients may use the same experimental developer subcommands internally; the route distinction concerns user-facing enrollment, authority and lifecycle, not disjoint executable code. Do not add a second independently managed relay alongside a client-owned runtime. [S38](sources.md#s38)

Experimental `codex remote-control` must establish supported client pairing, expiry/revocation, redaction, one supervisor, stop/disable and state ownership before it is offered as available. It remains opt-in and may be blocked independently of Codex SSH. Remote-control policy must not be confused with SSH policy. [S38–S39](sources.md#s38)

For Cursor, disclose cloud loop versus local tools and cloud HTTP/SSE MCP versus local stdio. For Antigravity and Happier, declare one supported service contract rather than supervising a service installer. For OpenCode, authenticate before private exposure. Each route keeps its own credential, runtime and qualification record.


Codex SSH does not imply Work or cloud-to-computer routing. An external controller retains independently reviewed Work Local, Work Cloud local-computer access, browser and helper authority; those settings belong to its owner, not the Assbox guest. See the [ChatGPT authority inventory](architecture.md#chatgpt-work-and-codex-are-separate-authority-surfaces).
