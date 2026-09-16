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

Application services restart after failure, with delays increasing from five to
sixty seconds. A normal exit stays stopped. Shutdown kills the whole service group
after the existing sixty-second grace period. CPU, I/O and memory accounting make
resource pressure visible without adding a separate Assbox tuning interface.

Use `systemd-cgtop`, `zramctl`, `free -h` and
`journalctl -k -g 'oom|Out of memory'` to inspect pressure. For application failures,
run `systemctl --user status assbox-opencode` (or the selected application's unit)
as `agent`, and inspect its user journal. `systemctl show nix-daemon -p ControlGroup`
shows the build daemon's placement. Account for active builds and agents together
when diagnosing memory exhaustion.
