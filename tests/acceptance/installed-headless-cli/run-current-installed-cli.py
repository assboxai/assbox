from shlex import quote
import subprocess

efi = expected["system"] == "aarch64-linux"
image = installer.shared_dir / "curated-target.qcow2"
if recovery is None:
    subprocess.run([qemu_img, "create", "-f", "qcow2", image, "24G"], check=True)
else:
    subprocess.run([qemu_img, "convert", "-f", "qcow2", "-O", "qcow2", recovery, image], check=True)
installer.start()
installer.wait_for_unit("multi-user.target", timeout=300)
installer.succeed("findmnt -n -o FSTYPE /nix/.ro-store | grep -Fx squashfs")
installer.wait_until_succeeds("test -b " + disk)
assert installer.succeed("blockdev --getsize64 " + disk).strip() == str(24 * 1024**3)
installer.succeed(f'test "$(readlink -f {disk})" != "$(findmnt -n -o SOURCE /)"')
root = disk + "-part2"
esp = disk + "-part1"
if recovery is None:
    first_partition = "--new=1:2048:+512M --typecode=1:ef00" if efi else "--new=1:2048:+1M --typecode=1:ef02"
    installer.succeed(f"sgdisk {first_partition} --new=2:0:0 --typecode=2:8300 {disk}")
    installer.succeed("udevadm settle")
    installer.wait_until_succeeds("test -b " + root)
    installer.succeed(f"mkfs.ext4 -F -L ASSBOX_CI_ROOT {root}")
    installer.succeed(f"udevadm trigger --action=change --settle --name-match={root}")
    if efi:
        installer.wait_until_succeeds("test -b " + esp)
        installer.succeed(f"mkfs.fat -F32 -n ASSBOX_CI_ESP {esp}")
        installer.succeed(f"udevadm trigger --action=change --settle --name-match={esp}")
else:
    installer.wait_until_succeeds("test -b " + root)
    installer.succeed(f"e2fsck -p -E journal_only {root}; status=$?; test $status -le 1", timeout=120)
assert installer.succeed("lsblk -nr -o TYPE " + disk).split() == ["disk", "part", "part"]
installer.succeed(f"mkdir -p /mnt/installed && mount {root} /mnt/installed")
if efi:
    installer.succeed(f"mkdir -p /mnt/installed/boot/efi && mount {esp} /mnt/installed/boot/efi")
if recovery is None:
    installer.fail("test -e /mnt/installed/nix/var/nix/profiles/system")
else:
    prior_system = installer.succeed(
        'readlink "/mnt/installed/nix/var/nix/profiles/$(readlink /mnt/installed/nix/var/nix/profiles/system)"'
    ).strip()
    assert prior_system.startswith("/nix/store/") and prior_system != installed
installer.succeed(f"nix-store --check-validity {installed}")
installer.succeed(
    f"nixos-install --root /mnt/installed --system {installed} --no-root-password --no-channel-copy",
    timeout=install_timeout,
)
active_profile = installer.succeed(
    'readlink "/mnt/installed/nix/var/nix/profiles/$(readlink /mnt/installed/nix/var/nix/profiles/system)"'
).strip()
assert active_profile == installed
if efi:
    installer.succeed("test -s /mnt/installed/boot/efi/EFI/BOOT/BOOTAA64.EFI")
else:
    installer.succeed("test -s /mnt/installed/boot/grub/grub.cfg")
installer.succeed("sync && umount -R /mnt/installed")
installer.shutdown()

target.start()
target.wait_for_unit("multi-user.target", timeout=300)
assert target.succeed("readlink /run/current-system").strip() == installed
assert target.succeed("findmnt -n -o FSTYPE /").strip() == "ext4"
reported_target = target.succeed("systemctl get-default").strip()
assert "systemd.unit=" not in target.succeed("cat /proc/cmdline")
assert target.succeed("systemctl is-active multi-user.target").strip() == "active"
target.fail("systemctl --quiet is-active graphical.target")
target.fail("systemctl --quiet is-active display-manager.service")
assert target.succeed("id -u headless-probe").strip() == "1234"

for program in ("chromium", "google-chrome", "firefox", "Xorg", "Xvfb", "Xvnc", "weston"):
    target.fail("test -x /run/current-system/sw/bin/" + program)

unit_files = target.succeed("systemctl list-unit-files --no-legend --no-pager")
units = [line.split()[0] for line in unit_files.splitlines() if line.split()]
blocked_units = ("assbox-worker", "assbox-cua", "display-manager")
assert not any(name.startswith(blocked_units) for name in units), units
target.fail("test -S /tmp/.X11-unix/X0")
target.fail("test -S /run/user/1234/wayland-0")
processes = target.succeed("ps -eo comm=")
assert not set(processes.split()) & {"Xorg", "Xvfb", "Xvnc", "chromium", "firefox", "weston"}

namespace = "unshare --net --"
interfaces = [row["ifname"] for row in json.loads(target.succeed(namespace + " ip -j link show"))]
routes = target.succeed(namespace + " ip route").splitlines()
assert interfaces == ["lo"] and not routes, (interfaces, routes)

# Keep the installed resolver running. Hide every host pathname socket from
# the CLI processes by mounting a private /run in their network namespace.
assert target.succeed("systemctl is-active systemd-resolved.service").strip() == "active"
target.succeed("test -S /run/systemd/resolve/io.systemd.Resolve")
system_bin = target.succeed("readlink -e /run/current-system/sw").strip() + "/bin"
assert system_bin.startswith("/nix/store/")
gid = target.succeed("id -g headless-probe").strip()
assert gid.isdecimal()
for program in ("bash", "env", "mount", "setpriv", "setsid", "timeout", "unshare"):
    target.succeed("test -x " + quote(system_bin + "/" + program))
isolate = (
    quote(system_bin + "/unshare") + " --net --mount --propagation private -- "
    + quote(system_bin + "/bash") + " -ec "
    + quote(
        quote(system_bin + "/mount") + " -t tmpfs -o mode=0755,size=8M tmpfs /run; "
        "test ! -S /run/systemd/resolve/io.systemd.Resolve; "
        "test ! -S /run/dbus/system_bus_socket; exec \"$@\""
    )
    + " assbox-private-run "
)
inside = target.succeed(isolate + quote(system_bin + "/ip") + " -j link show")
assert [row["ifname"] for row in json.loads(inside)] == ["lo"]
assert not target.succeed(isolate + quote(system_bin + "/ip") + " route").splitlines()

commands = {}
for identity, entry in sorted(expected["expected"].items()):
    name = entry["command"]
    executable = "/run/current-system/sw/bin/" + name
    output = entry["output"]
    expected_path = target.succeed("readlink -e " + quote(output + "/bin/" + name)).strip()
    assert expected_path.startswith("/nix/store/")
    assert target.succeed("readlink -e " + quote(executable)).strip() == expected_path
    installed_executable = system_bin + "/" + name
    assert target.succeed("readlink -e " + quote(installed_executable)).strip() == expected_path
    help_command = [
        system_bin + "/setpriv", "--reuid", "1234", "--regid", gid,
        "--init-groups", "--no-new-privs", system_bin + "/env", "-i",
        "HOME=/home/headless-probe", "USER=headless-probe", "LOGNAME=headless-probe",
        "TERM=dumb", "PATH=" + system_bin, "CI=1", system_bin + "/setsid",
        "--wait", system_bin + "/bash", "-ec",
        'test ! -t 0 && test ! -t 1 && test ! -t 2; '
        'if (exec </dev/tty) 2>/dev/null; then exit 72; fi; exec "$@"',
        "assbox-no-tty", system_bin + "/timeout", "45s", installed_executable, "--help",
    ]
    help_capture = "/tmp/assbox-cli-offline-" + name
    status, help_output = target.execute(
        isolate + " ".join(map(quote, help_command))
        + " </dev/null >" + quote(help_capture) + " 2>&1; result=$?; "
        + "cat " + quote(help_capture) + "; exit $result",
        timeout=60,
    )
    commands[identity] = {
        "command": name, "output": output, "resolvedExecutable": expected_path,
        "helpExit": status, "helpCharacters": len(help_output.strip()),
    }

assert target.succeed("systemctl is-active systemd-resolved.service").strip() == "active"
target.succeed("test -S /run/systemd/resolve/io.systemd.Resolve")
print(json.dumps({"curatedHelpOutcomes": commands}, sort_keys=True))
assert len(commands) == 8
diagnosis = {
    "installed": installed,
    "installedFromOfflineSquashfs": True,
    "bootedFromInstalledExt4Disk": True,
    "upgradedVerifiedX86Snapshot": recovery is not None,
    "configuration": expected,
    "commands": commands,
    "activeBootTarget": "multi-user.target",
    "graphicalTargetActive": False,
    "networkInterfaces": interfaces,
    "networkRoutes": routes,
    "controllingTerminal": False,
    "standardInput": "/dev/null",
    "standardOutputAndError": "regular file",
    "timeoutSeconds": 45,
}
Path(target.out_dir / "current-installed-offline-cli.json").write_text(json.dumps(diagnosis, indent=2) + "\n")
assert all(item["helpExit"] == 0 and item["helpCharacters"] >= 20 for item in commands.values()), commands

target.shutdown()
