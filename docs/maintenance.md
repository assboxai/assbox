# Maintenance and recovery

## Scheduling and activation

Daily maintenance starts at **18:00 in the configured local timezone**, with up to
15 minutes of random delay. A persistent systemd timer catches up missed windows.
The time is a start time, not a promise that downloading/building/reboot will finish
at 18:00. A missed window may run after startup outside that clock hour.

The machine consumes an authenticated immutable release, not a moving Git branch.
That release supplies an exact dependency graph; machine-local configuration stays
local. GitHub latest is discovery only. Failed provenance, identity, expiry, replay,
source hash or lock checks stop before evaluating a candidate. Network/trust failure
never falls back to direct branch evaluation. See
[release authentication](release-authentication.md) for trust and bootstrap details.

The updater durably records the authenticated release high-water mark before Nix
metadata/evaluation, then builds a private candidate. After checking unchanged live
configuration, profile identity and the target boot receipt, it journals publication
of `flake.nix`, `flake.lock` and `assbox-release.json`, selects the profile and performs
boot activation. This is equivalent in purpose to `nixos-rebuild boot`, not a live
userspace switch. A failed build does not publish its configuration or reboot;
the acceptance watermark deliberately remains advanced and permits an exact retry.

A changed staged generation gets a wall notification and ten minutes of grace,
then normal systemd reboot with inhibitors bypassed. Graphical sessions and agent
jobs cannot veto patching. Services receive bounded graceful termination; application
checkpointing, remote task cancellation and resumability are not guaranteed.

## Failure retries and power

A scheduled staging failure receives up to **three hourly retries** by default.
The count is persisted before each retry; a crash does not reset it. The next
scheduled maintenance run starts a new budget. A journal requiring inspection is
not silently overwritten or repaired by retries. Exhausted staging attempts remain
visible in service logs until the next scheduled run or administrator action.

Reboot retries are independent of this budget. A pending staged generation is
handled before reading the staging budget, contacting release services or building
another candidate. A failed new release lookup therefore cannot delay an already
staged update. An unresolved transaction blocks both new staging and reboot until
recovery; a pending marker is not proof that activation completed. Inspection
errors are propagated, and malformed state is not treated as absent.

Low battery or unreadable/uncertain battery power defers reboot; positively
confirmed AC permits it. Battery-powered
machines need a known charge at or above the configured minimum (20% by default).
A machine positively observed to have no batteries can reboot without an AC sensor.
Supplies explicitly marked by Linux as peripheral devices, such as mouse batteries,
are excluded. Host supplies without a scope attribute remain part of the power check.
Power and selected generation are checked again after the grace period. A system
which remains power-starved may remain pending: there is no forced unsafe shutdown
or external alerting backend.

## Configuration

Put overrides in `local.nix`:

```nix
{ ... }:
{
  assbox.updates = {
    enable = true;
    calendar = "*-*-* 18:00:00";
    jitter = "15m";
    persistent = true;
    rebootGraceSeconds = 600;
    minimumBatteryPercent = 20;
    maximumStageRetries = 3;
    retryCalendar = "hourly";
    keepGenerations = 8;
  };
}
```

Calendar strings use systemd syntax and the configured local timezone unless one
is explicit. Check changes with `systemd-analyze calendar`. Cadence, window start,
jitter, catch-up, grace, battery threshold, retry cadence/budget and retention are
ordinary options. Advanced systemd overrides remain possible in `local.nix`.
Disabling automatic updates also suppresses automatic boot-time cleanup; it makes
the administrator responsible for both patching and retention.

## Manual commands

```sh
assbox status
sudo assbox check
sudo assbox update              # Build and stage; no reboot in this invocation
sudo assbox update --reboot     # Stage, then use the notification/power policy
sudo assbox rebuild            # Activate local configuration live
sudo assbox rebuild --boot     # Stage local configuration for reboot
sudo assbox cleanup            # Conservative retention and store GC
assbox logs
assbox doctor
```

The automatic retry service acts on pending reboot markers, including manual
staging, while automatic updates are enabled. Plain `update` therefore does not
suppress all future automatic reboots. Manual NixOS tools do not participate in the
Assbox lock/journal; do not run them concurrently with an Assbox operation.

The post-boot service checks the booted, activated and selected system and network target,
then may clean old generations. It is not an authenticated application health check
or proof of macOS bootability. There is no automatic boot-count fallback.
An elapsed one-shot boot timer owns the automatic check: live rebuilds do not
retry it, even after failure. After inspecting and resolving a failed check, run
`sudo assbox internal boot-check` explicitly or reboot to check again.
`assbox status` distinguishes the booted generation from activated userspace.
Pending reboot records include the originating kernel boot ID: a live switch,
including a switch back to the booted generation, cannot complete that reboot.
Live Assbox changes retarget an outstanding reboot to the new selected generation.
Older generation-only records remain readable but require a matching booted
generation; subsequent writes use the boot-ID format. Standard NixOS tools do not
retarget Assbox records, so a conflicting selected profile still requires inspection.
Development binaries predating this format cannot consume the new records; finish
the reboot with the current binary before returning to such a development snapshot.

## Journal and rollback

An operation builds its first complete journal in a private sibling directory,
syncs it and publishes the active name atomically. Cleanup retires that name before
deleting its contents. Orphaned preparation/retirement directories may be discarded
under the operation lock; a genuinely corrupt active journal is not guessed away.

`/var/lib/assbox/transaction` records source snapshots, generations and ordered
phases. A pre-activation interruption can discard the candidate or restore the
published files. All changed files must first match their old or candidate bytes;
a third-party edit prevents all restoration. Partial restoration can be retried.
Release replay state is outside this journal and never rolled back. Once activation may have started, inspection is required:

```sh
sudo assbox recover
# Only after inspecting the retained state:
sudo assbox recover --rollback
```

Rollback stages the previous generation, not a reversal of mutable application
data, external actions or partially changed userspace. Reboot completes a return to
the selected generation. `sudo assbox rollback` similarly stages a retained earlier
generation without reverting local source. A later update may reconstruct the newer
configuration unless its desired revision/settings are changed.

Recovery after uncertain activation always records a reboot into the restored
generation. Matching generation links alone cannot prove partially changed
services have been restored, even if the old kernel is still running.
An invalid generation path, an unrelated selected profile or an unrelated pending
marker prevents activation recovery. Unreadable or malformed pending state also
blocks recovery when no active transaction exists.

Every Assbox generation carries a schema-2 boot receipt containing separate
immutable bindings and mutable loader policy. The CLI validates the destination
receipt, including an older rollback target, against the running one before profile
changes or activation. Architecture, strategy, platform, root/ESP/disk identity,
filesystem types and immutable loader details must match. The active loader's
generation limit may change within 2–32 through an ordinary Assbox rebuild or
rollback. Missing, foreign, malformed or older-schema receipts are refused. Other
boot/storage migrations require separately reviewed ordinary NixOS administration;
there is no automatic receipt-schema migration. A receipt is not a signature and
does not make arbitrary root-owned Nix code safe.

## Retention and free space

Default cleanup retains the newest eight system generations plus the running
one. It refuses to prune while a reboot/journal is pending or booted, activated
and selected profiles disagree. Old generations get temporary GC roots before deletion, boot
entries are refreshed under the same boot guard, and only after journal retirement
are those roots released and `nix-store --gc` run. Interruption after pruning starts
requires inspection; recovery does not reconstruct deleted generation numbers.

`assbox.boot.generations` separately controls how many generations appear in boot
menus. Other profiles and GC roots continue to retain their closures; cleanup does
not erase application data or external recovery archives. No free-space guarantee
is possible when the retained system set itself fills the disk. Monitor free space,
size storage appropriately, and never discard the only known-good system merely to
force an upgrade through.

## Release trust

A release attests to core source, a generated lock, policy and representative tests,
not every user's hardware-specific store path. The local CLI authenticates it and
builds with local hardware. Authentic provenance is not a safety proof, and the
GitHub repository/workflow/Sigstore trust domain must actually be secured. Read
[release authentication](release-authentication.md) and [governance](governance.md).
Expiry and outages require attention; there is no built-in external alerting service.
