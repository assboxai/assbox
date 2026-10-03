# SPDX-License-Identifier: GPL-3.0-or-later
"""Frozen NixOS driver scenario; destructive operations stay inside fresh guests."""
import hashlib
import json
from pathlib import Path
import select
import shlex
import subprocess
import time

CASE = '/var/lib/assbox-acceptance'
postboot = []
postboot_deadline = None

for machine in (server, installer, target):
    machine.out_dir = machine.out_dir / machine.name
    machine.out_dir.mkdir(mode=0o700)


def write(machine, path, value):
    machine.succeed('printf %s ' + shlex.quote(value) + ' > ' + shlex.quote(path))


def assert_guest(number, command):
    target.succeed('set -eu; ' + command, timeout=postboot_remaining())
    postboot.append({'id': 'P%02d' % number, 'status': 'passed'})


def postboot_remaining():
    remaining = postboot_deadline - time.monotonic()
    if remaining <= 0: raise TimeoutError('postboot phase deadline')
    return max(1, int(remaining))


def boot(machine):
    deadline = time.monotonic() + 600
    machine.start()
    marker = machine.out_dir.parent / 'vm-started.json'
    if not marker.exists(): marker.write_text(json.dumps({'vm_executed': True, 'first_guest': machine.name}) + '\n')
    while not select.select([machine.shell], [], [], 1)[0]:
        if time.monotonic() >= deadline: raise TimeoutError('guest boot deadline: ' + machine.name)
    machine.shell.settimeout(max(1, deadline - time.monotonic()))
    try: machine.connect()
    finally: machine.shell.settimeout(None)
    remaining = deadline - time.monotonic()
    if remaining <= 0: raise TimeoutError('guest boot deadline: ' + machine.name)
    machine.wait_for_unit('multi-user.target', timeout=max(1, int(remaining)))


def collect():
    # Keep the earliest assertion error; collection failure is separate evidence.
    for machine, commands in [(installer, ['journalctl -b --no-pager']), (target, ['journalctl -b --no-pager', 'systemctl --failed --no-legend'])]:
        if not machine.booted or not machine.connected:
            continue
        for index, command in enumerate(commands):
            try:
                value = machine.succeed(command, timeout=30)
                (machine.out_dir / ('journal.txt' if index == 0 else 'systemctl-failed.txt')).write_text(value[:64 * 1024 * 1024])
            except Exception as error:
                (machine.out_dir / 'collection-error.txt').write_text(type(error).__name__)
    (target.out_dir / 'postboot.json').write_text(json.dumps(postboot, sort_keys=True) + '\n')
    for guest_path in ([CASE + '/terminal/installer-transcript.txt', CASE + '/terminal/phase-events.jsonl',
                       CASE + '/fixture-calls.jsonl', CASE + '/fixture-release.json',
                       '/run/assbox-install/target/.assbox-install.json'] if installer.booted and installer.connected else []):
        try: installer.copy_from_vm(guest_path, '.')
        except Exception: pass


for image, size in [('assbox-target.qcow2', '64G'), ('assbox-backup.qcow2', '2G')]:
    path = installer.shared_dir / image
    assert not path.exists()
    subprocess.run([qemu_img, 'create', '-f', 'qcow2', str(path), size], check=True)

try:
    boot(server)
    server.succeed('python3 ' + release_script + ' ' + source + ' ' + CASE + ' ' + revision + ' ' + content_digest, timeout=300)
    server.succeed('systemctl start source-mirror'); server.wait_for_open_port(443)
    server.succeed('mkdir -m700 /run/assbox-keys; ssh-keygen -q -t ed25519 -N "" -C disposable-vm -f /run/assbox-keys/key')
    public_key = server.succeed('cat /run/assbox-keys/key.pub').strip()
    server.succeed('tar -C ' + CASE + ' -cf /tmp/release-fixture.tar .')
    server.copy_from_vm('/tmp/release-fixture.tar', '.fixture')
    boot(installer)
    installer.succeed('test -d /sys/firmware/efi')
    installer.succeed('mkdir -p /iso; mount -o ro /dev/sr0 /iso')
    installer.copy_from_host(str(server.out_dir / '.fixture/release-fixture.tar'), '/tmp/release-fixture.tar')
    installer.succeed('mkdir -m700 ' + CASE + '; tar -C ' + CASE + ' -xf /tmp/release-fixture.tar')
    target_disk = installer.succeed('readlink -f /dev/disk/by-id/virtio-assbox-repair-target').strip()
    backup_disk = installer.succeed('readlink -f /dev/disk/by-id/virtio-assbox-repair-backup').strip()
    assert target_disk != backup_disk and target_disk.startswith('/dev/vd') and backup_disk.startswith('/dev/vd')
    assert int(installer.succeed('blockdev --getsize64 ' + target_disk)) == 64 * 1024 ** 3
    assert int(installer.succeed('blockdev --getsize64 ' + backup_disk)) == 2 * 1024 ** 3
    assert int(installer.succeed('blockdev --getss ' + target_disk)) == 512
    for disk in (target_disk, backup_disk):
        assert installer.succeed('lsblk -nro MOUNTPOINTS ' + disk).strip() == ''
        assert installer.succeed('wipefs -n --noheadings ' + disk).strip() == ''
    write(installer, '/tmp/target-layout', 'label: gpt\nsize=512M,type=U\ntype=L\n')
    write(installer, '/tmp/backup-layout', 'label: gpt\ntype=L\n')
    installer.succeed('set -eu; sfdisk ' + target_disk + ' < /tmp/target-layout; sfdisk ' + backup_disk + ' < /tmp/backup-layout; udevadm settle')
    root = installer.succeed('readlink -f /dev/disk/by-id/virtio-assbox-repair-target-part2').strip()
    esp = installer.succeed('readlink -f /dev/disk/by-id/virtio-assbox-repair-target-part1').strip()
    backup = installer.succeed('readlink -f /dev/disk/by-id/virtio-assbox-repair-backup-part1').strip()
    assert root == target_disk + '2' and esp == target_disk + '1' and backup == backup_disk + '1'
    installer.succeed('set -eu; mkfs.ext4 -F ' + root + '; mkfs.fat -F32 ' + esp + '; mkfs.ext4 -F ' + backup)
    inventory = dict(root=root, esp=esp, backup=backup, target_by_id='/dev/disk/by-id/virtio-assbox-repair-target', admin_key=public_key)
    write(installer, CASE + '/inventory.json', json.dumps(inventory))
    installer.succeed('python3 ' + terminal_script + ' ' + cli + ' ' + CASE + '/inventory.json ' + CASE + '/terminal', timeout=10800)
    installer.copy_from_vm(CASE + '/terminal/installer-transcript.txt', '.')
    installer.copy_from_vm(CASE + '/terminal/phase-events.jsonl', '.')
    installer.copy_from_vm(CASE + '/fixture-calls.jsonl', '.')
    installer.copy_from_vm(CASE + '/fixture-release.json', '.')
    calls = json.loads(installer.succeed('python3 -c ' + shlex.quote('import json; print(json.dumps([json.loads(x) for x in open("' + CASE + '/fixture-calls.jsonl")]))')))
    assert len([c for c in calls if c[0] == 'systemd-ask-password']) == 2
    installer.succeed('mkdir -p /mnt/installed; mount ' + root + ' /mnt/installed')
    record = json.loads(installer.succeed('cat /mnt/installed/.assbox-install.json'))
    assert record['phase'] == 'complete' and record['disk'] == inventory['target_by_id']
    assert record['rootUuid'] == installer.succeed('blkid -s UUID -o value ' + root).strip()
    assert record['espUuid'] == installer.succeed('blkid -s UUID -o value ' + esp).strip()
    assert record['backupUuid'] == installer.succeed('blkid -s UUID -o value ' + backup).strip()
    assert record['manifestSha256'] == hashlib.sha256(server.succeed('cat ' + CASE + '/r-1-release.json').encode()).hexdigest()
    installer.copy_from_vm('/mnt/installed/.assbox-install.json', '.')
    # Machine-local instrumentation is applied AFTER the untouched production
    # CLI completed. This is a second real build/install, explicitly recorded.
    # No alternate OS, privileged resolver or test CLI is put on the target.
    original_system = installer.succeed('readlink -f /mnt/installed/nix/var/nix/profiles/system').strip()
    installer.succeed('mount ' + esp + ' /mnt/installed/boot/efi')
    installer.succeed('cp ' + instrumentation + ' /mnt/installed/etc/nixos/local.nix')
    installer.succeed('nixos-install --root /mnt/installed --flake path:/mnt/installed/etc/nixos#assbox --no-root-password --no-channel-copy', timeout=7200)
    effective_system = installer.succeed('readlink -f /mnt/installed/nix/var/nix/profiles/system').strip()
    installer.succeed('set -eu; sync; umount /mnt/installed/boot/efi; umount /mnt/installed')
    installer.succeed('set -eu; mkdir -p /mnt/backup; mount -o ro ' + backup + ' /mnt/backup; for m in /mnt/backup/assbox-*/SHA256SUMS; do (cd "$(dirname "$m")"; sha256sum -c SHA256SUMS); done; umount /mnt/backup')
    (installer.out_dir / 'instrumentation.json').write_text(json.dumps(dict(schema=1,
        sha256=hashlib.sha256(Path(instrumentation).read_bytes()).hexdigest(),
        applied_after_production_install=True, original_system=original_system, effective_system=effective_system,
        overrides=['test-driver access', 'locked root preserved', 'static eth1', 'local mirror CA', 'no substituters/builders', 'maintenance/reboot timers disabled'])) + '\n')
    installer_journal = installer.succeed('journalctl -b --no-pager', timeout=30)
    (installer.out_dir / 'journal.txt').write_text(installer_journal[:64 * 1024 * 1024])
    installer.shutdown()
    assert not installer.booted and installer.process.poll() is not None
    boot(target)
    postboot_deadline = time.monotonic() + 600
    postboot.append({'id': 'P01', 'status': 'passed'})
    assert_guest(2, 'test -f /etc/NIXOS; test "$(jq -r .phase /.assbox-install.json)" = complete')
    assert_guest(3, 'test ! -e /iso; test "$(findmnt -nro SOURCE /)" = /dev/vda2')
    assert_guest(4, 'test "$(stat -c %u:%a /var/lib/assbox)" = 0:700; test "$(stat -c %u:%a /var/lib/assbox/release-state)" = 0:600; '
        'test "$(sed -n 1p /var/lib/assbox/release-state)" = ASSBOX-RELEASE-1; test "$(sed -n 2p /var/lib/assbox/release-state)" = 1; '
        'test "$(wc -l < /var/lib/assbox/release-state)" = 4; grep -Eq "^[0-9a-f]{64}$" <(sed -n 3p /var/lib/assbox/release-state); '
        'grep -Eq "^[1-9][0-9]*$" <(sed -n 4p /var/lib/assbox/release-state)')
    assert_guest(5, 'test "$(stat -c %u:%a /var/lib/assbox-secrets/admin-password.hash)" = 0:600')
    assert_guest(6, 'assbox status')
    assert_guest(7, 'systemctl is-active sshd; test -z "$(systemctl --failed --no-legend)"')
    target.wait_for_open_port(22, timeout=postboot_remaining())
    ssh = 'ssh -o BatchMode=yes -o ConnectTimeout=20 -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -i /run/assbox-keys/key '
    assert server.succeed(ssh + 'admin@192.168.1.3 id -un', timeout=postboot_remaining()).strip() == 'admin'
    postboot.append({'id': 'P08', 'status': 'passed'})
    server.fail(ssh + 'root@192.168.1.3 true', timeout=postboot_remaining()); server.fail(ssh + 'agent@192.168.1.3 true', timeout=postboot_remaining())
    assert_guest(9, "set -o pipefail; sshd -T -f /etc/ssh/sshd_config | awk '{ $1 = tolower($1); print }' | grep -x 'passwordauthentication no' && getent shadow root | cut -d: -f2 | grep '^!$'")
    target.fail('runuser -u agent -- sudo -n true', timeout=postboot_remaining())
    target.fail('runuser -u agent -- head -c1 /dev/vda', timeout=postboot_remaining())
    target.fail('runuser -u agent -- head -c1 /var/lib/assbox-secrets/admin-password.hash', timeout=postboot_remaining())
    postboot.append({'id': 'P10', 'status': 'passed'})
    assert_guest(11, 'test ! -e /run/current-system/sw/bin/tailscale; test ! -e /run/current-system/sw/bin/assbox-worker; test ! -e /run/current-system/sw/bin/X; jq -e \' .presentation == "headless" and .selectedComponents == [] \' /etc/assbox-state.json')
    assert_guest(12, 'nix-store -q -R /run/current-system > /tmp/closure; if grep -E "canonical-installer-cli|canonical-external-fixtures" /tmp/closure; then exit 1; fi; test "$(readlink -f /run/current-system/sw/bin/assbox)" != ' + shlex.quote(cli))
    target.fail('systemctl is-enabled assbox-maintenance.timer', timeout=postboot_remaining())
    target.fail('systemctl is-enabled assbox-reboot-retry.timer', timeout=postboot_remaining())
    assert_guest(13, 'test "$(sha256sum /etc/nixos/local.nix | cut -d" " -f1)" = ' + hashlib.sha256(Path(instrumentation).read_bytes()).hexdigest() + '; test -f /etc/assbox-canonical-vm')
    assert_guest(14, 'jq -e \' .phase == "complete" \' /.assbox-install.json; grep -q ' + revision + ' /etc/nixos/assbox-release.json')
finally:
    collect()
    try:
        if server.booted and server.connected: server.succeed('rm -f /run/assbox-keys/key', timeout=10)
    except Exception: pass
    for machine in (installer, target, server):
        try: machine.crash()
        except Exception: pass
