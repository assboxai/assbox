# Applications and service ownership

Choose Assistant, Coder, Kiosk or Custom in `assbox install`. `assbox configure` previews the same purpose-first selection on an installed machine; `--apply` builds and stages it for reboot. The generated components and exclusions are explicit Nix values. Changing preset data later does not add tools to an installed machine. Keep hand-written settings in `local.nix`.

Assistant OpenClaw and Hermes, and the integrated Coder Happier default, select Codex, Claude Code, Antigravity CLI, Cursor Agent, Grok, OpenCode, Pi and OMP. Remove any CLI individually. Other native/SSH routes start with a minimal selection. All selected tools on one execution instance share its `agent` identity and scoped credentials.

| Component | Managed behavior |
|---|---|
| `codex`, `claude-code`, `cursor-agent`, `antigravity-cli`, `grok`, `opencode`, `pi`, `omp` | Pinned independent CLIs; installation does not authenticate or start a remote service |
| `happier`, `happier-daemon` | Pinned client and Nix-owned `daemon start-sync --takeover`; hosted E2EE relay by default, endpoint override supported |
| `openclaw`, `openclaw-gateway`, `openclaw-node` | Upstream Assistant experience; managed gateway/private dashboard or explicitly paired node |
| `hermes`, `hermes-gateway`, `hermes-dashboard` | Foreground gateway, persistent Hermes home and separately selected loopback dashboard |
| `claude-code-remote`, `cursor-worker`, `vscode-tunnel` | Separate upstream-native routes with explicit setup and configuration-bound markers |
| `antigravity-remote`, `codex-relay` | Staged until an immutable foreground runtime contract is configured; Codex relay is Advanced/experimental |
| `chatgpt-desktop`, `claude-desktop` | Guarded native launchers; exact release/account/platform policy qualification required |
| `chatgpt-remote` | Separate mobile-host selection requiring the desktop; Linux availability still needs its own qualification |
| `chromium` | Manual presentation or explicitly selected web kiosk; no automatic native policy equivalence |

Happy, Happy Remote, Gemini CLI and Cowork Dispatch IDs and backend options were removed. No account migration or old data-directory deletion is performed. Cowork capability selection belongs to Claude Desktop.

For managed services, run as the execution user:

```sh
assbox component setup happier-daemon
assbox component setup hermes-gateway
assbox component setup openclaw-gateway
assbox component diagnose happier-daemon
assbox component stop happier-daemon
assbox component enable happier-daemon
```

Use only the commands for selected components. Setup, provider authentication and a successful task are separate observations. `stop` and `disable` persist an owner marker; `enable` clears it without granting setup, account access or native authority. Reconfiguration or a runtime contract change invalidates the relevant setup marker. Missing credentials are not an OS boot failure. Ordinary service output is suppressed; explicit diagnostics capture bounded private files.

Happier setup uses `happier auth login --no-open --method web`. This does not require inbound SSH or Tailscale. Owner-initiated `happier auth pair-remote --ssh user@host --json` is a separate trusted-client procedure: verify the target key/user/server/account and qualify its credential and service side effects first. Do not import a whole HOME or run its service installer. Pi/OMP CLI availability does not imply a built-in Happier adapter. Dynamic bridges and client-managed helpers require the disclosed consent and their own qualification; managed binaries remain owned by Nix.

A configured direct Codex relay cannot run alongside `happier-daemon`; their shared Codex runtime/session ownership has not been qualified. Retire one route explicitly before activating the other. An empty relay contract may remain staged. SSH remains an independently keyed entry point and starts no persistent Assbox Codex service; concurrent client-owned Codex sessions still require upstream session and credential qualification.

## SSH and Tailscale

Workload SSH is separately selected with explicit keys and exposure; external Desktop SSH connects to the standalone execution user. Administrator SSH uses a separate identity. Tailscale support is a deselectable installer default, while enrollment and approved exposure remain owner actions. Its control socket is root-only.

Hermes dashboard's recommended profile requires the exact non-loopback HTTPS URL and native password/OIDC setup. Its backend binds `127.0.0.1:9119`. Select it explicitly, set `assbox.components.hermes-dashboard.publicUrl`, and approve a matching `assbox.network.tailscale.serveMappings` entry if wanted. Enrollment, tailnet grants and application authentication remain owner steps. Advanced `accessProfile = "tunnel-only"` also requires `consentTunnelOnly = true`; it does not claim native app authentication and is not a fallback for broken authenticated HTTPS.

Supported public URLs use a DNS name or canonical non-loopback IPv4 address and an optional valid port. Localhost names, ambiguous numeric hosts, credentials, query strings and fragments are rejected consistently by the guided and raw Nix paths. Listener reachability still does not prove native authentication or secure cookies.

For a dashboard published through Serve, use `sudo assbox component stop hermes-dashboard` (or `disable`). The owner helper records the disabled state, withdraws its owned exposure and then stops the backend. It preserves unrelated Serve paths. `enable` does not grant application authentication or enroll the host.

Native Kiosk requests `assbox.kiosk.localExecution = "none"` by default. Protected local Code selects `"managed-worker"` and the required guest tools. Both modes still need each app's native gate. ChatGPT Codex Local, Work Local, Work Cloud local access, cloud-only operation, browser actions, computer use, helpers and SSH are checked separately. Routing Code to SSH does not route Work or disable controller-local execution. Cloud tasks and local Cowork/provider VM are separate opt-ins and separate evidence scopes. Raw app installation is not an enforcement result.

For an explicit web kiosk, `assbox component stop chromium` durably stops every selected web-kiosk browser and any declared ordinary Chromium launcher. `enable chromium` starts those declared units again. The corresponding stop/enable controls also cover autostart VS Code, Zed and graphical Emacs. A selected CLI or manual GUI without a declared service has no managed stop control.

Computer-use resources are opt-in on execution instances. Cursor uses its upstream-managed private desktop. For a provider that needs supplied display resources, use `assbox-computer-use display -- omp` or the Hermes managed gateway's display wrapper. Browser-only resources do not install the virtual desktop stack. Physical presentation and execution desktops are separate; no autonomous resources are enabled on a sensitive native controller.

See [product contract](product/index.md), [status](implementation-status.md), [network/security](product/access-and-security.md), [state and resources](resources.md), and [qualification](../qualification/README.md).
