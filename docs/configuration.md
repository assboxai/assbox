# Local configuration and packages

> **Native controller deployments:** Native None requests no local execution and remains inactive until exact policy qualification. Protected local Code uses the [managed worker](worker/controller-model.md); its coding agents, development tooling and credentials belong there. Generic standalone examples below do not override sensitive-controller placement. Follow [worker operations](worker/operations.md) and [scoped Git onboarding](worker/git-workflow.md).

## Standalone access and tools

The installer can enable workload SSH independently of editor integrations. A
manual equivalent in `local.nix` is:

```nix
assbox.network.ssh = {
  agent = { enable = true; keys = [ "ssh-ed25519 REPLACE_WITH_PUBLIC_KEY" ]; };
  exposure = "lan";
  lanInterfaces = [ "enp0s5" ]; # Use the installed guest's actual interface.
  lanSourceCidrs = [ "192.168.64.1/32" ]; # Use the actual controller address.
};
assbox.components.codex.enable = true;
assbox.components.chromium.enable = true;
assbox.presentation = "wayland";
assbox.session.autostart = [ "chromium" ]; # Optional.
```

Alternatively keep the default `ssh.exposure = "tailscale"`, omit the LAN fields,
and set `assbox.network.tailscale.enable = true`; enroll from the console. The
same exposure applies to administrator SSH when enabled with its own keys.
Neither exposure enables password login, agent forwarding, X11 forwarding from
the generated client alias, or a public app-server port. Additional packages use
`assbox package add` or the installer's validated package list. All standalone
workloads share the agent account; these options do not introduce per-tool sandboxes.

## Machine-local files

The installer creates `/etc/nixos` with these ordinary Nix files:

| File | Ownership and purpose |
| --- | --- |
| `flake.nix`, `flake.lock` | Ordinary machine-local flake with an immutable authenticated release pin |
| `assbox-release.json` | Verified release metadata, updated with the local pin |
| `hardware-configuration.nix` | Generated hardware discovery; inspect before changing |
| `storage.nix` | Generated filesystem and boot-disk binding |
| `assbox-settings.nix` | Installer choices, overridable with normal module priorities |
| `assbox-packages.nix` | Canonical CLI-managed additional package list |
| `local.nix` | Human-owned NixOS customization; never rewritten by Assbox |

Do not place passwords, API keys or authentication tokens in any Nix file. The Nix
store is not a secret store. The administrator password hash is a root-only file in
`/var/lib/assbox-secrets`; Wi-Fi credentials use root-only NetworkManager keyfiles.
Application credentials belong to the private agent home.

X11 and Wayland include standard file-picker portals and GNOME Keyring for desktop
credentials, including Zed account login and provider API keys. On the first use,
GNOME asks you to create a keyring. For unattended access after reboot, leave both
password fields empty and confirm **Store passwords unencrypted**. This is a
one-time choice in the standard desktop prompt, not the administrator password.
The keyring lives in the agent's private home with user-only file permissions;
it is **not encrypted on disk** and is accessible to agent processes and root.
Do not treat it as isolation between applications or protection from disk theft.

Choosing a keyring password instead is supported by GNOME, but requires manual
unlock when an application needs it after reboot. Assbox's locked agent account
and automatic graphical login supply no password for automatic unlocking. Assbox
never replaces an existing keyring, removes its password or stores an unlock
password. Cancelling a prompt leaves credential-dependent operations incomplete;
retry the application's normal login/key-saving operation when ready. Headless
installations do not acquire these desktop services.

`/var/lib/assbox/release-state` is private replay-protection state, not a parallel
Nix configuration database. Assbox never decreases it during generation rollback.
The CLI recognizes the installer-shaped literal input line and package-list grammar;
custom flake inputs/formatting remain valid NixOS but may require manual management
rather than automatic source rewriting.

## Friendly package operations

On a configured machine:

```sh
assbox package search imagemagick
assbox package list
sudo assbox package add imagemagick
sudo assbox package remove imagemagick
```

Names are attributes from the machine's pinned nixpkgs, including dotted names such
as `python3Packages.requests`. Arbitrary Nix expressions, flake URLs and command
options are not package names. `list` lists only CLI-managed additions, not every
package in the closure. `remove` removes only that list entry; a package required by
the base system or application remains present.

Add/remove builds a candidate before atomically publishing the package file and
activating with `switch`. A build failure does not change the running generation or
publish the candidate. An activation failure is recorded for inspection, not
misrepresented as an atomic whole-system rollback. Adding a package normally does
not reboot; use the boot-staging workflow for changes that should not activate live.

## Ordinary NixOS escape hatch

```sh
sudo assbox config edit
sudo assbox check
sudo assbox rebuild
```

For example, `local.nix` may contain:

```nix
{ pkgs, ... }:
{
  environment.systemPackages = with pkgs; [ tmux htop ];
  assbox.devices.wifi.enable = true;
  assbox.updates.calendar = "*-*-* 18:00:00";
}
```

The normal NixOS equivalent remains valid:

```sh
sudo nixos-rebuild build --flake /etc/nixos#assbox
sudo nixos-rebuild switch --flake /etc/nixos#assbox
# Or stage rather than activate live:
sudo nixos-rebuild boot --flake /etc/nixos#assbox
```

Manual commands do not acquire Assbox's operation lock or create its recovery
journal. Do not run them concurrently with an Assbox operation. A manually staged
generation may not have an Assbox pending-reboot marker; reboot it explicitly.
Assbox is an affordance, not a prerequisite for using the resulting NixOS system.

The managed helper requires a root-owned configuration tree with ordinary files:
no symlink/hardlink escapes, non-root writable ancestors or very large trees/files.
These restrictions protect its snapshot/publication model. More elaborate local
NixOS arrangements can use ordinary NixOS tooling instead; the CLI must refuse
unsupported arrangements rather than rewrite them.

Do not run a formatter over `assbox-packages.nix` and expect package add/remove to
understand an altered representation. It intentionally recognizes only its own
canonical grammar. Move advanced expressions to `local.nix`, then restore the
managed file to its generated representation. This is not a restriction on the NixOS
module system itself.

## Components and devices

`sudo assbox configure` reuses the purpose-first selection flow and prints the
generated settings changes, then checks assertions and effective values against
local overrides. It does not build or activate. `sudo assbox configure --apply`
builds the validated candidate and stages it for reboot. The preview omits
unchanged context and redacts sensitive settings. Both commands preserve
`local.nix`, repositories, credentials and worker resources; an execution topology
change requires the separate worker configuration/export procedure.

Execution egress applies to the actual execution domain, including an existing
managed worker. Selecting offline removes its configured uplinks and DNS. Enabling
egress afterward requires explicit worker network configuration; reconfiguration
does not guess interfaces or silently replace an incompatible resolver.

Deselecting Tailscale removes its Serve control binary reference and reconciler
service/timer. Withdraw any Assbox-owned dashboard exposure while Tailscale is
still enabled before removing it. An unresolved ownership journal makes the
activation withdrawal fail explicitly; the helper never discards it merely
because its control backend is absent.

The native kiosk screen reads each selected app's current installed gate as
verified, pending, unavailable, ineffective or stale. It starts no login or
observer probe. A changed requested policy cannot reuse a receipt for another
policy. A proposed installation starts pending, and every launch still checks
the independent gate. Back returns to selection, where apps can be deselected;
worker and web alternatives require explicit selection and their own preflight.

```sh
sudo assbox component set opencode,opencode-server wayland
sudo assbox component set none headless
sudo assbox component set claude-code headless --accept-unfree
sudo assbox rebuild --boot
```

Component selection stages a new generation and retains old application data.
It does not silently change a locally overridden presentation. ChatGPT requires
X11 and explicit machine-wide unfree-package permission. This is permission for
all unfree nixpkgs packages, not just the selected application, and survives
switching to a different application. `--accept-unfree` records
`assbox.acceptUnfree = lib.mkDefault true` in the managed settings; without that
flag, selection never grants consent or revokes an existing grant. An existing
`assbox.acceptUnfree = true` in `local.nix` is also sufficient. Conflicting local
overrides are reported before the build rather than silently bypassed.
Finish the change with a controlled reboot; onboarding is described in
[applications](applications.md).

`assbox.boot.generations` is a normal configurable boot-menu limit (2–32). Editing
it in `local.nix` and using `sudo assbox rebuild --boot` is supported: the immutable
storage/boot binding remains unchanged. This option is distinct from
`assbox.updates.keepGenerations`, which controls retained NixOS generations and GC.

Wi-Fi, audio/microphone, camera, Bluetooth and suspend are explicit NixOS options.
The installer recommends Wi-Fi from the active route and scale from plausible EDID
information; uncertain values are shown for human selection. These are installation
suggestions, not an ongoing hardware-dependent configuration rewrite.

Radio power switches remain administrative even while the agent owns the local
desktop. `/dev/rfkill` is root-only; administrators use `sudo rfkill` when needed.
The configured Wi-Fi selection is reapplied when NetworkManager starts, and
disabled Wi-Fi radios are blocked on hotplug. Temporary administrator radio
changes last until that policy is reapplied; change the Nix option for persistence.
The legacy kernel radio-hotkey handler is disabled so an agent-controlled input
device cannot bypass this boundary. This uses a standard NixOS kernel configuration
override and requires building the configured kernel; radio hotkeys do not toggle
radios. As with other managed device changes, this policy takes effect on reboot;
replacing udev rules alone does not revoke descriptors opened by an earlier session.

USB keyboard/mouse and Ethernet remain usable. Removable storage is not automounted
or granted as a raw block device to the agent. An administrator may mount it
explicitly; read-only import is preferable. Cameras/audio follow their device
options. This is not a defense against a malicious USB device impersonating a
keyboard, nor an isolation guarantee for every vendor-specific USB interface.

Redistributable firmware is allowed by default for general PC compatibility.
Proprietary applications and other unfree packages require explicit consent. A
specific GPU, Wi-Fi chipset or laptop quirk may still require an ordinary local
NixOS option; discovery is not a universal driver compatibility guarantee.

## Console, SSH and local discovery

The installer enables `assbox.network.ssh.admin.enable` and Tailscale only when an
admin public key is explicitly supplied after the tailnet-only access explanation.
Selecting an SSH editor host also asks for its own agent public key and enables
Tailscale. Complete Tailscale login from console before using SSH. Without either
key, sshd remains off. Configure separate `ssh.agent.keys` and `ssh.admin.keys` in `local.nix`;
[explicit LAN access](applications.md#ssh-and-tailscale) is also available. Password SSH and root SSH remain
disallowed by the appliance defaults. `assbox.network.discoverable = true` enables
Avahi/mDNS hostname advertisement; it defaults false. Do not assume an `.local`
address exists when discovery is disabled. These choices do not disable ordinary
outbound networking or alter the one-time Wi-Fi recommendation.
