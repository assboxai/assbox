# Component research and qualification

Research reviewed 2026-09-16. Native component builds, new VMs, authenticated tasks and
Intel Mac acceptance are **not run** for this expansion. Source inspection and the
lightweight module tests are not substitutes. Record actual results against the
commit and package/client versions tested, outside the source tree.

## Pinned contracts

The initial independent agent-family lock roots use llm-agents.nix revision
`7bba6197505fbc7e138a4922ac97061d2ec11b42`. Each root can advance or hold independently
through the existing whole-subgraph release mechanism. Commands, wrapper behavior,
proprietary consent and architectures were checked against its package recipes.

- [Claude Remote Control](https://code.claude.com/docs/en/remote-control): foreground
  `claude remote-control`, with interactive account/workspace trust and one-time
  confirmation. No API-key substitute, automatic approval bypass or telemetry
  disablement that would interfere with provider eligibility.
- [Cursor personal workers](https://cursor.com/help/ai-features/self-hosted-machines):
  personal login and foreground worker start. The pinned recipe exports `cursor-agent`.
  [Computer use](https://cursor.com/docs/cloud-agent/self-hosted/computer-use) supports
  an explicit existing X11 display. Assbox supplies its documented X11/ffmpeg helpers
  and excludes virtual desktop fallback and isolated desktop-sharing modes.
- [OpenClaw node registration at v2026.9.4](https://github.com/openclaw/openclaw/blob/v2026.9.4/src/cli/node-cli/register.ts):
  `node run` is the foreground host, distinct from daemon installation and the private
  worker command. [Session hosting](https://docs.openclaw.ai/nodes/session-hosting)
  is separately enabled and receives executable artifacts from the paired Gateway.
- [Happy's pinned CLI](https://github.com/slopus/happy/blob/04a9761a5bdb0e2685ad4da712d3654fd7c395f2/packages/happy-cli/src/index.ts)
  dispatches `daemon start-sync` to the foreground supervisor. The pinned
  [daemon implementation](https://github.com/slopus/happy/blob/04a9761a5bdb0e2685ad4da712d3654fd7c395f2/packages/happy-cli/src/daemon/run.ts)
  also starts a Happy Terminal companion. The package bundles Claude Agent SDK;
  backend selection must not be described as a vendor-code purity guarantee.
- [VS Code Tunnels](https://code.visualstudio.com/docs/remote/tunnels) supports the
  standalone CLI. The recipe pins upstream commit `8b640eef5a6c6089c029249d48efa5c99adf7d51`
  and separately measured SHA-256 hashes for both architecture archives. Its server
  remains client-managed code. SSH/tunnel hosts use NixOS's `nix-ld` compatibility
  loader only when those capabilities are selected.
- [Zed remote development](https://zed.dev/docs/remote-development) provisions a
  client-compatible server. Assbox does not maintain a second pinned-server mode.
- Graphical supervision uses the foreground application, preserving its exit status.
  The pinned [Zed CLI](https://github.com/zed-industries/zed/blob/v1.3.6/crates/cli/src/main.rs)
  detaches by default; its foreground option does not propagate the child's status.
  Assbox uses the Nix-wrapped `libexec/zed-editor`. VS Code receives a second entry
  point to its Electron application through the package's normal GTK/environment
  wrapping hook; the public `code` CLI retains its ordinary handoff behavior.
  These package paths are checked by `editor-vm` when pins change.

## Explicit unresolved capabilities

| Capability | Evidence and required resolution |
| --- | --- |
| ChatGPT Remote | [Remote instructions](https://learn.chatgpt.com/docs/remote) identify Mac/Windows. Establish supported Linux account pairing and a real edit/approval cycle before removing the blocker. Desktop launch is insufficient. |
| Cowork Dispatch | [Linux scope](https://support.claude.com/en/articles/13947068-assign-tasks-from-anywhere-in-claude-cowork) includes files/connectors/plugins, excluding computer use. Review and demonstrate the packaged VM/device-permission requirements without expanding agent administrative authority. |
| Antigravity Remote | [Documented start](https://antigravity.google/docs/remote-control/) installs an OS service. Review the pinned binary/source's exact foreground daemon contract, state and shutdown before adding an Assbox-owned unit. Do not nest service installers. |

These entries remain in the catalog for discoverability but reject enablement. No
unavailable capability appears in the passing configuration matrix. Removing a
blocker requires its adapter and regression coverage in the same reviewed change.

## Automated gates

- `scripts/component_catalog.py --check`: generated Rust and release-family drift,
  unique IDs/exports, known dependencies, cycles and metadata shape.
- Rust tests: parsing, canonical rendering, explicit dependency expansion,
  proprietary consent, blocked capabilities and presentation constraints.
  The real generated installer settings and edited selections are parsed/evaluated
  by Nix with consent, both SSH roles and Happy backends present.
- `tests/tooling/test_component_catalog.py`: real Nix module merging with inert
  package values; absence of implicit packages/services, onboarding gating, GUI
  lifetime, explicit mutable-code consent and access dependencies. No system build.
- Local remote-script tests execute the Nix-rendered onboarding and diagnostic
  scripts with substitute provider and user-manager commands. They check explicit
  permission, operation locks, private file modes, output limits, cancellation and
  restoration. Module tests also distinguish changed settings from package updates
  when computing permission markers. These tests do not execute systemd services.
- `component-*`, `mixed-cli`, `editors-x11`, `editor-hosts`, `full-x11` and
  `full-wayland` configurations: policy and native build checks. Existing base,
  BIOS, Apple and session fixtures remain.
- `closure-*`: actual system closure checked against known unselected curated
  package identities. This does not prove absence of obfuscated code inside opaque
  vendor binaries. Review known bundled SDKs and downloaded helpers separately.
- `application-<family>-vm`: native runtime checks for every independent family.
  Existing OpenCode/OpenClaw VMs test local authentication and session lifecycle;
  the ChatGPT-only VM checks its desktop executable and window while requiring
  standalone Codex to remain absent. It does not depend on Codex CLI setup.
  New remote units must remain dormant before interactive onboarding. None of
  these credential-free VMs certifies provider login or completed remote tasks.
- `remote-lifecycle-vm`: real production adapter modules and systemd user units with
  harmless substitute provider programs. It exercises onboarding, repeated failures
  beyond the former start limit, clean-exit recovery, explicit stop, descendant
  cleanup, foreground GUI crashes with surviving helpers and normal close, graphical-session teardown,
  structured doctor output, private diagnostic capture, changed settings and
  component removal through NixOS reconfiguration. Only restart delays are shortened;
  native execution remains required on both architectures.
- `editor-vm`: actual packaged VS Code, Zed and GUI Emacs on X11. It requires visible
  windows, kills only each main process, verifies recovery, closes windows normally,
  and checks recovery after Openbox failure, X-server failure and logout without
  manually restarting the display manager. Explicit manager stop must clean up
  the graphical session and leave it stopped. Wayland and hardware behavior also require
  the owner-run acceptance below. This new VM gate has not yet been executed.
- `desktop-services-vm`: real X11 and Wayland sessions with GTK file chooser portals.
  The driver operates visible open-file, open-folder, save and cancel dialogs and
  verifies their returned responses/paths, then repeats after session restart and
  reboot. It also completes GNOME's first-use passwordless-keyring prompt, including
  the unencrypted-storage confirmation, and verifies a disposable Secret Service
  credential across fresh client processes, session restart, daemon restart and
  reboot, then checks deletion and private file permissions. It retains the
  production locked-password autologin account and uses no seeded keyring files.
  The gate uses the same portal API as native Zed without provider credentials;
  it has not yet been executed. It complements rather than replaces `editor-vm`.
- `access-lan-vm` and `access-tailscale-vm`: real OpenSSH keys, privilege refusal,
  IPv4/IPv6 packets, untrusted ingress and disappearance of the admitted interface.
  The tailnet fixture simulates `tailscale0`; real overlay login remains below.
- Release report validation requires every family on both native architectures,
  with strict plan identity and missing/duplicate/contradictory evidence rejection.
  Final composed systems still pass the full release/security gates.

## Owner-run acceptance

For each result record the Assbox commit, architecture/hardware, selected components,
Nix package/derivation versions, local/mobile client versions, date, account/workspace
eligibility, observed outcome and limitations. Use `not run`, `passed` or `failed`;
never infer a provider result from installation or a setup marker. Redact credentials,
pairing URLs and project content. Recheck materially changed adapters/provider versions;
these procedures do not become an unattended daily phone-pairing requirement.

1. **Each CLI:** authenticate through the supported interactive flow; run a small
   project edit and test, request/deny approval, resize the terminal, exercise UTF-8,
   exit/restart and confirm the intended identity. Verify no other standalone agent
   appeared in the selected system closure.
2. **Claude Remote and Cursor:** onboard in a disposable project, initiate a task
   from the supported remote surface, edit/test, deny an action, cancel a task,
   disconnect/reconnect, restart the unit and reboot. Confirm expired/revoked login
   fails visibly with bounded retries. For Cursor X11, test screenshot/click and
   session teardown; unreachable explicit display must fail without a virtual desktop.
3. **OpenClaw:** test Gateway authentication and loopback listeners, then approve
   the node on a separate trusted Gateway. With session hosting off, verify hosted
   workers are unavailable. Explicitly enable it and execute a delegated task;
   record artifact provenance, exercise invalid-artifact rejection and pairing
   revocation. Confirm Gateway/node roles coexist without duplicate listeners.
4. **Happy:** test Codex and Claude backends separately and together, pairing and
   device removal, terminal/remote handoff, companion provisioning, relay outage,
   shutdown and reboot. Inspect SDK/helper inventory and private state permissions.
5. **VS Code SSH/tunnel and Zed SSH:** connect as `agent`; open a project, use a
   terminal, language server, edit/test and reconnect. Test both supported CPU
   architectures with matching clients. Confirm no host desktop editor is required,
   no administrative access is granted, and client-managed helper downloads are
   disclosed. For tunnels, test login, license confirmation and revocation.
6. **Graphical apps/editors:** launch every advertised session mode, test login or
   normal editing, including Zed Open File, Open Folder and Save As on both X11
   and Wayland. Follow the [keyring setup](configuration.md#machine-local-files),
   save a disposable provider credential through Zed and check its availability
   after logout/relogin and reboot. Existing encrypted collections must keep their
   password and prompt for manual unlock. Check OpenCode attach and OpenClaw
   dashboard separately from their backends. Test GUI Emacs only with its explicit
   variant; keep nano available for recovery.
7. **Access and coexistence:** authenticate the actual Tailscale account from console;
   test LAN denial, overlay-only SSH and tailnet disappearance. Test both SSH roles
   and wrong-key rejection. Run Gemini/Antigravity and multiple frontends together;
   check that auth/config files are not overwritten. Exercise distinct worktrees
   where available; do not expect independent agents to coordinate one checkout.
8. **Disable/update/recovery:** remove a selected service, stage and reboot, verify
   no managed process remains, then re-enable using preserved state. Confirm updates
   do not demand fresh onboarding solely because the package path changed. Verify
   existing installer/boot/credential/update-authentication gates and the separate
   [Intel Mac checklist](intel-mac-acceptance.md).

## Deferred tranche

Run complete native builds and VMs, provider procedures, coverage, mutations and
vulnerability scans when resource restrictions are lifted. Investigate their resulting
failures then. No Actions run or publication is needed to perform the inexpensive
local checks. Do not turn an unexecuted check into a green result or loosen an
existing safety boundary to make an optional integration appear supported.
