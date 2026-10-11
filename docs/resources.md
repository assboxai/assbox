# Resource behavior

Assbox leaves Nix build parallelism and core selection at the upstream defaults.
A larger machine can use all its available processors. Agents run at normal CPU
priority; elevating them with negative `nice` values would not prevent an OOM kill.

Nix's daemon and scheduled maintenance run in the root `assbox.slice`, with CPU and
I/O weights of 20. These relative weights favor foreground work during contention
while allowing background builds to use idle capacity. The daemon's build children
inherit that placement. There are no Assbox CPU quotas, memory ceilings or build
job caps. I/O weight effectiveness depends on the device and kernel scheduler.

Root clients can use Nix's local store directly under its
[automatic store selection](https://nix.dev/manual/nix/2.34/store/types/).
Scheduled root maintenance still inherits the maintenance service's background
slice. Foreground administrator builds retain their calling context.

Standard NixOS zram provides demand-allocated compressed swap using zstd. Its logical
capacity is half of RAM; it does not reserve half of RAM at boot, and it does not
alter disk partitions. Compression helps with cold, compressible pages but cannot
make an arbitrarily large workload fit in memory.

Installed-system checks and builds drain command output concurrently. Structured
stdout is limited to 32 MiB while reading, and failures retain only the final
64 KiB of stderr, marked when truncated. This keeps verbose diagnostics from
accumulating in the administrator process; it does not limit build memory or
parallelism. The live installer separately keeps private disk-backed build logs.

Local application services restart after failure, with delays increasing
from five to sixty seconds. The OpenClaw Gateway also restarts after a successful
exit because its configuration-reload restart path hands control to systemd this way.
Remote servers and editor launchers back off from twenty
to three hundred seconds over five restart steps, without a start-count lockout.
Remote adapters restart after transient failures and ordinary clean exits; declared
permanent refusals remain stopped. Closing a graphical editor normally leaves it closed. Explicit service stop,
disablement and graphical-session teardown do not trigger automatic restarts.
Managed graphical launchers use foreground application entry points. Zed's public
CLI and VS Code's public CLI may detach and hide the application exit status, so
the services use the wrapped application entry points instead. A main-process
exit also stops remaining helpers; a surviving helper cannot hide a GUI crash.
The X11 OpenCode attach launcher uses `st`, which reports a failed child as a
failure to systemd, with a small patch preventing its close-generated hangup from
being reported as a crash. Its ordinary window-manager close stays closed.
Wayland uses `foot`; the regular X11 shell terminal remains `xterm`.
Expired credentials still require interactive login; retries do not grant access.
Shutdown kills the whole service group after the sixty-second grace period.
CPU, I/O and memory accounting make resource pressure visible without adding a
separate Assbox tuning interface.

The X11 display manager also retries with five-to-sixty-second backoff and no
start-count lockout. Greeterless autologin restores the agent session after Openbox
or X-server failure and after logout. Explicitly stopping the display manager
still leaves it stopped. This restores the desktop and configured launchers, not
unsaved application state or interrupted tasks.

Use `systemd-cgtop`, `zramctl`, `free -h` and
`journalctl -k -g 'oom|Out of memory'` to inspect pressure. For application failures,
run `sudo assbox doctor` or inspect `systemctl --user status assbox-opencode` as
`agent`. Provider output is suppressed; use the [private diagnostic capture](applications.md)
for managed remote adapters. `systemctl show nix-daemon -p ControlGroup`
shows the build daemon's placement. Account for active builds and agents together
when diagnosing memory exhaustion.

## Execution capabilities and mutable state

`assbox.computerUse.mode` is `none`, `browser`, or `virtual-desktop`. Private desktop resources add Xvfb/Xauthority, window-manager/session tools and bounded service memory only when selected. The provider owns its computer-use implementation. A missing helper does not authorize a package-manager bootstrap. `assbox.computerUse.providerRuntime` can hold an independently pinned required helper. Manual display-wrapper invocations are explicit; GUI support remains subject to the dated evidence and actual release qualification.

`assbox.resources.agentMemoryMaxMiB` bounds each managed agent service and its children; it defaults to 4096 MiB and is not a reservation. `agentCPUWeight` controls contention. Background Nix builds retain their existing lower-weight slice and zram behavior. Budget application homes, provider helpers, projects, retained generations, build transients and state checkpoints independently. Actual CPU/architecture and peak-resource qualification is still required.

OS rollback does not roll back SQLite databases, memory, skills, schedules, repositories or credentials. As owner, close direct CLI sessions, then use:

```sh
sudo assbox state backup
sudo assbox state list
sudo assbox state restore SNAPSHOT_NAME
sudo assbox state restore SNAPSHOT_NAME --apply
```

Backup stops and later restores only the previously active managed services. Checkpoints are root-private 0700/0600 archives and may contain credentials; protect or encrypt the storage. They remain bound to this machine and explicit selected application paths. Repositories are not included by default. Configure `assbox.state.directory` on owner-controlled storage, `additionalPaths` for intentional extra data, archive size/free-space reserve and retention. Snapshot links/devices need manual export; automatic restore refuses them. Do not use this feature to migrate accounts, copy a HOME across machines or replace canonical worker identities.

Selected Happier and Hermes services add their configured state homes to checkpoints, including a dashboard-only Hermes service. The default CLI homes remain included when those CLIs are selected. Service homes must be normalized directories inside `/home/agent`; overlapping checkpoint paths require an explicit selection change. Other custom provider paths need an `additionalPaths` entry.

Selected web-kiosk profiles and the autostart OpenClaw dashboard profile are included. Their managed browser services are stopped for the checkpoint. Graphical editor services are also quiesced, but editor/project state needs an explicit `additionalPaths` selection. Web kiosks and declared graphical launchers receive the same service memory and CPU accounting limits.

A restore preview shows the source generation and integrity metadata. `--apply` stops the execution user and requires no remaining execution processes, so keep an independent administrator connection. It preserves previous state and an explicit recovery journal and leaves execution stopped for review. It does not infer provider schema compatibility or start migrated credentials. `backupBeforeUpdate` is an explicit opt-in for scheduled update checkpoints. Worker application state is checkpointed inside its own guest; the existing host worker-disk admission and identity rules remain authoritative.

Guest checkpoints and their local checkpoint identity live in root-private `/home/.assbox-state-backups`, so the disposable worker root does not erase them. Guest root administration is disabled by default; invoke the state helper only through explicitly authorized guest administration or declare a reviewed guest maintenance job. Otherwise export scoped application data through the normal SSH workflow. Copying the entire backup directory, including its identity record, is not a supported cross-instance import.
