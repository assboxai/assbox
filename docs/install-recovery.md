# Inspecting an interrupted installation

Keep the live medium and external boot backup. Initial installation has no
automatic resume or disk-restore command; `assbox recover` is for subsequent
installed-machine management operations.

## While the installer is still running

A build error prints private log paths under the mounted target's
`var/log/assbox-install` and offers an explicit retry on an interactive terminal.
This applies to both the provisional automatic-sizing build and the final system build.
Check the log and available space, or restore networking, without editing the
captured configuration or changing mounts/devices. Answer `y` only to repeat that
exact build. A changed/expired release, changed configuration or changed storage
selection refuses the retry. To stop, answer no or cancel the installer.

Cancellation waits for the transient `assbox-install-*.service` to stop its entire
cgroup. If systemd is unavailable, the installer reports that it is retaining
mount ownership. Restore communication or inspect the named service before
unmounting anything. Killing the installer with SIGKILL does not establish that
its service stopped. Do not remove `/run/assbox-install` while it contains mounts.

## After a crash or power loss

Boot rescue/live media and identify the disks again using model, serial, capacity,
by-id and filesystem UUIDs. Do not rely on remembered `/dev/sdX` names. Inspect
existing mounts and any surviving transient service before opening the target.
These commands only observe state:

```sh
lsblk -o NAME,TYPE,SIZE,MODEL,SERIAL,UUID,PARTUUID,MOUNTPOINTS
findmnt
systemctl list-units --all 'assbox-install-*.service'
```

On a fresh rescue boot, the following example opens a selected **unmounted ext4
root** without journal replay. Set `ROOT` to the inspected root partition first:

```sh
: "${ROOT:?Set ROOT to the verified unmounted Assbox ext4 root partition}"
sudo install -d -m 0700 /mnt/assbox-inspect
sudo mount -o ro,noload,nosuid,nodev,noexec "$ROOT" /mnt/assbox-inspect
sudo cat /mnt/assbox-inspect/.assbox-install.json
sudo ls -l /mnt/assbox-inspect/var/log/assbox-install
# Inspect/copy relevant private logs before unmounting.
sudo umount /mnt/assbox-inspect
```

A dirty filesystem may hide the latest writes when opened without replay. Missing
or unreadable records mean uncertainty, not permission to retry. Do not repair a
filesystem containing valuable data merely to make the installer accept it.

The record binds an operation ID, target and backup identities, backup directory,
release-manifest digest and configuration digest. A separate write-intent JSON
beside the external backup records the same selection before target writes. It
does not track subsequent progress. `SHA256SUMS` inside the archive authenticates
read-back consistency, not the identity of whoever supplied the backup. Retain the
original trusted backup media and protect any exported private logs/configuration.

| Target phase | Recovery decision |
| --- | --- |
| No target writes established | Recheck preflight and backup; a new invocation may use an actually empty, prepared root. |
| `target-writes` / `building` | Inspect the incomplete Linux root. Assbox has not started boot activation. A new invocation refuses its contents. |
| `activating` | Inspect profile, boot files, ESP and firmware from rescue media; a complete boot operation is not established. |
| `complete` | Test boot and login; a completed record is not proof of hardware or application acceptance. |

An expert may complete or repair an installation using ordinary NixOS rescue
tools after verifying the intended source, system path and boot strategy. That is
a separate administration operation outside Assbox's guarded installation flow.
Alternatively, explicitly prepare the intended Linux root again after preserving
anything needed. Assbox never does that preparation or authorizes it merely by
finding a record. Do not delete only the marker and rerun.

On Intel Macs, preserve rEFInd, unrelated ESP files and every retained macOS
partition. Do not blindly restore a whole disk header or ESP image: it may replace
changes made after the backup. Compare the saved partition/firmware metadata and
ESP archive first, repair only the inspected boot state, and verify both operating
systems boot. The archive is a boot-state backup, not a backup of personal data.
