# SPDX-License-Identifier: GPL-3.0-or-later
"""NixOS test-driver scenario. Executed with server/installer/target fixtures.

Every destructive command addresses disposable guest disks. No fake disk, build,
profile, activation or GC implementation is used. External release evidence is
controlled separately and is not claimed to be a public signature round trip.
"""
import json
import shlex
import base64
import hashlib

CASE = '/var/lib/assbox-acceptance'
# The backdoor shell has a TTY. Ordinary cases must fail an unexpected build
# retry instead of waiting for input; the retry scenario uses its own PTY below.
INSTALL = shlex.quote(harness) + ' --ignored --exact acceptance::install_apply --nocapture < /dev/null'


def write(machine, path, value):
    machine.succeed('printf %s ' + shlex.quote(value) + ' > ' + shlex.quote(path))


def mount_read(machine, device, command):
    machine.succeed('mkdir -p /mnt/inspect; mount -o ro,noload ' + shlex.quote(device) + ' /mnt/inspect')
    try:
        return machine.succeed(command)
    finally:
        machine.succeed('umount /mnt/inspect')


def root_phase():
    return mount_read(installer, root, 'jq -r .phase /mnt/inspect/.assbox-install.json').strip()


def clear_work():
    installer.fail("systemctl list-units --state=activating,active --no-legend 'assbox-install-*.service' | grep assbox-install-")
    installer.fail("findmnt -rn -o TARGET | grep '^/run/assbox-install/'")
    installer.succeed('rm -rf /run/assbox-install; rm -f ' + CASE + '/cut ' + CASE + '/reached')


def format_target():
    clear_work()
    # Every case begins with a distinct filesystem identity. Erase any bounded
    # ENOSPC signature and wait for udev to publish the new UUID before the
    # installer captures an inventory that it will later revalidate.
    installer.succeed(
        'wipefs --all --force ' + root + '; mkfs.ext4 -F ' + root
        + '; udevadm trigger --action=change --settle --name-match=' + root
    )
    if esp:
        installer.succeed('mkfs.fat -F32 ' + esp + '; mkdir -p /mnt/esp; mount -t vfat ' + esp + ' /mnt/esp')
        if mode == 'apple-refind':
            # Real rEFInd and a preserved unrelated payload; this does NOT boot macOS.
            installer.succeed('mkdir -p /mnt/esp/EFI/refind /mnt/esp/EFI/BOOT /mnt/esp/EFI/APPLE')
            installer.succeed('cp ' + refind + ' /mnt/esp/EFI/refind/refind_x64.efi; cp ' + refind + ' /mnt/esp/EFI/BOOT/BOOTX64.EFI')
            write(installer, '/mnt/esp/EFI/APPLE/retained', 'unrelated EFI payload\n')
            write(installer, '/mnt/esp/EFI/refind/refind.conf', 'timeout 2\nscanfor manual\nmenuentry "Assbox test" {\n loader /EFI/Assbox/grubx64.efi\n}\n')
            # The fallback copy uses its own directory for configuration.
            installer.succeed('cp /mnt/esp/EFI/refind/refind.conf /mnt/esp/EFI/BOOT/refind.conf')
        installer.succeed('sync; umount /mnt/esp')


def before_boot_bytes():
    command = 'sfdisk --dump ' + disk
    if esp:
        command += '; sha256sum ' + esp
    else:
        # BIOS activation may write the MBR and embedding area.
        command += '; dd if=' + disk + ' bs=1M count=1 status=none | sha256sum'
    return installer.succeed(command)


def snapshot_target():
    # The target is unmounted at both comparison boundaries. QEMU's shared-read
    # flag permits observing its still-attached device. Sparse comparison checks
    # all logical bytes without reading tens of GiB of identical zero clusters.
    installer.succeed('sync')
    snapshot = str(installer.shared_dir / 'before-target.qcow2')
    Path(snapshot).unlink(missing_ok=True)
    subprocess.run([qemu_img, 'convert', '-U', '-f', 'qcow2', '-O', 'qcow2', target_image, snapshot], check=True)
    return snapshot


def assert_target_unchanged(snapshot):
    installer.succeed('sync')
    subprocess.run([qemu_img, 'compare', '-U', '-f', 'qcow2', '-F', 'qcow2', snapshot, target_image], check=True)
    Path(snapshot).unlink()


def start_install(cut=None, timeout=3600):
    if cut:
        write(installer, CASE + '/cut', 'pause:' + cut)
    installer.succeed(INSTALL + ' > /tmp/install.log 2>&1 & echo $! > /tmp/install.pid')
    if cut:
        installer.succeed(
            'timeout ' + str(timeout) + " sh -c 'while test ! -f " + CASE
            + '/reached && kill -0 "$(cat /tmp/install.pid)" 2>/dev/null; '
            + "do sleep 1; done' || true; test -f " + CASE
            + '/reached || { tail -200 /tmp/install.log >&2; false; }',
            timeout=timeout + 60,
        )
        assert installer.succeed('cat ' + CASE + '/reached') == cut


def wait_install_exit():
    installer.wait_until_succeeds('! kill -0 $(cat /tmp/install.pid) 2>/dev/null', timeout=3600)


def temporary_local(extra):
    # Replace the disposable /etc symlink, never write through it into the store.
    installer.succeed('rm -f /etc/assbox-acceptance-local.nix')
    write(installer, '/etc/assbox-acceptance-local.nix', local_base.rstrip()[:-1] + extra + '\n}\n')


server.start()
server.wait_for_unit('multi-user.target')
server.succeed('python3 ' + release_script + ' ' + source + ' ' + CASE, timeout=300)
server.succeed('systemctl start source-mirror')
server.wait_for_open_port(443)
installer.start()
installer.wait_for_unit('multi-user.target')
installer.succeed('mkdir -p /iso; mount -o ro /dev/sr0 /iso')
# Copy fixture evidence from the isolated server; actual Nix source acquisition
# still traverses the local TLS mirror and verifies the locked archive NAR.
server.succeed('tar -C ' + CASE + ' -cf /tmp/release-fixture.tar .')
server.copy_from_vm('/tmp/release-fixture.tar', '.fixture')
installer.copy_from_host(str(server.out_dir / '.fixture/release-fixture.tar'), '/tmp/release-fixture.tar')
installer.succeed('mkdir -m700 ' + CASE + '; tar -C ' + CASE + ' -xf /tmp/release-fixture.tar')
disk = installer.succeed('readlink -f /dev/disk/by-id/virtio-assbox-target').strip()
assert disk.startswith('/dev/vd')
assert int(installer.succeed('blockdev --getss ' + disk)) == sector_size
if mode in ('uefi', 'apple-refind'):
    layout = 'label: gpt\nsize=512M,type=U\n' + ('size=64M,type=7C3457EF-0000-11AA-AA11-00306543ECAC\n' if mode == 'apple-refind' else '') + 'type=L\n'
    root_number = 3 if mode == 'apple-refind' else 2
    esp = disk + '1'
elif mode == 'bios-gpt':
    layout, root_number, esp = 'label: gpt\nsize=2M,type=21686148-6449-6E6F-744E-656564454649\ntype=L\n', 2, None
else:
    layout, root_number, esp = 'label: dos\nstart=2048,type=83\n', 1, None
write(installer, '/tmp/layout', layout)
installer.succeed('sfdisk ' + disk + ' < /tmp/layout; udevadm settle')
root = disk + str(root_number)
# Both writable fixture disks have stable serials independent of drive order.
installer.succeed("printf 'label: gpt\ntype=L\n' | sfdisk /dev/disk/by-id/virtio-assbox-backup; udevadm settle; mkfs.ext4 -F /dev/disk/by-id/virtio-assbox-backup-part1")
backup = installer.succeed('readlink -f /dev/disk/by-id/virtio-assbox-backup-part1').strip()
request = {'root': root, 'esp': esp or '', 'backup': backup,
           'platform': 'macbookpro12-1' if mode == 'apple-refind' else 'generic',
           'key': installer.succeed('cat ' + key).strip()}
write(installer, CASE + '/install.json', json.dumps(request))
format_target()
refind_digest = installer.succeed('sha256sum ' + refind).split()[0] if refind else None
local_base = installer.succeed('cat /etc/assbox-acceptance-local.nix')
retained_digest = installer.succeed('sha256sum ' + disk + '2').split()[0] if mode == 'apple-refind' else None

# Existing/recovered data is never removed or repaired. Compare all target bytes,
# not only a marker file, around these production-path refusal cases.
if scenario == 'install':
    if mode == 'apple-refind':
        # Real sysfs DMI must prevent choosing a generic/foreign Mac profile,
        # before release transport, mounts, backup or target writes.
        request = json.loads(installer.succeed('cat ' + CASE + '/install.json'))
        for platform in ('generic', 'apple-intel', 'macbookpro11-1'):
            write(installer, CASE + '/install.json', json.dumps(dict(request, platform=platform)))
            before = snapshot_target()
            assert 'detected Mac model requires' in installer.fail(INSTALL + ' 2>&1', timeout=60)
            assert_target_unchanged(before)
        write(installer, CASE + '/install.json', json.dumps(request))
    for setup in ['touch /mnt/edit/existing', 'touch /mnt/edit/lost+found/recovered',
                  'rmdir /mnt/edit/lost+found; ln -s /tmp /mnt/edit/lost+found',
                  'chmod 777 /mnt/edit/lost+found']:
        installer.succeed('mkdir -p /mnt/edit; mount ' + root + ' /mnt/edit; ' + setup + '; sync; umount /mnt/edit')
        before = snapshot_target()
        installer.fail(INSTALL, timeout=900)
        assert_target_unchanged(before)
        format_target()
    # Pre-write injected failure occurs after real configuration evaluation and
    # backup read-back. Both external archive and target preservation are checked.
    write(installer, CASE + '/cut', 'fail:install-pre-write')
    before = snapshot_target()
    assert 'install-pre-write' in installer.fail(INSTALL + ' 2>&1', timeout=1800)
    assert_target_unchanged(before)
    format_target()
    # Corrupt a newly written backup artifact before the real read-back, without
    # altering the target. The VM removes only this deliberately damaged fixture.
    before = snapshot_target()
    start_install('install-backup-written')
    damaged = installer.succeed('ls -td /run/assbox-install/backup/assbox-*/ | head -1').strip().rstrip('/')
    installer.succeed('echo corrupted >> ' + shlex.quote(damaged + '/partition-table.json'))
    installer.succeed('rm ' + CASE + '/cut')
    wait_install_exit()
    installer.succeed('grep "external backup read-back failed" /tmp/install.log')
    assert_target_unchanged(before)
    installer.succeed('mkdir -p /mnt/damaged-backup; mount /dev/disk/by-id/virtio-assbox-backup-part1 /mnt/damaged-backup; rm -rf ' + shlex.quote('/mnt/damaged-backup/' + damaged.rsplit('/', 1)[1]) + '; umount /mnt/damaged-backup')
    format_target()
    # A real exhausted backup filesystem must refuse before any target write.
    installer.succeed('mkdir -p /mnt/full-backup; mount /dev/disk/by-id/virtio-assbox-backup-part1 /mnt/full-backup')
    installer.succeed('fallocate -l "$(df -B1 --output=avail /mnt/full-backup | tail -1)" /mnt/full-backup/filler; umount /mnt/full-backup')
    before = snapshot_target()
    assert 'backup lacks room' in installer.fail(INSTALL + ' 2>&1', timeout=1800)
    assert_target_unchanged(before)
    installer.succeed('mount /dev/disk/by-id/virtio-assbox-backup-part1 /mnt/full-backup; rm /mnt/full-backup/filler; umount /mnt/full-backup')
    format_target()
    # Cancellation also interrupts the password client and reaps it without ever
    # putting its output in logs or waiting for user input to release the mounts.
    evidence = json.loads(installer.succeed('cat ' + CASE + '/case.json'))
    write(installer, CASE + '/case.json', json.dumps(dict(evidence, pause_password=True)))
    before = snapshot_target()
    start_install()
    installer.wait_until_succeeds('test -f ' + CASE + '/password-pid', timeout=1800)
    password_pid = installer.succeed('cat ' + CASE + '/password-pid').strip()
    installer.succeed('kill -TERM $(cat /tmp/install.pid)')
    wait_install_exit()
    installer.fail('kill -0 ' + password_pid)
    assert_target_unchanged(before)
    write(installer, CASE + '/case.json', json.dumps(evidence))
    format_target()
    # A cancellation after target writes is not a boot activation and does not
    # authorize restart against a populated root.
    write(installer, CASE + '/cut', 'pause:install-building')
    boot_before = before_boot_bytes()
    installer.succeed(INSTALL + ' > /tmp/install.log 2>&1 & echo $! > /tmp/install.pid')
    installer.wait_until_succeeds('test -f ' + CASE + '/reached', timeout=1800)
    installer.succeed('kill -TERM $(cat /tmp/install.pid)')
    installer.wait_until_succeeds('! kill -0 $(cat /tmp/install.pid) 2>/dev/null', timeout=90)
    assert root_phase() == 'building'
    assert before_boot_bytes() == boot_before
    clear_work()
    refusal = installer.fail(INSTALL + ' 2>&1', timeout=900)
    assert 'installation record' in refusal, refusal
    format_target()
    # Kill an installer with an actual sandbox grandchild still running. The
    # supervised cgroup, not only the immediate nix client, must be drained.
    temporary_local('system.systemBuilderCommands = lib.mkAfter "sleep 300";')
    boot_before = before_boot_bytes()
    start_install()
    child_query = "ps -eo cgroup:200,pid,comm | awk '$3 == \"sleep\" && $1 ~ /assbox-install-/ { print $2 }'"
    installer.wait_until_succeeds('test -n "$(' + child_query + ')"', timeout=3600)
    children = installer.succeed(child_query).split()
    installer.succeed('kill -TERM $(cat /tmp/install.pid)')
    wait_install_exit()
    for child in children:
        installer.fail('kill -0 ' + child)
    assert root_phase() == 'building'
    assert before_boot_bytes() == boot_before
    format_target()
    temporary_local('')

    # Source/configuration drift and a new external mount invalidate the captured
    # selection before invoking the builder. Neither permits boot activation.
    for change in ['configuration', 'mount']:
        boot_before = before_boot_bytes()
        start_install('install-building')
        if change == 'configuration':
            installer.succeed('echo "# concurrent edit" >> /run/assbox-install/target/etc/nixos/local.nix')
        else:
            # The installer deliberately owns a writable mount at this checkpoint.
            # A second device mount with `-o ro` is rejected by modern mount before
            # Assbox can observe it, so create a real alias of the owned mount and
            # prove that it still resolves to the selected root block device.
            installer.succeed(
                'mkdir -p /mnt/alias; mount --bind /run/assbox-install/target /mnt/alias; '
                'test "$(findmnt -nr -o SOURCE --mountpoint /mnt/alias)" = ' + root
            )
        installer.succeed('rm ' + CASE + '/cut')
        wait_install_exit()
        installer.succeed('grep -E "configuration changed|mount" /tmp/install.log')
        if change == 'mount':
            installer.succeed('umount /mnt/alias')
        assert root_phase() == 'building'
        assert before_boot_bytes() == boot_before
        format_target()

    # Limit the test filesystem (not its device) and consume its free blocks.
    # Eight GiB admits the authenticated kernel closure and preflight work before
    # the checkpoint, while remaining bounded for the deliberate ENOSPC build.
    # A genuine ENOSPC build failure retains the phase and untouched boot region.
    installer.succeed('mkfs.ext4 -F -b4096 ' + root + ' 2097152')
    boot_before = before_boot_bytes()
    start_install('install-building')
    installer.succeed('fallocate -l "$(df -B1 --output=avail /run/assbox-install/target | tail -1)" /run/assbox-install/target/filler')
    installer.succeed('rm ' + CASE + '/cut')
    wait_install_exit()
    installer.succeed('grep "bootloader activation has not started" /tmp/install.log')
    assert root_phase() == 'building'
    assert before_boot_bytes() == boot_before
    format_target()
    # Abrupt VM power loss exercises durable state rather than a returned error.
    for cut in ['install-target-writes', 'install-built', 'install-activating', 'install-completing']:
        start_install(cut, timeout=1800 if cut == 'install-target-writes' else 3600)
        installer.crash()
        installer.start()
        installer.wait_for_unit('multi-user.target')
        installer.succeed('mount -o ro /dev/sr0 /iso')
        # Kernel journal replay on the disposable root is explicit test recovery,
        # never an installer permission to repair user filesystems.
        installer.succeed('mkdir -p /mnt/replay; mount ' + root + ' /mnt/replay; umount /mnt/replay')
        assert root_phase() != 'complete'
        installer.succeed('rm -f ' + CASE + '/cut ' + CASE + '/reached')
        refusal = installer.fail(INSTALL + ' 2>&1', timeout=900)
        assert 'installation record' in refusal, refusal
        format_target()

if scenario == 'install':
    # The exact same derivation fails while its external fixed-output input is
    # unavailable, then succeeds after an explicit y in the same install process.
    token_hash = 'sha256-' + base64.b64encode(hashlib.sha256(b'assbox disposable build input\n').digest()).decode()
    temporary_local('''system.systemBuilderCommands = lib.mkAfter ''
      cp ${pkgs.fetchurl { url = "https://github.com/acceptance/build-token";
        hash = "''' + token_hash + '''";
        # The target store is independent of the installer store. Preserve Nix
        # string context so this disposable CA is copied into that target store.
        curlOpts = "--cacert ${pkgs.writeText "assbox-disposable-build-ca.pem" ''' + json.dumps(test_ca_pem) + '''} --retry 0";
      }} "$out/acceptance-token"
    '';''')
    server.succeed('touch ' + CASE + '/block-build-token')
    boot_before = before_boot_bytes()
    installer.succeed('python3 ' + terminal_script + ' ' + harness + ' > /tmp/terminal-controller.log 2>&1 &')
    installer.wait_until_succeeds('test -f ' + CASE + '/retry-ready', timeout=3600)
    assert before_boot_bytes() == boot_before
    installer.succeed('test $(jq -r .phase /run/assbox-install/target/.assbox-install.json) = building')
    server.succeed('rm ' + CASE + '/block-build-token')
    write(installer, CASE + '/retry-answer', 'y\n')
    installer.wait_until_succeeds('test -f ' + CASE + '/terminal-status', timeout=3600)
    assert installer.succeed('cat ' + CASE + '/terminal-status') == '0'
else:
    installer.succeed(INSTALL, timeout=3600)
assert root_phase() == 'complete'
if retained_digest:
    assert installer.succeed('sha256sum ' + disk + '2').split()[0] == retained_digest
installer.succeed('mkdir -p /mnt/backup; mount -o ro /dev/disk/by-id/virtio-assbox-backup-part1 /mnt/backup')
installer.succeed('for manifest in /mnt/backup/assbox-*/SHA256SUMS; do (cd "$(dirname "$manifest")"; sha256sum -c SHA256SUMS); done')
installer.succeed('umount /mnt/backup')
installer.succeed('mount ' + root + ' /mnt/inspect')
# Copy only test harness dependencies/evidence, using real Nix closure transfer.
# The installed assbox executable remains the normal production package.
installer.succeed('nix copy --to /mnt/inspect ' + shlex.quote(harness.rsplit('/libexec/', 1)[0]) + ' ' + shlex.quote(dependencies), timeout=900)
# Keep the offline build closure and test runner rooted across real GC tests.
installer.succeed('mkdir -p /mnt/inspect/nix/var/nix/gcroots; ln -s ' + dependencies + ' /mnt/inspect/nix/var/nix/gcroots/acceptance-inputs; ln -s ' + shlex.quote(harness.rsplit('/libexec/', 1)[0]) + ' /mnt/inspect/nix/var/nix/gcroots/acceptance-harness')
installer.succeed('mkdir -p /mnt/inspect' + CASE + '; cp -a ' + CASE + '/. /mnt/inspect' + CASE)
installer.succeed('rm -f /mnt/inspect' + CASE + '/cut /mnt/inspect' + CASE + '/reached; sync; umount /mnt/inspect')
installer.shutdown()  # Releases QEMU's disk lock; target has no live ISO attached.
target.start()
target.wait_for_unit('multi-user.target', timeout=600)
target.succeed('test -f /etc/NIXOS; test ! -e /iso; test $(jq -r .phase /.assbox-install.json) = complete')
target.succeed('test $(stat -c %a /var/lib/assbox-secrets/admin-password.hash) = 600')
target.succeed('test $(stat -c %a /var/lib/assbox) = 700; test -s /var/lib/assbox/release-state')
target.succeed('assbox status; systemctl is-active sshd')
target.succeed("getent shadow root | cut -d: -f2 | grep '^!$'")
target.wait_for_open_port(22)
server.succeed('cp ' + private_key + ' /tmp/admin-key; chmod 600 /tmp/admin-key')
ssh = 'ssh -o BatchMode=yes -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -i /tmp/admin-key '
assert server.succeed(ssh + 'admin@192.168.1.3 id -un').strip() == 'admin'
server.fail(ssh + 'agent@192.168.1.3 true')
server.fail(ssh + 'root@192.168.1.3 true')
target.fail('runuser -u agent -- sudo -n true')
target.fail('runuser -u agent -- head -c1 /dev/vda')
if mode == 'apple-refind':
    target.succeed('grep "unrelated EFI payload" /boot/efi/EFI/APPLE/retained')
    assert target.succeed('sha256sum /boot/efi/EFI/refind/refind_x64.efi').split()[0] == refind_digest
if scenario == 'activation':
    exec(compile(Path(activation_script).read_text(), activation_script, 'exec'))
target.shutdown()
server.shutdown()
