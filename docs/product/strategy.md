# Product and strategy

## Purpose

Assbox is a dedicated AI appliance built using ordinary NixOS configuration, packages and management tooling. It supports remote agent execution, always-on assistance and physical AI-terminal use. It can be installed on suitable owner-supplied hardware or in an ordinary VM; a particular GUI vendor or a nested VM is not the product's defining feature.

The owner intentionally puts development repositories, working data and appropriately scoped credentials on the execution machine. Assbox should make that machine reproducible, understandable and low-maintenance while keeping administration and more-sensitive local controllers outside arbitrary execution where required.

A physical kiosk is first-class. A standalone headless appliance is first-class. Neither must carry the other's unnecessary runtime components. A native chat/cloud kiosk does not require a worker merely for displaying its apps; protected local execution does.

## Boundaries of responsibility

Assbox owns OS/package configuration, independent component selection, hardware/boot binding, access policy, execution placement, service supervision, updates, resource controls and recovery. It records implementation and qualification evidence.

Happier, OpenClaw, Hermes and native provider applications own their user experiences, sessions, channels, orchestration, delegation and provider protocols. Assbox does not create a universal agent server, ACP broker, model loop, remote frontend, delegation scheduler or provider-independent skill framework. Small configuration, package and display-resource adapters are appropriate; a competing application layer is not.

## Product shapes

The installer first asks Assistant, Coder, Kiosk or Custom. Assistant offers OpenClaw and Hermes; Coder recommends Happier and retains a few clear native/SSH alternatives; Kiosk offers ChatGPT and Claude; Custom exposes the same primitives and rules. These are presets, not separate distributions or security authorities.

The curated agent bundle is Codex, Claude Code, Antigravity CLI, Cursor Agent, Grok Build, OpenCode, Pi and OMP. Assistant and Happier presets select all eight by default, with granular deselection. Native single-provider and remote-host presets remain minimal. Installed tools are not automatically authenticated or run as services. Nano and tmux always remain in the base environment.

Tailscale support is a guided default, not mandatory infrastructure. Enrollment and application exposure require separate decisions. Hosted remote services must work without it where upstream supports that topology.

Codex via external ChatGPT Desktop SSH is a directly visible Coder choice, including a standalone Parallels guest controlled from macOS. Provider relay, SSH and private-server routes have different authority and lifetime dependencies; see [Coder options](coder-options.md).

Deployment starts on or after 6 October 2026. No pre-transition Cowork task migration is in scope; the announced new Pro/Max cloud mode is the baseline, with actual capabilities checked at onboarding. [S37](sources.md#s37)

## Non-goals and honest limits

Assbox is not a public multi-tenant kiosk, an assurance that arbitrary tools cannot leak their supplied credentials, or an independent full Linux-distribution infrastructure project. A shared execution account is a shared compromise domain. An outbound-capable agent can start its own network software even when Assbox's managed remote services are disabled.

“Unattended” means routine system maintenance is automated, bounded and diagnosable. It does not mean third-party sessions never expire, a locked keyring unlocks itself, an update reverses arbitrary application migrations, or hardware never needs recovery.

Claims of support must identify the actual package/runtime, integration, capability, auth mode and platform. See [implementation status](../implementation-status.md). Research or a successful package build is not a replacement for native acceptance.
