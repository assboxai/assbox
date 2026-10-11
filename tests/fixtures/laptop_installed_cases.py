# SPDX-License-Identifier: GPL-3.0-or-later
"""Additional real-install/boot cases; every device belongs to disposable guests.

The original installation/fault/recovery scenarios remain separate and unchanged.
These cases qualify transport and loader behavior, not physical Apple firmware.
"""
import json
import shlex

CASE = '/var/lib/assbox-acceptance'


def write(machine, path, value):
    machine.succeed('printf %s ' + shlex.quote(value) + ' > ' + shlex.quote(path))


def internal_identity(machine):
    device = '/dev/disk/by-id/virtio-assbox-internal'
    return machine.succeed('sfdisk --dump ' + device + '; sha256sum ' + device)


server.start()
server.wait_for_unit('multi-user.target')
server.succeed('python3 ' + release_script + ' ' + source + ' ' + CASE, timeout=300)
server.succeed('systemctl start source-mirror')
server.wait_for_open_port(443)
installer.start()
installer.wait_for_unit('multi-user.target')
installer.succeed('mkdir -p /iso; mount -o ro /dev/sr0 /iso')
server.succeed('tar -C ' + CASE + ' -cf /tmp/release-fixture.tar .')
server.copy_from_vm('/tmp/release-fixture.tar', '.fixture')
installer.copy_from_host(str(server.out_dir / '.fixture/release-fixture.tar'), '/tmp/release-fixture.tar')
installer.succeed('mkdir -m700 ' + CASE + '; tar -C ' + CASE + ' -xf /tmp/release-fixture.tar')

if target_transport == 'usb':
    # Select by serial and whole-disk USB identity, never a /dev/sdX ordinal.
    aliases = installer.succeed(
        "find /dev/disk/by-id -maxdepth 1 -name 'usb-*assbox-target*' ! -name '*-part*' -print"
    ).splitlines()
    assert len(aliases) == 1, aliases
    target_id = aliases[0]
    assert installer.succeed('lsblk -dn -o TRAN ' + shlex.quote(target_id)).strip() == 'usb'
    internal = '/dev/disk/by-id/virtio-assbox-internal'
    installer.succeed("printf 'label: gpt\ntype=L\n' | sfdisk " + internal + '; udevadm settle')
    installer.succeed('mkfs.ext4 -F ' + internal + '-part1; mkdir -p /mnt/internal; mount ' + internal + '-part1 /mnt/internal')
    write(installer, '/mnt/internal/preserved', 'internal disk must remain untouched\n')
    installer.succeed('sync; umount /mnt/internal')
    internal_before = internal_identity(installer)
    layout = 'label: gpt\nsize=2M,type=21686148-6449-6E6F-744E-656564454649\ntype=L\n'
    root_number, esp_number, platform = 2, None, 'generic'
    entrypoint = 'acceptance::install_apply'
else:
    assert mode in ('apple-efi', 'apple-refind') and macbook_model == 'MacBookPro11,1'
    target_id = '/dev/disk/by-id/virtio-assbox-target'
    preservation = mode == 'apple-refind'
    layout = 'label: gpt\nsize=512M,type=U\n' + ('size=64M,type=7C3457EF-0000-11AA-AA11-00306543ECAC\n' if preservation else '') + 'type=L\n'
    root_number, esp_number, platform = (3 if preservation else 2), 1, 'macbookpro11-1'
    entrypoint = 'acceptance::install_apply' if preservation else 'acceptance::install_direct_apple_efi'
    firmware_before = installer.succeed('efibootmgr -v')

disk = installer.succeed('readlink -f ' + shlex.quote(target_id)).strip()
assert int(installer.succeed('blockdev --getss ' + shlex.quote(disk))) == sector_size
write(installer, '/tmp/laptop-layout', layout)
installer.succeed('sfdisk ' + shlex.quote(target_id) + ' < /tmp/laptop-layout; udevadm settle')
root = installer.succeed('readlink -f ' + shlex.quote(target_id + '-part' + str(root_number))).strip()
esp = '' if esp_number is None else installer.succeed('readlink -f ' + shlex.quote(target_id + '-part' + str(esp_number))).strip()
installer.succeed('mkfs.ext4 -F ' + shlex.quote(root))
if esp:
    installer.succeed('mkfs.fat -F32 ' + shlex.quote(esp))
    if mode == 'apple-refind':
        installer.succeed('mkdir -p /mnt/esp; mount ' + shlex.quote(esp) + ' /mnt/esp; mkdir -p /mnt/esp/EFI/refind /mnt/esp/EFI/BOOT /mnt/esp/EFI/APPLE')
        installer.succeed('cp ' + shlex.quote(refind) + ' /mnt/esp/EFI/refind/refind_x64.efi; cp ' + shlex.quote(refind) + ' /mnt/esp/EFI/BOOT/BOOTX64.EFI')
        refind_configuration = 'timeout 2\nscanfor manual\nmenuentry "Assbox test" {\n loader /EFI/Assbox/grubx64.efi\n}\n'
        write(installer, '/mnt/esp/EFI/refind/refind.conf', refind_configuration)
        write(installer, '/mnt/esp/EFI/BOOT/refind.conf', refind_configuration)
        write(installer, '/mnt/esp/EFI/APPLE/retained', 'unrelated EFI payload\n')
        refind_before = installer.succeed('sha256sum /mnt/esp/EFI/refind/refind_x64.efi').split()[0]
        installer.succeed('sync; umount /mnt/esp')
        retained_before = installer.succeed('sha256sum ' + shlex.quote(target_id + '-part2')).split()[0]
installer.succeed("printf 'label: gpt\ntype=L\n' | sfdisk /dev/disk/by-id/virtio-assbox-backup; udevadm settle; mkfs.ext4 -F /dev/disk/by-id/virtio-assbox-backup-part1")
backup = installer.succeed('readlink -f /dev/disk/by-id/virtio-assbox-backup-part1').strip()
request = {'root': root, 'esp': esp, 'backup': backup, 'platform': platform,
           'key': installer.succeed('cat ' + shlex.quote(key)).strip()}
write(installer, CASE + '/install.json', json.dumps(request))

install_command = shlex.quote(harness) + ' --ignored --exact ' + entrypoint + ' --nocapture < /dev/null'
installer.succeed(install_command, timeout=action_timeout)
installer.fail("findmnt -rn -o TARGET | grep '^/run/assbox-install/'")
if target_transport == 'usb':
    assert internal_identity(installer) == internal_before
else:
    assert installer.succeed('efibootmgr -v') == firmware_before
    if mode == 'apple-refind':
        assert installer.succeed('sha256sum ' + shlex.quote(target_id + '-part2')).split()[0] == retained_before
installer.succeed('mkdir -p /mnt/backup; mount -o ro /dev/disk/by-id/virtio-assbox-backup-part1 /mnt/backup')
installer.succeed('for manifest in /mnt/backup/assbox-*/SHA256SUMS; do (cd "$(dirname "$manifest")"; sha256sum -c SHA256SUMS); done')
installer.succeed('umount /mnt/backup')

# Release the target's image lock and cold-boot only the actual installed disk.
# The target VM has no live ISO, installer root or external backup attached.
installer.shutdown()
target.start()
target.wait_for_unit('multi-user.target', timeout=action_timeout)
target.succeed('test -f /etc/NIXOS; test ! -e /iso; test $(jq -r .phase /.assbox-install.json) = complete')
policy = json.loads(target.succeed('cat /run/current-system/assbox-boot-policy.json'))
assert policy['binding']['mode'] == mode
assert policy['binding']['disk'] == target_id
assert not policy['binding']['loader']['efiCanTouch']
root_source = target.succeed('findmnt -nro SOURCE /').strip()
root_device = target.succeed('readlink -f ' + shlex.quote(root_source)).strip()
assert target.succeed('readlink -f ' + shlex.quote(policy['binding']['rootDevice'])).strip() == root_device
target.fail('findmnt /iso')
target.fail('ls /dev/disk/by-id/virtio-assbox-backup')
if target_transport == 'usb':
    assert target.succeed('lsblk -dn -o TRAN ' + shlex.quote(target_id)).strip() == 'usb'
    assert internal_identity(target) == internal_before
    modules = target.succeed('lsmod')
    assert 'usb_storage' in modules and 'ehci' in modules
else:
    assert policy['binding']['platform'] == 'macbookpro11-1'
    if mode == 'apple-efi':
        assert policy['binding']['loader']['grubRemovable']
        target.succeed('test -s /boot/efi/EFI/BOOT/BOOTX64.EFI')
        target.fail('test -e /boot/efi/EFI/refind')
        target.succeed("test $(od -An -tx1 -N2 /boot/efi/EFI/BOOT/BOOTX64.EFI | tr -d ' \\n') = 4d5a")
    else:
        assert not policy['binding']['loader'].get('grubRemovable', False)
        assert target.succeed('sha256sum /boot/efi/EFI/refind/refind_x64.efi').split()[0] == refind_before
        assert target.succeed('sha256sum ' + shlex.quote(target_id + '-part2')).split()[0] == retained_before
        target.succeed('grep "unrelated EFI payload" /boot/efi/EFI/APPLE/retained; test -s /boot/efi/EFI/Assbox/grubx64.efi')
for pattern in ['wlan*', 'hci*']:
    target.fail('ls /sys/class/net/' + pattern)
for path in ['/sys/class/bluetooth/*', '/sys/class/sound/*', '/dev/snd/*', '/sys/class/video4linux/*']:
    target.fail('ls ' + path)
target.succeed('systemctl is-active assbox-device-policy-check.service')
target.succeed('test $(passwd -S root | cut -d" " -f2) = L; test $(passwd -S agent | cut -d" " -f2) = L')
target.succeed('su -s /run/current-system/sw/bin/sh agent -c "! sudo -n true"')
