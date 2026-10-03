# Standalone Assbox in Parallels

This is an installation and acceptance procedure, not a completed Parallels
certification. Use matching-architecture NixOS media: AArch64 on an Apple Silicon
host, x86-64 for an Intel VM. The guest uses the generic UEFI profile; the host's
bare-metal boot chain and hardware drivers are outside the guest's scope.

## Standalone Assbox with macOS ChatGPT

Choose **Coder → Codex external Desktop SSH**. Assbox runs the selected coding tools
inside the Parallels VM; macOS ChatGPT remains the external controller. No
Assbox-managed inner worker or nested KVM is needed. The same standalone
installation also works with ordinary SSH terminals and SSH-aware editors.

1. Create a matching-architecture VM and prepare target/backup storage as below.
   Use an expanding virtual disk with enough maximum capacity for tools, projects,
   retained systems and builds. The host file grows with guest writes; virtual
   capacity is not pre-reserved macOS free space. Monitor both host and guest.
2. In the Assbox wizard choose the generic platform, Coder and Codex external
   Desktop SSH. The minimal selection is `codex`; other tools are explicit. For a manual graphical session, also select `chromium`
   and X11/Openbox or Wayland/labwc, optionally autostarting `chromium`. Use the
   additional-package prompt for tools such as `htop`. Headless is equally valid.
3. Enable workload SSH, supplying the macOS workload public key for `agent`.
   Supply an administrator key separately only if wanted. Select Tailscale and
   enroll at the installed console, or LAN with the actual guest interface(s).
   For direct Parallels access, confirm the host-to-guest route and optionally
   restrict sources to the macOS virtual-network address/CIDR. Do not assume an
   interface name, fixed DHCP address or isolation from other reachable hosts.
4. After installation, detach the ISO and boot Assbox. At the trusted VM console,
   inspect `ip -brief address` and read `/etc/assbox/connection-guide.txt`. Obtain
   the SSH host fingerprint with `sudo ssh-keygen -lf
   /etc/ssh/ssh_host_ed25519_key.pub`. Configure the suggested SSH alias on macOS,
   compare the first-connection fingerprint, and verify login as `agent`.
5. Authenticate Codex **inside the guest** as `agent`. Confirm `command -v codex`
   through the same SSH login. In macOS ChatGPT, add this SSH host and select a
   guest project directory. The application manages its app server over SSH;
   do not open a separate public app-server port. Provider authentication and
   final app connection remain explicit user steps.

The browser and terminal in the guest are for manual use. This tranche does not
wire ChatGPT browser/desktop automation into that session or promise that every
app capability works remotely. Qualify command/file execution and reconnects with
synthetic projects before adding real credentials. Assbox does not configure or
enforce the macOS application's local tools or account policy.

The Parallels VM boundary is the relevant local boundary. Disable host directory,
clipboard, device and credential sharing that the workload does not need; Assbox
cannot enforce host hypervisor preferences. Parallels shared networking provides
connectivity, not a promise that macOS or LAN services are unreachable. Assbox's SSH policy restricts ingress. The standalone execution UID also defaults to internet-only egress, including protected LAN, overlay, local-broker and metadata restrictions; qualify NAT and IPv6 on the actual VM. All selected guest agents share the `agent` account and its secrets.
Guest OS rollback does not undo projects, host changes, Git pushes or provider
actions. Manage the host, guest, virtual disk capacity and backups separately.

Upstream interface references: [OpenAI SSH connections](https://learn.chatgpt.com/docs/remote-connections#connect-to-an-ssh-host),
[Parallels expanding disks](https://kb.parallels.com/en/4706), and
[Parallels networking modes](https://kb.parallels.com/en/4948). These explain the
interfaces, not acceptance results for this configuration.

## Guest preparation

For Apple Silicon, use the current minimal **64-bit ARM/AArch64** image from the
[official NixOS downloads](https://nixos.org/download/), not the x86-64 image and not
a board-specific SD-card image. Parallels documents installing ARM Linux from an
ARM ISO in its [Linux installation guidance](https://kb.parallels.com/en/128445).
That general capability is not vendor certification of this Assbox configuration.

Create a disposable matching-architecture Linux VM with UEFI firmware and an attached read-only ISO.
Add distinct virtual disks for the installation target and external boot backup.
Use normal virtual storage/network devices recognized by the stock live image.
Do not pass through a host physical disk. Disable unnecessary host-folder sharing
and never expose host credentials for an installer test. A host snapshot is useful
for test reset, not a substitute for independent backups.

Provide enough target disk space for packages, build intermediates and retained
generations; see [build capacity](installation.md#build-capacity). The full build
uses that disk. Authentication/evaluation and the running compiler still need RAM;
no tested minimum is claimed.
The backup needs space for complete ESP/boot metadata, not merely the partition
list. Distinct guest disks may still share one physical host disk.

Boot the ISO and inspect, without writing:

```sh
uname -m                       # aarch64 on Apple Silicon; x86_64 for an Intel VM
test -d /sys/firmware/efi        # Must succeed
findmnt /iso
lsblk -o NAME,TYPE,SIZE,RO,FSTYPE,MOUNTPOINTS
```

An attached ISO normally appears as a read-only `rom` device, but use observed
paths, not assumed `/dev/sr0`, `/dev/sda` or `/dev/vda` names. The installer also
accepts a clearly identified local installer disk. Ambiguous loop/network sources
are refused. If storage or networking is not recognized by the stock live image,
stop and investigate rather than claiming the generic profile supports it.

Prepare the disposable target as GPT with exactly one empty FAT ESP and one empty
ext4 root; prepare a backup partition on the other virtual disk. Formatting is a
separate administrator operation, not an Assbox command. Unmount every partition
of both disks. Record the layout before invoking the installer.

## Bootstrap and install

First resolve/review the project's real lock and pass native build/verification
checks in an AArch64 Linux environment. The package and dev shell select
`aarch64-linux` automatically. The current release gate also requires the full
end-to-end tests described in [verification](verification.md).

Use the reviewed native executable and installation procedure in
[installation](installation.md#native-binary-and-source-identity). Run plan-only
first. For a minimal baseline choose `generic`, Custom with no components or managed worker, `headless`, and the intended local timezone/SSH
public key. For the external-controller arrangement use the choices above. With explicit authorization, run `--apply` against the disposable VM.
Record the immutable source identity, built system path, commands and real results.
No host hardware configuration is committed to the public repository.

Disconnect the installation ISO before the acceptance boot and select the installed
virtual target disk. Do not mistake a successful reboot into the live ISO for a
successful installation.

## Acceptance sequence

Start with `none`/headless: verify target boot, console/admin login, key-based SSH
when enabled (and no TCP/22 listener for console-only),
networking, architecture, hostname and an ordinary `/etc/nixos` flake. Check
`assbox status`, then package add/remove, rebuild, staged update, reboot and retained
generation selection. Exercise failed builds and the documented recovery paths on
snapshots. Never equate a plan-only pass with a successful installation.

Next test OpenCode/headless and OpenClaw/headless, including real provider login and
authenticated client tasks. Test `none`/Wayland and `none`/X11 separately before
headed applications. Validate virtual GPU behavior, terminal input, display scale,
automatic session startup, shutdown and restart. ChatGPT/X11 comes last, with actual
Linux Remote authentication and an end-to-end task. A package evaluating on ARM is
not evidence its graphical runtime works in this VM.

Protected local Code requires a managed KVM worker. Check for usable `/dev/kvm`
inside the Parallels guest before choosing that mode; this requires nested
virtualization exposed to the guest. Native None can be staged without a worker
but requires its own exact no-local-execution qualification. The external Mac
Desktop SSH route uses a standalone guest and requires no inner worker. Assbox does not emulate the production worker or
move its execution to the controller. Follow [worker acceptance](worker/acceptance.md)
and [client routing](worker/client-routing.md) on a supported target, budgeting RAM
and storage for both systems.

Parallels Tools, shared-folder integration and automatic display resizing are not
configured by Assbox. Record missing guest-driver/integration features as test
results, not as evidence about bare-metal Apple Silicon support. Keep host and guest
updates/backups independently managed.

CI's ARM storage VM can use software emulation when nested acceleration is absent.
It tests generic QEMU behavior, not Parallels graphics, firmware or product-specific
integration. Both test environments have distinct acceptance value.

## External-controller acceptance record

The [canary and reconnect fixture](external-coder-fixture.md) provides reproducible
owner-run tasks and bounded private records for the actual Mac/guest integration.
Its synthetic unit checks are separate from the pending native workflow below.

Record the source commit/release, guest architecture, Parallels/macOS/app versions,
presentation and network choice. All results below are **pending** for this tranche.
Use disposable credentials and a synthetic repository, then revoke test tokens.

| Gate | Required evidence |
| --- | --- |
| Standalone installation | Correct target boot without `/dev/kvm`, no nested worker process or image, ordinary `/etc/nixos` |
| SSH identity and exposure | Console fingerprint matches; workload key reaches `agent`; unrelated keys/passwords fail; permitted interface/CIDR succeeds and disallowed source fails; admin key reaches only its intended account |
| External command/file scope | macOS ChatGPT edits a random guest-only canary and runs `hostname`, `pwd`, a build and a test in that guest project; a host-only canary is absent |
| Failure and reconnect | Lost guest network or powered-off VM reports remote unavailability; no silent move to a macOS project; reconnect/reboot preserves the selected guest project |
| Independent GUI | Chromium, terminal, rendering and input work on each advertised X11/Wayland choice; optional autostart restarts with the session; headless has no browser |
| Shared account semantics | Optional agents see the same intended project; credentials remain inside the guest and are treated as shared within that account |
| Updates and data | Package change, staged update, reboot and rollback retain projects; provider reauthentication handled explicitly |
| Capacity and recovery | Expanding host disk growth observed; guest and macOS free-space pressure handled with a disposable VM and a tested backup/restore path |

Passing the managed-worker QEMU tests does not pass this Parallels/macOS routing
gate. Conversely, passing standalone Parallels does not qualify nested KVM or the
installed Linux ChatGPT controller adapter. Guest GUI automation remains deferred.
