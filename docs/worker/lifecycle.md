# Worker disablement, retained state and re-enablement

## Product contract

The controller owns the worker lifecycle. Disabling the worker removes its
execution services, timers, private network and active runtime configuration;
it does not move agents onto the controller, erase the persistent home disk,
rotate transport identities or revoke provider credentials.

`assbox-vmm` and `assbox-health-probe` are persistent infrastructure identities
whenever Assbox is enabled, even on a system that has never enabled a worker.
They have locked passwords, `/var/empty` homes that are not created as user
homes, and non-login shells. Neither is a human login or an agent account.
`assbox-vmm` belongs to `kvm` only while the worker is enabled. Keeping the
identities does not install or activate QEMU, create worker state or enroll a
provider account.

This separation is important because candidate storage admission runs **before
activation**. A re-enabled candidate must be able to resolve and verify the
owner of retained files while the disabled generation is still running. The
helper does not infer identity from the disk's numeric owner, adopt an orphaned
disk, or edit the user database itself. NixOS manages the declared identities;
see S12 in [sources](sources.md).

| State | Worker resources | Existing state and identities |
| --- | --- | --- |
| Assbox enabled, worker never enabled | No worker image/runtime/services/network | Inert infrastructure accounts only; no worker disk or keys created |
| Worker enabled | Controller-owned image, services and private TAP | Persistent home and dedicated transport keys are provisioned deliberately |
| Worker stopped | Execution stopped; installed configuration remains | Disk, keys and infrastructure accounts retained |
| Worker disabled and rebooted | Worker services/timers/network/runtime absent | Disk and keys retained; accounts remain, without VMM `kvm` membership |
| Worker re-enabled | Candidate admission before publication; provisioning after activation | Same verified home disk and key material reused, not reformatted or rotated |

Retained Nix generations can continue to retain their own worker artifacts.
Disabling is not an instruction to garbage-collect recovery generations or to
remove the account's cloud credentials.

## Supported operator sequence

A ChatGPT controller cannot retain Desktop without its required worker. To
retire that controller profile, remove its sensitive controller selections
through the normal Assbox configuration transaction before requesting:

```sh
sudo assbox worker disable
sudo assbox worker disable --apply
```

The first invocation is a plan. Apply through the ordinary transaction/reboot
workflow and verify the disabled state. Do not interpret `worker stop` as a
persistent disable; subsequent boots or an explicit start can run the installed
worker again.

To re-enable, use `sudo assbox worker setup` or an explicit `worker configure`
selection as documented in [operations](operations.md). Supply the intended
components, consent, network settings and **the same state size** as the
retained disk. Disablement is not a saved configuration preset: inspect the
proposed settings rather than assuming every old choice has been restored.
Restore ChatGPT controller selections only when its worker dependency is again
satisfied. None of these operations copies development credentials to the
controller or provides an agent-execution fallback there.

## Ownership and interrupted provisioning

The controller's root provisioning helper creates a missing data directory with
an unprivileged VMM owner and mode `0700`. Existing directories are inspected,
not repaired. Ordinary tmpfiles processing is not allowed to chown/chmod this
data directory before admission can inspect it. Preparation likewise checks
permissions without normalizing them. See S13 in [sources](sources.md).

A wrong owner, unexpected permission mode, symlink, ambiguous disk, changed disk
size or interrupted `home.raw.new` allocation is a refusal condition. These
conditions must not become a format, resize, silent ownership transfer or new
empty home directory. The acceptance test intentionally exercises these cases.

Canonical keys must already exist whenever `home.raw` exists. Missing or invalid
client, worker-host or health keys refuse admission and provisioning before any
writes. Only their derived probe copy, public trust files and seed image can be
recreated from validated canonical keys. A clean or interrupted first setup
without a home disk may generate absent keys after validating all keys already
present. A leftover root overlay without its home disk is state loss, not first
provisioning. Neither case authorizes silent identity rotation or a new empty home.

The persistent disk and canonical private keys require exactly mode `0600`;
owner-only but unreadable, unwritable, executable or special-bit modes refuse.
Existing infrastructure directories are also inspected without normalization.

If an account is missing despite preserved state, stop and inspect the declared
configuration and NixOS account history. Restore the legitimate infrastructure
identity through trusted NixOS configuration before retrying admission. For a
system whose active configuration does not yet declare the inert identities,
first activate an Assbox configuration that declares them while leaving the
worker disabled. Do not blindly run `chown -R`, delete the disk, assign a guessed
numeric UID or synthesize an identity from the disk owner. If account mappings
were lost, treat that as an explicit recovery operation requiring verified
backup/ownership evidence. The same caution applies after fully removing Assbox;
removal of Assbox itself is not covered by worker-only disablement.

An interruption between first directory creation and ownership assignment can
leave a root-owned empty directory. It is deliberately refused on the next
attempt; confirm its provenance and contents before an administrator repairs or
quarantines it. State-directory creation does not overwrite existing entries.

Disabled worker state is still sensitive. It can contain PATs, provider tokens
and home-based malware. Protect opaque backups and use the
[incident-response procedure](operations.md#incident-response) for suspected
compromise. Disable/re-enable is neither a reset nor credential revocation.

## Required verification

`worker-policy` evaluates enabled, disabled and non-Assbox configurations. It
checks that identities survive worker disablement, lose VMM device-group
membership, and do not themselves add worker services, image references or
runtime configuration.

`worker-lifecycle-vm` boots a controller test VM, activates an enabled
specialisation, provisions synthetic transport keys and sparse test state,
activates the disabled generation, and reboots it. It checks preserved numeric
UID/GID mappings, disk metadata and key material, absence of worker resources,
and successful admission of the enabled candidate **before** reactivation. It
also verifies that unexpected directory permissions are refused rather than
normalized. The fixture deliberately does not start a nested worker and its
disk is not a guest filesystem. It proves neither KVM boot nor real guest
filesystem persistence.

Complete the separate real-worker lifecycle procedure in
[acceptance](acceptance.md#disable--re-enable-with-a-real-worker) on disposable
state. This requires actual disable/reboot/re-enable/reboot, a surviving marker
inside worker `/home`, stable SSH identity and no controller execution fallback.
Unexecuted native gates are requirements, not passing results.

## Sparse capacity and disk I/O failure

New `home.raw` files have a chosen fixed virtual capacity and allocate backing
blocks on demand. Automatic sizing occurs once, after system/image construction,
and leaves the [documented reserves](operations.md#capacity-and-network-policy).
Admission budgets unallocated capacity as well as the writable root. It does not
prevent unrelated controller writes, later builds or an outer hypervisor from
consuming that space. Existing files are reused only at their original validated
size. There is no automatic grow, shrink, reformat, or repair path.

QEMU is configured to **pause on writable-disk read/write errors**, including host
space exhaustion. The process remaining alive does not mean the worker is ready:
SSH health fails while it is paused, and boot acceptance stays pending. Do not
repeatedly restart it or delete `home.raw`, its identity keys or the root overlay
as a response to a disk-full message.

On a disposable qualification system, record QMP status and block I/O status,
restore real host free space without deleting worker data, then explicitly resume
the VM through its administrator-only QMP monitor. Allow outstanding writes to
finish and verify the nonce/project and guest filesystem before a clean shutdown.
If it cannot be resumed safely, preserve the disk as opaque bytes and follow the
existing controlled recovery procedure in [operations](operations.md). A forced
stop may lose in-flight writes; an ordinary restart discards the system overlay
but retains home state, including any damage. Never mount or repair an untrusted
guest filesystem on the controller. No automated incident or capacity recovery is
claimed. The native [disk-pressure gate](acceptance.md#capacity-and-disk-pressure)
is required before relying on this behavior.
