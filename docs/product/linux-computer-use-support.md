# Linux browser and computer-use support

**Reviewed:** 2026-10-02. **Scope:** Dated upstream Linux capability evidence; not installed Assbox qualification or installer policy.

This is dated upstream evidence, not a release compatibility certificate. All Assbox paths below remain **not run** with no qualification evidence. The selected application, authentication mode, package/helper build and display backend must pass their own release tests before being advertised as qualified.

| Product path | Linux browser actions | Linux arbitrary desktop control | Sources |
|---|---|---|---|
| ChatGPT Desktop (Linux native app) | Documented browser actions in the Linux preview. | Other desktop-app control is not yet supported in the reviewed release entry. | [S18](sources.md#s18), [S53](sources.md#s53) |
| Claude Desktop / Cowork (Linux beta) | Built-in browser rollout includes Linux beta; account/rollout dependent. | Reviewed native screen-control support lists macOS/Windows, not Linux. | [S56](sources.md#s56), [S57](sources.md#s57) |
| Claude Code built-in computer-use feature | Separate browser integrations are outside this native screen-control feature. | Not supported on Linux by the reviewed CLI documentation; interactive macOS preview. | [S17](sources.md#s17) |
| Cursor self-hosted worker | Documented with installed Chrome/Chromium. | Documented Linux X11 capture/input; headless TigerVNC/XFCE path. | [S22](sources.md#s22), [S40](sources.md#s40) |
| OpenClaw Gateway | Documented managed browser path. | Labs/opt-in Linux managed desktop and separately enabled computer tool. | [S23](sources.md#s23) |
| Hermes browser / Cua Driver / Bot Screen | Documented local and cloud backends; inspect any local sidecar behavior. | Documented Linux X11/Wayland paths with display, AT-SPI and capture prerequisites. | [S12](sources.md#s12), [S58](sources.md#s58), [S59](sources.md#s59) |
| OMP v18.1.19 computer prelude / selected Nix build | Separate browser prelude is documented; browser runtime/helper still needs its own test. | Versioned docs describe Linux X11 input/capture and conditional Wayland support. | [S29](sources.md#s29), [S33](sources.md#s33) |

## Exact-path qualifications

The reference requirement IDs below identify implementation acceptance work. Actual source and runtime results belong in the [implementation ledger](../implementation-status.md), not in a silently promoted upstream-support field.

### CU01 — ChatGPT Desktop (Linux native app)

**Reviewed:** 2026-10-02. **Assbox status:** not run; no evidence.

**Scope and limits:** Native product on its documented Linux distributions; NixOS and exact client/policy still require qualification.

**Implementation requirement:** Keep kiosk browser consent separate from local Work/Codex execution. No Xvfb workaround is advertised as enabling native screen control.

**Qualification references:** A089, A112, A114.

**Upstream evidence:** [S18](sources.md#s18), [S53](sources.md#s53).

### CU02 — Claude Desktop / Cowork (Linux beta)

**Reviewed:** 2026-10-02. **Assbox status:** not run; no evidence.

**Scope and limits:** Native Desktop browser bridge can be needed even when Cowork runs in the cloud; it must remain open/online.

**Implementation requirement:** Qualify private browser state and selected local authority. Do not equate cloud Cowork with a remote browser or import personal cookies automatically.

**Qualification references:** A062, A063, A068, A114.

**Upstream evidence:** [S56](sources.md#s56), [S57](sources.md#s57).

### CU03 — Claude Code built-in computer-use feature

**Reviewed:** 2026-10-02. **Assbox status:** not run; no evidence.

**Scope and limits:** Native CLI feature, not Claude models used through OpenClaw/Hermes/OMP or another Linux-capable tool.

**Implementation requirement:** Do not present a Linux virtual display as enabling this feature. A separately selected harness needs separate authentication, tools and evidence.

**Qualification references:** A070, A114.

**Upstream evidence:** [S17](sources.md#s17).

### CU04 — Cursor self-hosted worker

**Reviewed:** 2026-10-02. **Assbox status:** not run; no evidence.

**Scope and limits:** Explicit computer-use opt-in; desktop sharing is separate. Agent loop/tool placement follows the self-hosted contract.

**Implementation requirement:** Use pinned cursor-agent, required packages and provider-owned display lifecycle; scrub inherited DISPLAY and qualify viewer/cleanup behavior.

**Qualification references:** A069, A071, A074, A114.

**Upstream evidence:** [S22](sources.md#s22), [S40](sources.md#s40).

### CU05 — OpenClaw Gateway

**Reviewed:** 2026-10-02. **Assbox status:** not run; no evidence.

**Scope and limits:** TigerVNC/XFCE with private D-Bus; enabling a Desktop panel is not enabling CUA.

**Implementation requirement:** Pin helper dependencies and require separate tool consent. Reject unrelated RFB listener selection; keep human viewing and active tool control distinct.

**Qualification references:** A068, A069, A072, A075, A114.

**Upstream evidence:** [S23](sources.md#s23).

### CU06 — Hermes browser / Cua Driver / Bot Screen

**Reviewed:** 2026-10-02. **Assbox status:** not run; no evidence.

**Scope and limits:** Current upstream feature docs; exact Hermes/Cua pin required. Native Wayland is opt-in, with documented capture/XWayland caveats. Bot Screen is provider-owned headless Xfce/TigerVNC.

**Implementation requirement:** Prefer a qualified upstream Bot Screen when included in the pin; otherwise qualify the selected existing-display path. Preserve private egress and do not infer same-UID isolation.

**Qualification references:** A039, A068, A070, A071, A114.

**Upstream evidence:** [S12](sources.md#s12), [S58](sources.md#s58), [S59](sources.md#s59).

### CU07 — OMP v18.1.19 computer prelude / selected Nix build

**Reviewed:** 2026-10-02. **Assbox status:** not run; no evidence.

**Scope and limits:** Upstream release-binary capture limits differ from the baseline-referenced Nix build enabling wayland-pipewire. Neither establishes compositor/portal success.

**Implementation requirement:** Qualify exact compiled features, permissions and capabilities on each display backend. Keep computer use off until selected; no generic Wayland pass from X11 results.

**Qualification references:** A068, A070, A071, A114.

**Upstream evidence:** [S29](sources.md#s29), [S33](sources.md#s33).

## How to use this evidence

A limitation of a native consumer application is not a limitation of the same model used through another Linux-capable harness. An API or alternative harness needs its own tools, authentication and qualification; it is not automatic feature parity.

Browser automation is not arbitrary desktop control. A virtual display is an execution resource, not a security boundary between same-UID agents, and installing Xvfb cannot enable an unsupported native feature. Current upstream docs and differently compiled release binaries must not override evidence about the exact selected Nix closure.

Update this dated matrix when qualifying a release; retain the actual source date, package revision, compiled features and test record. Missing or stale evidence is neither a pass nor proof that a route cannot work. Do not fetch this table at boot or use it as a substitute for the native activation policy.

Stable environment and authority rules are in [computer-use policy](computer-use.md). The [source register](sources.md) preserves the provider claims and dates.
