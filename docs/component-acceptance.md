# Component research and qualification

The original package research was reviewed 2026-09-16; the supplied plan's dated
provider evidence is maintained separately in the [Linux capability matrix](product/linux-computer-use-support.md).
This operational gate inventory is updated for the current source candidate.
Native component builds, new VMs, authenticated tasks and
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
  The candidate's selected virtual-desktop path supplies X11/TigerVNC/XFCE and
  screenshot/input helpers for Cursor's provider-managed headless desktop. The
  resource wrapper scrubs physical session state and holds a single desktop lease;
  it does not select the controller display. Exact tool and optional sharing
  behavior still needs independent [computer-use qualification](product/computer-use.md).
- [OpenClaw node registration at v2026.9.4](https://github.com/openclaw/openclaw/blob/v2026.9.4/src/cli/node-cli/register.ts):
  `node run` is the foreground host, distinct from daemon installation and the private
  worker command. [Session hosting](https://docs.openclaw.ai/nodes/session-hosting)
  is separately enabled and receives executable artifacts from the paired Gateway.
- Happier uses the pinned foreground-service contract and `scripts/providers/happier_contract.py` dry-run/path oracle. Real pairing and session qualification remain separate.


## ChatGPT Remote qualification

ChatGPT Remote is selectable with Desktop/X11. Qualify Linux account pairing,
guest SSH project selection, a real edit/approval cycle, restart recovery, and
refusal to substitute controller execution. Desktop launch alone is insufficient.
See [worker acceptance](worker/acceptance.md).

## Explicit unresolved capabilities

| Capability | Evidence and required resolution |
| --- | --- |
| Claude Cowork | Ordinary selected cloud behavior follows the post-6-October contract, observed for the actual account/build. Eligible local provider VM modes require their own immutable contract, entitlement/isolation observations and explicit prerequisite selection. The retired `cowork-dispatch` ID is not an activation path. |
| Antigravity Remote | Selection stages the adapter when its reviewed foreground argv is empty. An immutable configured argv declares one Assbox-owned unit; setup and runtime compatibility remain separate. Do not nest service installers. |
| Native ChatGPT/Claude | Public launchers and autostart call the native policy supervisor. No contract ships qualified. Missing, ineffective or stale evidence leaves the affected app inactive; worker selection cannot waive the gate. |
| Direct Codex relay | Advanced staged adapter requires its own foreground contract and client/auth evidence. It cannot run alongside Happier's daemon until that coexistence is separately designed and qualified. |

Staged selection is different from active capability. Credential-free fixtures may
build a staged configuration and verify its refusal; that is not a provider or
native-policy pass. A supplied contract still needs exact runtime and account evidence.

## Automated gates

- `scripts/component_catalog.py --check`: generated Rust and release-family drift,
  unique IDs/exports, known dependencies, cycles and metadata shape.
- Rust tests: parsing, canonical rendering, explicit dependency expansion,
  proprietary consent, blocked capabilities and presentation constraints.
  The real generated installer settings and edited selections are parsed/evaluated
  by Nix with consent, both SSH roles and the frozen instance/worker selections present.
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
  the ChatGPT-only VM checks its installed guarded executable and refuses launch
  without native policy evidence. It does not authenticate or open an unrestricted
  native window to discover whether enforcement works.
  New remote units must remain dormant before interactive onboarding. None of
  these credential-free VMs certifies provider login or completed remote tasks.
- `remote-lifecycle-vm`: real production adapter modules and systemd user units with
  harmless substitute provider programs. It exercises onboarding, repeated failures
  beyond the former start limit, clean-exit stop, explicit stop, descendant
  cleanup, foreground GUI crashes with surviving helpers and normal close, graphical-session teardown,
  structured doctor output, private diagnostic capture, changed settings and
  component removal through NixOS reconfiguration. Only restart delays are shortened;
  native execution remains required on both architectures.
- `computer-use-vm`: real execution-UID Xvfb/Xauthority/private D-Bus,
  screenshot/input, occupied-lease refusal, cancellation/cleanup and private
  sandboxed Chromium against a local page. This unrun substrate gate does not
  qualify a provider tool loop or native consumer computer-use feature.
- `editor-vm`: actual packaged VS Code, Zed and GUI Emacs on X11. It requires visible
  windows, kills only each main process, verifies recovery, closes windows normally,
  and checks recovery after Openbox failure, X-server failure and logout without
  manually restarting the display manager. Explicit manager stop must clean up
  the graphical session and leave it stopped. Wayland and hardware behavior also require
  the owner-run acceptance below. It also copies the locked, unwrapped rust-analyzer
  to the agent home with a conventional GNU/Linux interpreter and no RPATH, then
  requires real LSP initialize/shutdown handshakes through both the login shell and
  a user service with `NoNewPrivileges`. This tests loader/library compatibility
  without live downloads or provider accounts; it does not claim to test Zed's
  downloader or every upstream release. This VM gate has not yet been executed.
- `desktop-services-vm`: real X11 and Wayland sessions with GTK file chooser portals.
  The driver operates visible open-file, open-folder, save and cancel dialogs and
  verifies their returned responses/paths, then repeats after session restart and
  reboot. It also completes GNOME's first-use passwordless-keyring prompt, including
  the unencrypted-storage confirmation, and verifies a disposable Secret Service
  credential across fresh client processes, session restart, daemon restart and
  reboot, then checks deletion and private file permissions. It retains the
  production locked-password autologin account and uses no seeded keyring files.
  A Zed-only selection supplies Chromium: the real session URL handler must open a
  disposable loopback page whose JavaScript completes a callback, then its test
  browser must stop. HTTP/HTTPS associations and the callback are checked again
  after session restart and reboot. No browser flags or disabled sandbox are injected.
  On Wayland it also kills greetd's actual MainPID four times, crashes labwc, and
  requests normal logout. Each recovery must replace the compositor and a session-bound
  fixture service, remove their old processes/children, and restore dialogs, credentials
  and browser callbacks without manually starting greetd. An explicit stop must keep
  the session stopped beyond the maximum restart delay. Production delays are retained.
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
4. **Happier:** test independently selected coding CLIs, pairing and device
   removal, terminal/remote handoff, relay outage, shutdown and reboot. Verify the
   pinned dry-run service contract, one Nix supervisor, managed executable paths
   and scoped state. Do not use vendor service installation as configuration.
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
   and wrong-key rejection. Run Pi/OMP/Antigravity and multiple frontends together;
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
