# ADR 0001: Assbox product and deployment contract

**Status:** accepted for implementation. **Implementation:** tracked separately in [status](../implementation-status.md). **Decision authority:** repository review, not provider marketing or installer labels.

## Decision

Assbox is a dedicated agent-execution appliance and optional physical AI terminal implemented through ordinary NixOS tooling. Assistant/Coder/Kiosk/Custom are purpose-first presets over one independent component system. OpenClaw and Hermes are Assistant choices; Happier is the recommended Coder frontend; native ChatGPT/Claude kiosks are first-class. Codex external Desktop SSH, including macOS/Parallels, is a visible minimal Coder option; Claude native routes and grouped Cursor/Antigravity/OpenCode choices reuse their actual upstream interfaces.

Assistant/Happier guided presets select eight independently removable agent CLIs. Nano/tmux stay base. Tailscale support is a guided, deselectable default, never automatic enrollment/exposure. Raw module defaults remain opt-in; installed presets are resolved settings, not subscriptions to changing bundle membership.

Presets describe intended use, not security boundaries. Security properties derive from execution placement, OS identity, network policy, credentials, and display/device authority.

Standalone execution is normal where no sensitive local controller requires separation. Native chat/cloud kiosk requests no local execution and no Assbox worker; only verified effective controls for the actual client/platform/account permit activation. Pending, unsupported, ineffective or stale policy keeps the affected capability inactive. Neither a warning acknowledgement nor adding a worker waives missing enforcement. Protected local Code explicitly adds the worker. Preserve one managed QEMU/KVM worker for protected native-controller execution, with persistent home, disposable root and existing admission/recovery. Code SSH, local Cowork provider VM and cloud execution are different paths. Native feature qualification cannot be replaced by a blanket catalog allow flag. Mac->SSH and phone->Mac->SSH have upstream topology documentation but await Assbox evidence; Linux Desktop->worker SSH and Linux mobile hosting retain independent exact-client gates.

Deployment starts on or after 6 October 2026. New Pro/Max Cowork follows the announced cloud baseline, checked against actual account/build capabilities; no pre-transition local-task migration is required. Other eligible local provider-VM modes remain conditional and cannot block ordinary kiosk qualification. [S37](../product/sources.md#s37)

Happier uses `happier-daemon` with one Nix-declared upstream-compatible supervisor. Recommended Hermes private access combines loopback binding, non-loopback HTTPS public_url and native auth; verify fail-closed behavior on the pin. A separately consented private tunnel-only exception discloses absence of app auth. Direct Codex CLI relay is experimental and distinct from Desktop SSH.

Native local-execution denial must cover every applicable locally acting surface independently; one disabled Code feature cannot establish that Work, cloud-to-computer requests or helpers are blocked. Selected cloud execution has its own authority and location-transition policy, not inherited local guarantees. Current vendor surface names and availability belong in dated evidence and the [architecture inventory](../product/architecture.md#chatgpt-work-and-codex-are-separate-authority-surfaces).

Physical display and autonomous computer use are separate. Use upstream-supported headless computer-use implementations; do not give arbitrary execution the sensitive human kiosk session. A virtual display alone is not a security sandbox.

Remove Happy/Happy Remote/Gemini CLI; retire the separate Cowork component ID but retain its intended functionality under Claude Desktop. Retain Antigravity Remote and implement its real single-owner service contract. Add Happier/Hermes/Pi/OMP as independent package families/components.

Assbox does not own an agent orchestrator, universal remote UI, ACP broker or computer-use model loop. It owns packages, configuration, authority/placement, network policy, lifecycle and recovery. Preserve pure-core/effectful-shell separation and normal Nix configuration authority.

## Consequences

The installer becomes simpler without reducing advanced choices. Engineering must complete standalone egress, exact helper packaging, protected native kiosk/Cowork and headless capability integration; these are not solved merely by selecting package names. Existing storage/identity/release safety remains in force.

Account and same-execution-domain exposure remain explicit. Do not assert Claude history-scope exclusion, universal protocol compatibility, immutable mutable-helper downloads, or security from same-UID service/display labels. Tests and dated support records establish evidence independently from this architectural decision.

## Changing this decision

A change to default enrollment, execution placement, privileged device access, credential authority, mutable-runtime policy, component auto-installation or orchestration scope requires an explicit reviewed amendment and corresponding migration/acceptance work. Routine upstream feature changes update support evidence and adapters; they do not silently redefine the product.
