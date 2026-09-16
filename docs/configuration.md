# Local configuration and packages

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

## Applications and devices

```sh
sudo assbox application set opencode wayland
sudo assbox application set none headless
sudo assbox application set chatgpt x11 --accept-unfree
sudo assbox rebuild --boot
```

Application selection stages a new generation and retains old application data.
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

The installer enables `assbox.network.ssh.enable` only when an admin SSH key is
provided. Without one, console-only means sshd and its firewall opening are off.
An administrator can later enable key-only SSH in `local.nix` and add normal
`users.users.admin.openssh.authorizedKeys.keys`. Password SSH and root SSH remain
disallowed by the appliance defaults. `assbox.network.discoverable = true` enables
Avahi/mDNS hostname advertisement; it defaults false. Do not assume an `.local`
address exists when discovery is disabled. These choices do not disable ordinary
outbound networking or alter the one-time Wi-Fi recommendation.
