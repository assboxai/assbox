# Dated provider and package evidence

Primary sources recorded 1–2 October 2026 for the accepted target, with individual review dates below. Deployment begins on or after 6 October 2026. Provider facts are not permanent architecture rules or proof of an installed release. Check actual client, account, runtime and platform in the [implementation ledger](../implementation-status.md).

<a id="s01"></a>

## S01 — Happier daemon

https://docs.happier.dev/apps/daemon

**Reviewed:** 2026-10-02. **Evidence type:** current-primary-documentation.

Documents Linux user-systemd supervision, supported service dry-run/inspection, no-browser auth login --no-open --method web, and owner-initiated auth pair-remote --ssh from an already authenticated machine. Requests can expire; some CLI operations can start a daemon. These are upstream contracts to inspect on the pin, not proof that pairing preserves Nix service ownership.

<a id="s02"></a>

## S02 — Happier deployment topology

https://docs.happier.dev/self-hosting/how-it-works

**Reviewed:** 2026-10-01. **Evidence type:** current-primary-documentation.

Clients and the execution-machine CLI/daemon communicate through a relay. Hosted remote access does not inherently require an inbound route or Tailscale.

<a id="s03"></a>

## S03 — Happier security

https://docs.happier.dev/security

**Reviewed:** 2026-10-01. **Evidence type:** current-primary-documentation.

Encrypted session content, metadata, and connected-service credentials have different protections. Endpoint compromise and account-wide authority remain relevant.

<a id="s04"></a>

## S04 — Happier encryption model

https://docs.happier.dev/security/encryption

**Reviewed:** 2026-10-01. **Evidence type:** current-primary-documentation.

Encryption modes and deployment policy must be checked against the selected release. Do not assume an environment variable from another release is effective.

<a id="s05"></a>

## S05 — Happier agent catalog

https://docs.happier.dev/agents

**Reviewed:** 2026-10-01. **Evidence type:** current-primary-documentation.

Provides named integrations and Custom ACP. Some integrations are explicitly experimental; installing a CLI is not proof of a qualified frontend adapter.

<a id="s06"></a>

## S06 — Hermes messaging gateway

https://hermes-agent.nousresearch.com/docs/user-guide/messaging/

**Reviewed:** 2026-10-01. **Evidence type:** current-primary-documentation.

Documents foreground `hermes gateway`, independently supervised messaging, pairing/allowlists, and persistent sessions. Treat messaging and dashboard as different services.

<a id="s07"></a>

## S07 — Hermes configuration

https://hermes-agent.nousresearch.com/docs/user-guide/configuration

**Reviewed:** 2026-10-01. **Evidence type:** current-primary-documentation.

Hermes supports a local terminal backend and other execution backends. HERMES_HOME selects application state; local tools can still share the OS account home and credentials.

<a id="s08"></a>

## S08 — Hermes security

https://hermes-agent.nousresearch.com/docs/user-guide/security/

**Reviewed:** 2026-10-01. **Evidence type:** current-primary-documentation.

Use upstream authentication and tool controls, but do not represent conversational authorization or an application profile as a hostile-user isolation boundary.

<a id="s09"></a>

## S09 — Hermes dashboard

https://hermes-agent.nousresearch.com/docs/user-guide/features/web-dashboard

**Reviewed:** 2026-10-01. **Evidence type:** current-primary-documentation.

Hermes documents non-loopback public_url as activating authentication even behind a loopback proxy. Validate exact pin, missing-auth refusal, secure cookies, origins and interactive WebSocket/PTY; tunnel-only access is a separate explicit mode.

<a id="s10"></a>

## S10 — Hermes installation

https://hermes-agent.nousresearch.com/docs/getting-started/installation

**Reviewed:** 2026-10-01. **Evidence type:** current-primary-documentation.

Upstream installation manages executable code and can provision browser/computer-use helpers. Assbox must package selected helpers and suppress competing updates and implicit reinstalls.

<a id="s11"></a>

## S11 — Hermes bundled skills

https://hermes-agent.nousresearch.com/docs/reference/skills-catalog

**Reviewed:** 2026-10-01. **Evidence type:** current-primary-documentation.

Bundled skills include delegation to Codex and Claude Code. Reuse upstream skills; do not add an Assbox orchestration engine.

<a id="s12"></a>

## S12 — Hermes browser automation

https://hermes-agent.nousresearch.com/docs/user-guide/features/browser

**Reviewed:** 2026-10-02. **Evidence type:** current-primary-documentation.

Documents local and cloud browser backends. The local path can use Chromium/CDP or a selected helper. Cloud selection is not a guarantee of no local browser: the documented hybrid path can use a local sidecar for private destinations. Qualify selected helpers, location and egress without importing personal browser profiles.

<a id="s13"></a>

## S13 — Hermes computer use

https://hermes-agent.nousresearch.com/docs/user-guide/skills/bundled/autonomous-ai-agents/autonomous-ai-agents-computer-use

**Reviewed:** 2026-10-01. **Evidence type:** current-primary-documentation.

The upstream skill names Linux support and delegates platform behavior to cua-driver. A pinned driver plus a working isolated display still requires qualification.

<a id="s14"></a>

## S14 — Claude Desktop Linux beta

https://code.claude.com/docs/en/desktop-linux

**Reviewed:** 2026-10-01. **Evidence type:** current-primary-documentation.

Official Linux packaging targets Debian/Ubuntu, not NixOS. The documented local Cowork path has its own QEMU/KVM/virtiofs/vsock requirements. General screen control is excluded from the Linux beta documentation.

<a id="s15"></a>

## S15 — Claude Desktop execution environments

https://code.claude.com/docs/en/desktop

**Reviewed:** 2026-10-02. **Evidence type:** current-primary-documentation.

Documents SSH Code sessions and disableDesktopLocalSessions for Desktop v1.37937.0 or later. The client reads SSH/local-session controls on the local machine while the remote session reads remote managed settings; connector delivery has separate controls. This is route-specific evidence, not a blanket Linux kiosk or Cowork exclusion guarantee.

<a id="s16"></a>

## S16 — Claude Code Remote Control

https://code.claude.com/docs/en/remote-control

**Reviewed:** 2026-10-01. **Evidence type:** current-primary-documentation.

Remote Control runs the execution session on the selected machine. It requires an eligible account and a full-scope login token; inference-only setup tokens are insufficient. General chat-history exclusion is not established here.

<a id="s17"></a>

## S17 — Claude Code computer use

https://code.claude.com/docs/en/computer-use

**Reviewed:** 2026-10-02. **Evidence type:** current-primary-documentation.

Native Claude Code CLI computer use is a macOS research preview requiring an interactive eligible login; the document explicitly excludes Linux/Windows CLI use. Browser integrations and other model/harness paths are different capabilities.

<a id="s18"></a>

## S18 — ChatGPT Linux release notes

https://help.openai.com/en/articles/6825453-chatgpt-release-notes

**Reviewed:** 2026-10-02. **Evidence type:** current-primary-documentation.

The Linux public-preview release entry documents browser actions and explicitly says other desktop applications cannot yet be controlled. This is current upstream product evidence, not an Assbox/NixOS build or a promise about later releases.

<a id="s19"></a>

## S19 — OpenAI remote connections

https://learn.chatgpt.com/docs/remote-connections

**Reviewed:** 2026-10-02. **Evidence type:** current-primary-documentation.

Documents Desktop SSH runtime startup and Mac/mobile-through-Mac remote topology. Separately, eligible Work Cloud tasks with local-computer access can continue in a cloud container when the computer is absent at a new turn; local execution requirements are not inherited and no mid-turn switch is promised. That feature does not change Codex Remote behavior. Qualify each actual client/account path.

<a id="s20"></a>

## S20 — Antigravity Remote Control

https://antigravity.google/docs/remote-control/

**Reviewed:** 2026-10-01. **Evidence type:** current-primary-documentation.

`agy remote-control start` installs/registers an OS service. It is not a documented foreground ExecStart contract. Retain the feature, extract/test the actual runtime entrypoint, and avoid duplicate supervision.

<a id="s21"></a>

## S21 — Gemini individual-account transition

https://developers.googleblog.com/an-important-update-transitioning-gemini-cli-to-antigravity-cli/

**Reviewed:** 2026-10-01. **Evidence type:** current-primary-documentation.

Individual Gemini CLI access transitioned to Antigravity; specified enterprise/API cases remain. Assbox removes the consumer catalog option without deleting shared .gemini state or silently migrating accounts.

<a id="s22"></a>

## S22 — Cursor Linux computer use

https://cursor.com/docs/cloud-agent/self-hosted/computer-use

**Reviewed:** 2026-10-02. **Evidence type:** current-primary-documentation.

Documents opt-in Linux X11 screenshot/input and browser use on self-hosted workers, with managed TigerVNC/XFCE when no existing display is selected. Dependencies are owner-installed. Display sharing is separate; an inherited reachable DISPLAY can select the wrong desktop unless managed launch scrubs it.

<a id="s23"></a>

## S23 — OpenClaw browser/UI/desktop configuration

https://docs.openclaw.ai/gateway/config-browser-ui-desktop

**Reviewed:** 2026-10-02. **Evidence type:** current-primary-documentation.

Documents managed browsers and a Labs, off-by-default Linux TigerVNC/XFCE desktop. Desktop viewing does not enable the computer tool: cua-computer and the tool policy require separate opt-in. Existing loopback RFB listeners can affect display selection; qualify the managed route and cleanup.

<a id="s24"></a>

## S24 — OpenClaw security

https://docs.openclaw.ai/gateway/security

**Reviewed:** 2026-10-01. **Evidence type:** current-primary-documentation.

A Gateway is a shared trust boundary. Channel authorization and application sandboxing are not substitutes for isolation between mutually untrusted users.

<a id="s25"></a>

## S25 — OpenClaw ACP integration setup

https://docs.openclaw.ai/tools/acp-agents-setup

**Reviewed:** 2026-10-01. **Evidence type:** current-primary-documentation.

External-agent integration includes plugins/adapters, not just installed agent executables. Pin the selected plugin and bridges and test their permissions and machine interfaces.

<a id="s26"></a>

## S26 — OpenClaw Tailscale integration

https://docs.openclaw.ai/gateway/tailscale

**Reviewed:** 2026-10-01. **Evidence type:** current-primary-documentation.

Documents private Serve and other exposure modes. Assbox chooses private authenticated exposure and does not enable public Funnel by default.

<a id="s27"></a>

## S27 — Tailscale Serve

https://tailscale.com/docs/features/tailscale-serve

**Reviewed:** 2026-10-01. **Evidence type:** current-primary-documentation.

Serve shares local services within a tailnet, subject to access policy. HTTPS setup and identity headers have explicit conditions; local header spoofing must not become an authorization shortcut.

<a id="s28"></a>

## S28 — Tailscale access controls

https://tailscale.com/docs/features/access-control/acls

**Reviewed:** 2026-10-01. **Evidence type:** current-primary-documentation.

Initial/default policies can allow broad peer communication. Directional access rules and local workload egress restrictions address different paths.

<a id="s29"></a>

## S29 — OMP computer use at v18.1.19

https://raw.githubusercontent.com/can1357/oh-my-pi/v18.1.19/docs/computer-use.md

**Reviewed:** 2026-10-02. **Evidence type:** versioned-primary-source.

At v18.1.19, OMP documents an off-by-default computer prelude with Linux X11 capture/input and AT-SPI. Wayland capture depends on wayland-pipewire and portal permissions. Limitations stated for upstream release binaries must not be assigned to differently compiled Nix packages; browser control is a separate prelude.

<a id="s30"></a>

## S30 — Hermes package at baseline-referenced package revision

https://raw.githubusercontent.com/numtide/llm-agents.nix/7bba6197505fbc7e138a4922ac97061d2ec11b42/packages/hermes-agent/package.nix

**Reviewed:** 2026-10-01. **Evidence type:** versioned-primary-source.

A Hermes package definition exists at the revision referenced by baseline package inputs. Assbox still has no Hermes component or family; package existence is not integration or build evidence.

<a id="s31"></a>

## S31 — Claude Desktop package at baseline-referenced revision

https://raw.githubusercontent.com/numtide/llm-agents.nix/7bba6197505fbc7e138a4922ac97061d2ec11b42/packages/claude-desktop/package.nix

**Reviewed:** 2026-10-01. **Evidence type:** versioned-primary-source.

Inspect the actual packaging and helper closure before updating controller policy; current upstream Linux documentation does not certify this derivation.

<a id="s32"></a>

## S32 — Pi package at baseline-referenced revision

https://raw.githubusercontent.com/numtide/llm-agents.nix/7bba6197505fbc7e138a4922ac97061d2ec11b42/packages/pi/package.nix

**Reviewed:** 2026-10-01. **Evidence type:** versioned-primary-source.

Definition supports a Node execution variant as well as a compiled Bun path. Old-CPU compatibility needs native validation rather than an architecture-name check.

<a id="s33"></a>

## S33 — OMP package at baseline-referenced revision

https://raw.githubusercontent.com/numtide/llm-agents.nix/7bba6197505fbc7e138a4922ac97061d2ec11b42/packages/omp/package.nix

**Reviewed:** 2026-10-02. **Evidence type:** versioned-primary-source.

The baseline-referenced package definition explicitly enables the wayland-pipewire Cargo feature on Linux. That is a build-input observation, not proof that screenshots or input work on a particular compositor/portal; native qualification remains required.

<a id="s34"></a>

## S34 — Grok Build package aliases

https://raw.githubusercontent.com/numtide/llm-agents.nix/7bba6197505fbc7e138a4922ac97061d2ec11b42/packages/grok/package.nix

**Reviewed:** 2026-10-01. **Evidence type:** versioned-primary-source.

Exports grok and an agent alias. A bare agent invocation is ambiguous in an all-agents environment.

<a id="s35"></a>

## S35 — Cursor packaged command

https://raw.githubusercontent.com/numtide/llm-agents.nix/7bba6197505fbc7e138a4922ac97061d2ec11b42/packages/cursor-agent/package.nix

**Reviewed:** 2026-10-01. **Evidence type:** versioned-primary-source.

The packaged command is cursor-agent. Integrations must use the selected package path, not a generic name copied from installer documentation.

<a id="s36"></a>

## S36 — Happier Antigravity adapter

https://docs.happier.dev/agents/agy

**Reviewed:** 2026-10-01. **Evidence type:** current-primary-documentation.

The Antigravity integration has a distinct bridge/runtime path. Include its actual executable/authentication dependencies in qualification rather than assuming agy alone is enough.

<a id="s37"></a>

## S37 — Cowork post-6-October transition

https://support.claude.com/en/articles/15520349-use-claude-cowork-on-web-desktop-and-mobile

**Reviewed:** 2026-10-01. **Evidence type:** current-primary-documentation.

Announces cloud execution for new Pro/Max Cowork tasks from 6 October 2026, with Desktop bridges for selected local resources. Assbox deployment assumes no earlier tasks; actual entitlement/build topology must still be checked.

<a id="s38"></a>

## S38 — Codex developer remote-control commands

https://developers.openai.com/codex/developer-commands

**Reviewed:** 2026-10-02. **Evidence type:** current-primary-documentation.

The developer reference labels remote-control experimental and documents foreground/start/stop/pair operations and short-lived pairing output. It says managed clients and SSH workflows can use these commands internally. That overlap does not equate independent CLI relay enrollment with the documented Desktop SSH/mobile contract.

<a id="s39"></a>

## S39 — Codex managed remote-control policy

https://developers.openai.com/codex/enterprise/managed-configuration

**Reviewed:** 2026-10-02. **Evidence type:** current-primary-documentation.

Managed allow_remote_control=false disables device remote control where supported but expressly does not disable SSH. Supported permission-profile and filesystem controls have version/platform/surface limits. These are not proof of a universal consumer-account switch disabling every controller-local execution path.

<a id="s40"></a>

## S40 — Cursor My Machines

https://cursor.com/docs/cloud-agent/self-hosted/my-machines

**Reviewed:** 2026-10-01. **Evidence type:** current-primary-documentation.

Personal self-hosted workers use outbound connections, a cloud-hosted agent loop and local tool execution; HTTP/SSE MCP can be cloud-side while stdio runs locally. Test the exact packaged cursor-agent path.

<a id="s41"></a>

## S41 — OpenCode web and server

https://opencode.ai/docs/web/

**Reviewed:** 2026-10-01. **Evidence type:** current-primary-documentation.

Provides web/server access with explicit bind and authentication choices. An Assbox private server route requires configured authentication and reviewed HTTPS/tunnel access.

<a id="s42"></a>

## S42 — Hermes public URL environment contract

https://hermes-agent.nousresearch.com/docs/reference/environment-variables

**Reviewed:** 2026-10-01. **Evidence type:** current-primary-documentation.

HERMES_DASHBOARD_PUBLIC_URL declares the externally reachable dashboard origin; a non-loopback public URL activates the auth requirement even when the server listens on loopback.

<a id="s43"></a>

## S43 — Happier adapter capabilities

https://docs.happier.dev/agents/capabilities

**Reviewed:** 2026-10-01. **Evidence type:** current-primary-documentation.

Per-agent capabilities and maturity differ; named integration and custom ACP support are not proof that every installed CLI, particularly OMP, has an identical qualified frontend path.

<a id="s44"></a>

## S44 — Parallels network modes

https://kb.parallels.com/en/4948

**Reviewed:** 2026-10-01. **Evidence type:** current-primary-documentation.

Shared networking uses host-managed NAT. Actual host-to-guest reachability and guest egress must be tested; NAT is not a security boundary against guest-initiated access to the Mac.

<a id="s45"></a>

## S45 — Parallels Apple Silicon Linux architecture

https://kb.parallels.com/en/128445

**Reviewed:** 2026-10-01. **Evidence type:** current-primary-documentation.

Apple Silicon Linux VM setup uses ARM installation media. This does not establish NixOS or every Assbox component as vendor-certified; exact guest/platform qualification is separate.

<a id="s46"></a>

## S46 — Grok Build CLI reference

https://docs.x.ai/build/cli/reference

**Reviewed:** 2026-10-01. **Evidence type:** current-primary-documentation.

Documents terminal, headless and ACP interfaces. Do not infer a hosted remote-human-control service from generic agent or remote-MCP terminology.

<a id="s47"></a>

## S47 — Grok Build dashboard

https://docs.x.ai/build/features/dashboard

**Reviewed:** 2026-10-01. **Evidence type:** current-primary-documentation.

The dashboard is a terminal interface, not evidence of a browser/mobile remote service. Use selected frontend integration or SSH for the proposed Assbox role.

<a id="s48"></a>

## S48 — Pi coding-agent interfaces

https://raw.githubusercontent.com/earendil-works/pi/main/packages/coding-agent/README.md

**Reviewed:** 2026-10-01. **Evidence type:** current-primary-documentation.

Pi supplies terminal, print, JSON and RPC/SDK interfaces. A machine interface is not by itself a turnkey internet-facing human remote service.

<a id="s49"></a>

## S49 — OMP collaboration at v18.1.19

https://raw.githubusercontent.com/can1357/oh-my-pi/v18.1.19/docs/collab.md

**Reviewed:** 2026-10-01. **Evidence type:** versioned-primary-documentation.

Collaboration shares an active host session with browser/TUI participants. Treat separately from an always-on machine-access service and do not automatically publish a session on installation.

<a id="s50"></a>

## S50 — Cowork organizational entitlement

https://support.claude.com/en/articles/13455879-use-claude-cowork-on-team-and-enterprise-plans

**Reviewed:** 2026-10-01. **Evidence type:** current-primary-documentation.

Organizational account policies and entitlements require separate observation. The Pro/Max transition must not be extrapolated into an unconditional local or cloud guarantee for every account.

<a id="s51"></a>

## S51 — ChatGPT desktop managed browser policies

https://help.openai.com/en/articles/20001535-manage-chatgpt-desktop-browser-policies-with-mdm

**Reviewed:** 2026-10-02. **Evidence type:** current-primary-documentation.

Documents platform-specific managed Chromium policy delivery, including Linux JSON paths. Browser extension, cookie and browser-policy controls do not by themselves prove that Code/Work/local helpers are disabled. Assbox must qualify effective client/account/feature scope rather than substitute browser policy for a global local-execution control.

<a id="s52"></a>

## S52 — Claude Desktop enterprise feature controls

https://support.claude.com/en/articles/12622667-enterprise-configuration-for-claude-desktop

**Reviewed:** 2026-10-02. **Evidence type:** current-primary-documentation.

Lists isClaudeCodeForDesktopEnabled and separate extension/local-MCP controls, with macOS/Windows deployment instructions. These are candidate feature controls, not proof of Linux delivery or enforcement, nor a complete Cowork/connector boundary. Exact platform/build/account applicability must be established before no-worker kiosk activation.

<a id="s53"></a>

## S53 — ChatGPT Linux desktop preview and evidence limits

https://learn.chatgpt.com/docs/linux/linux-app

**Reviewed:** 2026-10-02. **Evidence type:** current-primary-documentation.

Documents Linux preview packages and supported distro/architecture scope; NixOS is not listed. The inspected page does not specify the exact Linux Desktop-to-SSH-worker or Linux mobile Remote-host path. Package availability and generic remote docs are insufficient to claim these client-specific routes are qualified; absence of explicit documentation is not a finding that they cannot work.

<a id="s54"></a>

## S54 — Independent ChatGPT Work and Codex access

https://help.openai.com/en/articles/20001275-chatgpt-work-and-codex

**Reviewed:** 2026-10-02. **Evidence type:** current-primary-documentation.

Work Cloud, Work Local and Codex Local have independent workspace access controls; browser/network settings are separate. Workspace availability is not an execution-location enforcement guarantee for consumer accounts or a particular Linux build. A kiosk must inventory all locally acting surfaces rather than equate disabling Codex with disabling Work.

<a id="s55"></a>

## S55 — Work Cloud local-computer authority and policy scope

https://learn.chatgpt.com/docs/enterprise/cloud-local-access

**Reviewed:** 2026-10-02. **Evidence type:** current-primary-documentation.

Documents separately enabled local-computer access while the cloud coordinates work, with account/rollout prerequisites. Local execution requirements do not govern a cloud executor. Treat Work Cloud local access independently from both cloud-only Work and the Desktop SSH/Codex Remote route; unknown locally acting feature paths must not bypass policy.

<a id="s56"></a>

## S56 — Claude Desktop native computer-use platforms

https://support.claude.com/en/articles/14128542-let-claude-use-your-computer-in-cowork

**Reviewed:** 2026-10-02. **Evidence type:** current-primary-documentation.

The reviewed native Desktop computer-use beta lists macOS and Windows, not Linux. It distinguishes connectors and browser automation from screen interaction. This limitation is about the native product, not Claude models behind another qualified Linux harness.

<a id="s57"></a>

## S57 — Claude built-in browser on Linux beta

https://support.claude.com/en/articles/16607400-use-the-built-in-browser-in-claude-cowork

**Reviewed:** 2026-10-02. **Evidence type:** current-primary-documentation.

Documents a gradual built-in-browser rollout including Linux beta and eligible plans. Browser operation requires the desktop bridge to remain open/online even for a cloud Cowork session. Selected browser logins persist; Assbox must not auto-import personal cookies. This is not general Linux desktop control.

<a id="s58"></a>

## S58 — Hermes Cua Driver computer-use integration

https://hermes-agent.nousresearch.com/docs/user-guide/features/computer-use

**Reviewed:** 2026-10-02. **Evidence type:** current-primary-documentation.

Documents Linux computer use through Cua Driver with X11 and qualified Wayland paths, AT-SPI and display/capture prerequisites. Native Wayland remains opt-in and current capture guidance needs an XWayland bridge. Inspect the pinned driver/runtime and use its supported exact-path override rather than assuming upstream package-manager downloads are acceptable.

<a id="s59"></a>

## S59 — Hermes provider-managed headless Bot Screen

https://hermes-agent.nousresearch.com/docs/user-guide/features/bot-screen

**Reviewed:** 2026-10-02. **Evidence type:** current-primary-documentation.

Documents per-profile Xfce/TigerVNC work surfaces on headless Linux and provider viewing/control with short-lived viewer tickets. It explicitly treats same-UID screens as work surfaces rather than isolation from hostile peers, and notes that loopback browser debugging is not per-user protected. Prefer this upstream lifecycle when present in the selected pin; qualify viewer authorization and do not infer support in older packages.
