# Instance types and defaults

This is the accepted installer contract; [implementation status](../implementation-status.md) records source presence and qualification separately. Deployment begins on or after **6 October 2026**.

| Instance type | Application choices | Guided default |
|---|---|---|
| Assistant | OpenClaw or Hermes | OpenClaw; standalone/headless; full curated CLI bundle |
| Coder | Happier, Codex external Desktop SSH, Claude native access, More native options, terminal/SSH | Happier; standalone/headless; full curated bundle |
| Kiosk | ChatGPT, Claude, both; explicit web variant | Both native apps; physical X11; request local execution none, verify policy before activation |
| Custom / Advanced | Direct components, presentation, placement and access | Explicit choices using the same validation rules |

Assistant selects one primary application. A Hermes gateway is a messaging service; its optional web dashboard is a separate access surface. Installation neither joins channels nor exposes a dashboard.

## Coder navigation

**Happier** selects its runtime, `happier-daemon` and the eight curated CLIs. **Codex** selects the minimal standalone CLI/SSH target for ChatGPT Desktop on another computer. This explicitly includes macOS ChatGPT Desktop -> a Parallels Assbox guest, with no guest Desktop or nested worker.

**Claude** offers native mobile/web relay or external Claude Desktop SSH as distinct choices. **More native options** groups Cursor My Machines, Antigravity Remote and OpenCode private web/server. **Terminal / SSH** defaults to Codex but can be customized. Native presets can optionally expand the bundle. The local Desktop entry links to Kiosk and proposes protected local Code rather than maintaining a second implementation.

Direct Codex CLI relay remains an explicitly experimental Advanced capability with separate client/authentication/lifecycle evidence. It is not the SSH preset or a prerequisite for it. See [Coder options](coder-options.md).

## Native kiosk capability selection

Applications are independently deselectable. **Local execution none is the requested policy, not evidence of a native client capability.** Activate a no-worker native app only with a qualified, effectively applied contract for its exact platform/build/account and selected features. Missing KVM alone is not a reason to reject an otherwise enforceable profile. Selected local folders/browser/connectors retain separate authority; “none” does not mean that the native GUI itself runs no code.

| Native policy state | Required behavior |
|---|---|
| Verified and effectively applied | Activate only that qualified app/capability |
| Pending account/configuration facts | Stage inactive and report setup required, never ready |
| Unsupported, ineffective or conflicting | Block the affected activation and explain the precise reason |
| Stale after a relevant change | Revalidate before re-enable; do not trust a writable ready marker |

Offer only independently qualified protected/remote execution, explicitly selected web mode, or Back/deselection. Adding a worker does not repair uncontrolled local fallback, and a warning acknowledgement cannot authorize it. One blocked app must not suppress another independently safe app. Apply the same contract in setup, reconfiguration, launch and update/rollback; do not launch an unrestricted credential-bearing client to discover whether its control works. A safe authentication/bootstrap path must itself be qualified. [S15](sources.md#s15), [S39](sources.md#s39), [S51](sources.md#s51), [S52](sources.md#s52)

Selecting **protected local Code** adds the one managed worker and only required agent CLIs: Codex, Claude Code or both. The physical GUI does not inherit arbitrary worker execution. Do not fall back to controller-local commands when a worker or native policy fails.

New Pro/Max Cowork tasks use the announced post-6-October cloud model. No pre-transition local-task migration is required. Expose a local provider VM only for an account/build that actually offers it and passes its own qualification. That conditional capability is not a basic Claude-kiosk dependency. Observe actual entitlement/behavior during onboarding rather than treating the date as enforcement. [S37](sources.md#s37), [S50](sources.md#s50)

An explicit web chat/cloud kiosk remains an alternative, not a claim of native local-feature parity. A personal AI terminal is not a secure shared public kiosk; autologin and keyring unlock remain distinct concerns.

## Independent choices

**Presets describe intended use, not security boundaries. Security properties derive from execution placement, OS identity, network policy, credentials, and display/device authority.** Purpose, application, physical presentation, placement, transport and computer-use are independently stored choices.

All eight CLIs remain individually removable. Show installed, authenticated, frontend-integrated/maturity and Assbox-qualified states separately. A package or generic ACP interface does not imply equal frontend support. Future preset revisions must not silently add components; resolve once into ordinary explicit Nix settings and preserve `local.nix`.

Tailscale support is checked in guided presets and deselectable; enrollment/exposure are later explicit actions. A minimal Codex SSH preset includes only the necessary Coder additions, not the absence of common system services. Verify a fully Tailscale-deselected local SSH variant independently. Raw component defaults remain opt-in. Optional Vim/Emacs and graphical editors do not change unconditional nano/tmux.

A profile change shows its effective diff before application. Moving persistent state between standalone and a guest requires explicit migration, not a label change. Custom retains every hardware, placement, access and consent rule.


## Setup and independent native surfaces

Happier pairing is an owner action after installation, not an effect of choosing the preset. Use the supported no-browser URL flow or, optionally, pairing from an already authenticated trusted client over an approved SSH path. Keep target execution identity, server/account scope, private credentials and one managed daemon explicit. Hosted URL setup does not require incoming SSH or Tailscale. [S01](sources.md#s01)

ChatGPT kiosk qualification inventories Work Local, Work Cloud local-computer access and Codex Local separately; disabling one does not disable the others. Protected Code routing does not redirect Work. See the [surface authority contract](architecture.md#chatgpt-work-and-codex-are-separate-authority-surfaces). Native browser, desktop control and provider-specific build limits are recorded separately in the [dated Linux matrix](linux-computer-use-support.md).
