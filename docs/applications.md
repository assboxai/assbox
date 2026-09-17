# Components, applications and remote access

Assbox installs any explicit selection from [the reviewed catalog](../catalog/components.json).
Every optional component defaults off. Nano and tmux remain in the base. A package,
a remote service and graphical autostart are separate choices. Nothing selects an
extra agent implicitly, including OpenClaw and ChatGPT Desktop.

Successful `assbox component setup opencode-server` or `openclaw-gateway` starts
the managed backend. It also opens the corresponding frontend if selected in
`assbox.session.autostart` and a graphical session is active. With no active session,
a selected frontend waits for the next graphical login. Closing a window normally leaves it closed;
background backend restarts do not reopen it.

OpenCode setup publishes its password file atomically and preserves an existing
valid password. Every managed server/frontend start validates
`~/.config/assbox/opencode.env` before launching OpenCode. The file must be a private
regular file owned by `agent`, with one `OPENCODE_SERVER_PASSWORD=...` assignment:
a nonempty printable ASCII password without whitespace, quotes or backslashes,
optionally followed by one newline. Custom plain passwords remain supported;
shell syntax, quoted values, comments and additional assignments are rejected.
If interrupted older setup left an invalid file, restore the valid private file
or remove it and rerun `assbox component setup opencode-server` as `agent` to
generate a new password. Invalid existing files are never silently replaced.

The OpenClaw dashboard keeps its Chromium profile in
`~/.local/share/assbox/openclaw-browser`. Browser authentication persists across
service restarts, and ordinary Chromium windows have an independent lifecycle.
Existing dashboard users must authenticate once in this separate profile;
credentials from the ordinary browser profile are not copied. Both browsers still
run as the same agent account.

Run `assbox component list` to see IDs, dependencies, proprietary-package consent,
known mutable helpers and unavailable capabilities. `assbox component set
codex,gemini-cli headless` stages that complete selection for reboot. It rejects
missing dependencies; the installer previews dependency expansion and asks before
adding them. Use `--accept-unfree` for proprietary packages. Additional settings,
including mutable-helper consent and graphical launchers, use ordinary `local.nix`.
Component changes remove incompatible installer-generated launcher defaults.
Explicit launcher overrides in `local.nix` must still be removed when removing
their owning component or changing to headless presentation.
When selecting Happy Remote during installation, explicitly choose its Codex/Claude
backends; the installer includes those selected packages. Selecting an SSH editor
host asks for its separate agent public key and enables tailnet-only access.

## Selection examples

```nix
assbox.components = {
  claude-code.enable = true;
  claude-code-remote = {
    enable = true;
    workingDirectory = "/home/agent/projects/my-project";
  };
  gemini-cli.enable = true;
};
assbox.acceptUnfree = true;
assbox.presentation = "headless";
```

After boot, run `sudo -iu agent assbox component setup claude-code-remote`.
Complete provider login, workspace trust, Remote confirmation and pairing in the
interactive terminal. Exit the foreground setup session with Ctrl-C, then explicitly
confirm service start. This records permission to start that configured service;
it is **not** proof of successful authentication or a remote task. Changing its
settings requires onboarding again; ordinary package updates retain identity.

```nix
assbox.components.chatgpt-desktop = {
  enable = true;
  allowMutableCode = true;
};
assbox.acceptUnfree = true;
assbox.presentation = "x11";
assbox.session.autostart = [ "chatgpt-desktop" ];
```

ChatGPT Desktop uses the existing X11 session wrapper. ChatGPT and Claude Desktop
include Chromium for browser-based login. They may provision additional executable
code in the agent home. Their package installation does not establish remote pairing.

## Available integrations and boundaries

| Selection | Behavior |
| --- | --- |
| `codex`, `claude-code`, `gemini-cli`, `grok`, `opencode`, `cursor-agent`, `antigravity-cli`, `openclaw`, `happy` | Independent CLI packages; no Assbox daemon starts just from installing them |
| `claude-code-remote` | Foreground Claude server in an explicitly trusted project; account/workspace eligibility is upstream |
| `cursor-worker` | Personal worker using outbound connectivity; optional `computerUse.enable` requires X11 and an explicit display, with no virtual-desktop fallback or desktop-sharing mode |
| `openclaw-gateway` | Loopback gateway on port 18789, configured using `assbox component setup openclaw-gateway` |
| `openclaw-node` | Foreground node connected to `gatewayHost`/`gatewayPort`; TLS is required off loopback; node pairing must be approved on the trusted Gateway |
| `opencode-server` | Loopback service on port 4096; setup creates a private server-password file and performs provider login |
| `happy-remote` | Foreground Happy supervisor; explicit nonempty `backends = [ "codex" "claude-code" ]` names installed runtimes, not a security allowlist |
| `vscode`, `zed`, `vim`, `emacs` | Optional editors; Emacs defaults to terminal, with `variant = "gui"` available in headed configurations |
| `vscode-remote-host`, `zed-remote-host` | Agent SSH development hosts without installing the desktop editor; require agent SSH and mutable-helper consent |
| `vscode-cli`, `vscode-tunnel` | Fixed-hash standalone `assbox-vscode` CLI and separately enabled tunnel; login and server-license acceptance are interactive |
| `claude-desktop` | Linux graphical app, optionally started by the owned graphical session |

Grok's ambiguous `agent` alias is not exported. Use `grok`, `cursor-agent` and
`assbox-vscode`; the desktop VS Code retains `code`. Additional executables inside
an upstream package are not a promise of separate curated integrations.

The following catalog entries deliberately reject enablement:

- `chatgpt-remote`: current upstream Remote instructions establish Mac/Windows,
  but do not establish Linux pairing support.
- `cowork-dispatch`: the packaged Linux VM execution and required device permissions
  have not been established within Assbox's unprivileged account boundary.
- `antigravity-remote`: the pinned CLI documents installation of its own OS service;
  a reviewed foreground daemon contract is still needed.

These are unavailable capabilities, not passing or partially working adapters.
See [research and qualification](component-acceptance.md) for evidence and remaining work.

## Mutable code and shared state

`allowMutableCode` acknowledges a component's known downloaded helpers. It is not a
sandbox or a machine-wide download prohibition. VS Code clients manage their server,
extensions and language tools; Zed provisions a matching server. The selected VS Code
host/tunnel enables NixOS's `nix-ld` loader for compatibility on that machine; it does
not provide isolation. No pinned Zed server mode is maintained.

Happy bundles the Claude Agent SDK even when using another backend. Its pinned daemon
also starts a Happy Terminal companion that can provision code. OpenClaw node session
hosting requires separate `sessionHosting.enable = true` and `allowMutableCode = true`:
the trusted Gateway supplies worker artifacts with its own update authority. Configure
pairing in the private agent home before node onboarding. Assbox does not bypass
OpenClaw's artifact, device-authority or revocation checks, and does not enable Docker.

All applications share the `agent` account and can access that account's projects and
credentials. Separate unit names and state directories are not isolation. Do not place
secrets in Nix, Git, command-line arguments or global environment configuration.
Provider-owned state stays in its supported home location; Assbox does not invent
credential formats or isolate HOME in ways that break provider integration.

Remote onboarding scripts run interactively as `agent`, outside build/activation.
New remote units retry with a delay capped at five minutes and suppress provider output in the
ordinary system journal because it may contain pairing material. `sudo assbox doctor`
inspects both the system and agent user manager. It reports each configured unit's
load/active/substate, result, exit code, restart count and condition result. A failed
inspection is reported as unknown; an active process does not prove provider readiness.
The same inspection is available by running `assbox doctor` as `agent`.

For the five managed remote adapters, run `sudo -iu agent assbox component diagnose ID`.
This temporarily stops that unit and runs the same command under a transient user
service for at most five minutes, with up to ten seconds to terminate its process
group. At most 1 MiB of output is captured in a new mode-0600 file under the agent's
mode-0700 `~/.local/state/assbox/diagnostics` directory. The output is never relayed to
the ordinary journal or printed by the helper. Treat the file as credentials, inspect
it locally and delete it afterward; do not share it unredacted. This is an opt-in
diagnostic action, not continuous logging or provider monitoring.

Cancellation stops the diagnostic group. The original service is restored only if
it was running/retrying before capture and, for Cursor computer use, its graphical
session still exists. A service that was stopped stays stopped. Onboarding and
diagnostics for the same adapter cannot run concurrently. Re-onboarding stops the
managed unit before interactive login; canceled setup leaves it stopped until an
explicit start or later boot. Successful setup explicitly restarts it.

Expired credentials require provider
login; the managed service keeps retrying without a permanent start-count lockout. No background
probe continuously calls provider APIs or declares account eligibility.

Disabling a component stops its managed unit after activation/reboot, without deleting
credentials, projects, cached helpers or old generations. Maintenance retains its
existing reboot policy and may interrupt active jobs. No exactly-once execution,
conflict-free shared checkout, or automatic restoration of mutable tasks is promised.

## Graphical session ownership

Use `assbox.session.autostart` with `chatgpt-desktop`, `claude-desktop`, `vscode`,
`zed`, graphical `emacs`, `opencode-attach` or `openclaw-dashboard`. Each launcher
requires its owning component. Both X11/Openbox and Wayland/labwc include a terminal.
Session wrappers own `graphical-session.target` and clear stale display variables;
GUI units stop with that target. Headless services remain independent. Cursor's
explicit X11 computer-use worker follows the graphical target as well.

X11 uses LightDM's greeterless autologin. Logout, Openbox failure and X-server
failure cause a fresh agent session and its selected launchers to start, with
systemd restart backoff. The agent password stays locked; administrative login
uses a text console or explicitly enabled admin SSH. `sudo systemctl stop
display-manager` deliberately stops X11 and does not trigger another login.

## SSH and Tailscale

```nix
assbox.network = {
  tailscale.enable = true;
  ssh.agent = { enable = true; keys = [ "ssh-ed25519 REPLACE_WITH_PUBLIC_KEY" ]; };
};
assbox.components.zed-remote-host = { enable = true; allowMutableCode = true; };
```

Log in to Tailscale from the local admin console with `sudo tailscale up`; Assbox sets
ordinary overlay networking, Tailscale SSH off, route acceptance off and its own
firewall policy. Connect the editor as `agent`, never as administrator. Admin SSH
uses separately enabled `ssh.admin` and its own keys. The installer explains that
supplying an admin key enables tailnet-only access and requires console onboarding.

For LAN access, set `ssh.exposure = "lan"` and explicit `ssh.lanInterfaces`; optional
`lanSourceCidrs` restrict sources further. An empty CIDR list admits any source on
those selected interfaces. Password/root login, agent forwarding and gateway ports
are disabled. Local forwarding is restricted to loopback destinations. No Funnel,
exit-node/subnet routing, trusted whole interface or agent Tailscale operator is added.
