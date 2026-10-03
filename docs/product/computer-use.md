# Browser and computer use

Computer-use capability is independent of whether a monitor is attached and which frontend was selected.

| Capability | Contract |
|---|---|
| CLI only | Default; no managed browser/desktop provisioned or started |
| Browser automation | Qualified pinned browser/helper, sandbox enabled and private agent profile |
| Virtual desktop | Qualified provider-specific display/input/screenshot stack; optional authenticated viewing |

Prefer upstream-supported X11/TigerVNC/XFCE managed headless sessions for Cursor/OpenClaw. Prefer Hermes's own qualified Bot Screen when present in the selected pin. Use a small isolated-display resource wrapper for OMP or another pinned path only when an existing display is required. [S58–S59](sources.md#s58) Xvfb is a compatibility backend. Do not implement a universal Assbox Wayland session scheduler or computer-use agent loop. [S13](sources.md#s13), [S22–S23](sources.md#s22), [S29](sources.md#s29)

Scrub inherited physical display and session environment. Use private X authorization/D-Bus/browser state, handle stale locks and occupied RFB ports safely, and tear down owned resources. Default to one active computer-use desktop; qualify upstream parallel sessions before raising limits. Installing a dependency once does not make unlimited live instances cost-free.

The CLI-only mode omits the computer-use manifest and desktop closure. Browser mode does not install the display stack or permit the display entry point. `assbox-browser --remote-debugging-port=0` runs pinned headless Chromium with a fresh private profile/cache, the default sandbox and loopback debugging. The launcher refuses arguments that replace its profile, disable the sandbox or expose debugging to another address. Profile/cache state is removed when the owned process group stops; this resource does not import personal cookies or preserve browser authentication across sessions. An upstream adapter must explicitly support this executable/CDP path before it is qualified.

For another qualified upstream command, use `assbox-computer-use browser -- COMMAND` or `assbox-computer-use display -- COMMAND` as the execution user. That generic resource wrapper does not rewrite an upstream application's own browser settings. The wrappers run in user scopes bounded by `assbox.computerUse.memoryMaxMiB`; managed provider units keep their own supervised control group. The paths use the same single-session lease. The display bus remains a tracked foreground process, with bounded startup and process-group cleanup on failure or cancellation. Tool-loop integration remains provider-specific qualification work.

A separate display under one UID is not isolation from other same-UID processes. Autonomous tools must remain outside the protected kiosk controller domain. Do not supply physical `:0`, sensitive browser profiles, keyring sockets or accessibility context as a default fallback.

Human viewing is optional, private and authenticated. Distinguish view-only and control when upstream supports them; do not imply a view-only guarantee the protocol cannot enforce. No public raw VNC/X11/CDP listeners.

Capability claims must name the actual path. Browser actions are not arbitrary desktop control; a Claude/OpenAI API harness is not the same product/authentication mode as a consumer Desktop feature; and an Xvfb server does not enable an unsupported native agent feature. Package build flags may differ from upstream precompiled binaries. Qualify the exact selected closure and environment. [S17–S18](sources.md#s17), [S30–S33](sources.md#s30)

See [implementation status](../implementation-status.md) for what is actually present and tested.


See the [Linux browser and desktop support matrix](linux-computer-use-support.md) for dated provider facts, product/authentication scope, build caveats and separate Assbox evidence status. Updating that matrix does not enable a feature, alter an installed selection or qualify a binary. The permanent rule is independent capability selection with real tool/display evidence, not a frozen list of supported vendors.
