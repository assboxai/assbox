# Resource behavior

Assbox leaves Nix build parallelism and core selection at the upstream defaults.
A larger machine can use all its available processors. Agents run at normal CPU
priority; elevating them with negative `nice` values would not prevent an OOM kill.

Nix's daemon and scheduled maintenance run in the root `assbox.slice`, with CPU and
I/O weights of 20. These relative weights favor foreground work during contention
while allowing background builds to use idle capacity. The daemon's build children
inherit that placement. There are no Assbox CPU quotas, memory ceilings or build
job caps. I/O weight effectiveness depends on the device and kernel scheduler.

Standard NixOS zram provides demand-allocated compressed swap using zstd. Its logical
capacity is half of RAM; it does not reserve half of RAM at boot, and it does not
alter disk partitions. Compression helps with cold, compressible pages but cannot
make an arbitrarily large workload fit in memory.

Installed-system checks and builds drain command output concurrently. Structured
stdout is limited to 32 MiB while reading, and failures retain only the final
64 KiB of stderr, marked when truncated. This keeps verbose diagnostics from
accumulating in the administrator process; it does not limit build memory or
parallelism. The live installer separately keeps private disk-backed build logs.

Existing local application services restart after failure, with delays increasing
from five to sixty seconds. Remote servers and editor launchers back off from twenty
to three hundred seconds over five restart steps, without a start-count lockout.
Remote servers restart after both successful and unsuccessful unexpected exits;
closing a graphical editor normally leaves it closed. Explicit service stop,
disablement and graphical-session teardown do not trigger automatic restarts.
Managed graphical launchers use foreground application entry points. Zed's public
CLI and VS Code's public CLI may detach and hide the application exit status, so
the services use the wrapped application entry points instead. A main-process
exit also stops remaining helpers; a surviving helper cannot hide a GUI crash.
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
