# Application profiles

Exactly zero or one managed Assbox application is selected through
`assbox.application`. OpenClaw's extra Codex and OpenCode executables are tools in
that one profile, not additional managed profiles. Application state is retained
when selecting another profile; switching is not credential revocation or secure
erasure.

## None

`none` installs the substrate and toolbox only. Headless provides local console and
optional key-based SSH administration. Console-only does not run sshd. X11 and Wayland provide a minimal graphical session
and terminal as the unprivileged agent. Neither mode requires an AI application.

## ChatGPT Remote

ChatGPT Remote works on Linux; this is the main use case for the ChatGPT profile.
The current profile requires X11 and launches the Linux application through
LightDM/Xorg/Openbox. It includes Codex and a browser (Chrome on x86-64, Chromium
on AArch64). A future supported headless mode can be added without changing the substrate/application separation. No claim is
made that an untested Wayland path has been accepted.

Sign in to the application in the local graphical agent session. Authentication is
not embedded in the flake. The profile uses Electron's basic password storage to
avoid an unattended keyring prompt; this is not encrypted protection against theft
of the agent home. Independent disk encryption is not configured by this installer.
Treat access to the appliance and its state accordingly.

## OpenCode

The selected package supplies a terminal client and the headless `opencode serve`
service. Assbox binds its service to `127.0.0.1:4096`, never directly to the LAN.
Before the service starts, onboard as the agent:

```sh
sudo -iu agent assbox application setup
```

The helper runs OpenCode authentication interactively, creates a private service
password file at `~/.config/assbox/opencode.env` if needed, and restarts the NixOS
user service. Existing private password files are not overwritten. Credentials are
not printed by the helper. Use the upstream OpenCode CLI or a deliberate local/
SSH-tunneled client configuration to connect. The headed profile opens an attached
terminal client; it does not install Chromium or disable server authentication.
A separately requested browser can be added through ordinary local packages.

## OpenClaw

The profile installs OpenClaw, Codex and OpenCode. It runs a loopback gateway at
`127.0.0.1:18789` after configuration exists:

```sh
sudo -iu agent assbox application setup
```

The helper runs `openclaw onboard --skip-daemon` because NixOS, not an application
self-installer, owns the service. Complete provider and gateway authentication in
upstream onboarding. Keep gateway token authentication enabled; Assbox does not
silently generate an unauthenticated network endpoint. NixOS starts
`assbox-openclaw.service` as a user service. OpenCode and Codex are available tools;
the OpenCode server is not additionally started under this profile.

Onboarding and external providers change independently of the substrate. Test
actual authentication, browser workflows, job shutdown and restart with the locked
application versions before promoting a release. A package building successfully
does not establish that a remote provider still accepts its protocol.

## Service and access model

Agent services use a private home, restrictive umask, no privilege escalation,
restart-on-failure and a bounded stop timeout. Headless services are enabled in the
agent's lingering user manager; a local GUI is not required for startup. Graphical
ChatGPT follows the graphical session target. Graphical profiles autologin the
agent, not the administrator.

The X11 session wrapper owns `assbox-graphical-session.target`, which pulls in the
passive `graphical-session.target` as a dependency. It imports the current display
and authorization environment before starting application units. Normal Openbox
exit, a failed launch, and catchable termination signals stop the graphical targets
and clear that environment. A later login first clears stale state left by an
uncatchable termination. The NixOS fake-session helper is not a second owner.
Wayland starts the same Assbox target from labwc autostart once the display exists.
This lifecycle does not stop the independent headless OpenCode/OpenClaw services.

Use a local console or SSH as `admin`, then explicitly become `agent` to onboard.
The locked agent password does not prevent root from using `sudo -iu agent`.
Never paste admin credentials into an agent session. APIs bound to loopback may be
reached through SSH tunnels; do not open firewall ports merely to work around
upstream authentication. These services can execute code with the agent's access;
they are not independent hostile-workload sandboxes.

## Upstream interfaces

The package input is [llm-agents.nix](https://github.com/numtide/llm-agents.nix).
Runtime interface references are [OpenCode server](https://opencode.ai/docs/server/)
and [OpenClaw documentation](https://docs.openclaw.ai/). These links describe upstream
interfaces, not completed Assbox acceptance tests.

## Headed clients and architecture acceptance

The package set is selected natively for x86-64 or AArch64. Both are declared
configuration targets; build and authenticated application acceptance are still
required for each promoted version. Do not assume a successful Nix evaluation
proves an ARM Electron/browser session works in a particular VM.

After onboarding, headed OpenCode opens a terminal running `opencode attach` against
the loopback service. Its server password is supplied through a private environment
file, not an argv string. Headless users can attach from the agent's terminal too.
Headed OpenClaw opens Chromium at the fixed loopback Control UI URL. Authentication
is completed in the browser with upstream onboarding credentials; no token is
embedded in its command line or URL. A browser starting before a gateway is ready
may need a reload. Assbox does not bypass Control UI authentication for convenience.

Application service files and these clients are integration definitions, not claims
that provider authentication, remote tasks or graphical startup have passed tests.
Upstream interfaces are documented by [OpenCode](https://opencode.ai/docs/cli/) and
[OpenClaw](https://docs.openclaw.ai/web/control-ui); review changes against the locked
package versions rather than following a moving installer script.
