# SPDX-License-Identifier: GPL-3.0-or-later
"""Real management operations on the disk produced by installed_cases.py.

Release transport alone is controlled. Builds, system profiles, bootloader writes,
reboots, filesystem persistence and collection use the production implementation.
"""
STATE = '/var/lib/assbox'
TXN = STATE + '/transaction'
PENDING = STATE + '/pending-reboot'
PROFILE = '/nix/var/nix/profiles/system'
LOCAL = '/etc/nixos/local.nix'
MANAGE = shlex.quote(harness) + ' --ignored --exact acceptance::management --nocapture'


def operation(name, succeeds=True):
    command = 'ASSBOX_TEST_OPERATION=' + name + ' ' + MANAGE + ' 2>&1'
    return (target.succeed if succeeds else target.fail)(command, timeout=3600)


def selected():
    return target.succeed('readlink -f ' + PROFILE).strip()


def running():
    return target.succeed('readlink -f /run/current-system').strip()


def pending_system():
    fields = target.succeed('cat ' + PENDING).splitlines()
    assert len(fields) == 3 and fields[0] == 'assbox-pending-reboot-v1', fields
    return fields[1]


def boot_again():
    target.shutdown()
    target.start()
    target.wait_for_unit('multi-user.target', timeout=600)
    target.wait_until_succeeds('test $(systemctl show assbox-boot-check.timer -p SubState --value) = elapsed')
    target.succeed('assbox internal boot-check')
    assert running() == selected()


def start_cut(operation_name, cut):
    target.succeed('rm -f ' + CASE + '/reached')
    write(target, CASE + '/cut', 'pause:' + cut)
    target.succeed('systemd-run --collect --unit=acceptance-operation --service-type=exec '
                   'env ASSBOX_TEST_OPERATION=' + operation_name + ' ' + MANAGE)
    # A cut operation normally remains active until the driver removes its
    # control file. If it exits first, surface its journal immediately instead
    # of waiting for the outer NixOS test timeout.
    target.wait_until_succeeds(
        'test -f ' + CASE + '/reached || ! systemctl is-active --quiet acceptance-operation.service',
        timeout=3600,
    )
    target.succeed(
        'test -f ' + CASE + '/reached || '
        '{ journalctl --no-pager -u acceptance-operation.service; false; }'
    )
    assert target.succeed('cat ' + CASE + '/reached') == cut


def clear_cut():
    target.succeed('rm -f ' + CASE + '/cut ' + CASE + '/reached')


initial = running()
assert initial == selected()
target.wait_for_unit('assbox-boot-check.timer')
target.wait_until_succeeds('test $(systemctl show assbox-boot-check.service -p Result --value) = success; test $(systemctl show assbox-boot-check.timer -p SubState --value) = elapsed')
boot_check_id = target.succeed('systemctl show assbox-boot-check.service -p InvocationID --value').strip()
assert boot_check_id
operation('add')
target.succeed('hello | grep "Hello, world!"')
assert running() == selected() and running() != initial
operation('remove')
target.fail('test -e /run/current-system/sw/bin/hello')
assert running() == selected()
assert target.succeed('systemctl show assbox-boot-check.service -p InvocationID --value').strip() == boot_check_id
target.succeed('test $(systemctl show assbox-boot-check.service -p Result --value) = success; test ! -e ' + TXN)

# Each crash follows a real operation reaching the named durable boundary.
# Before activation recovery restores sources; afterwards inspection is required.
cuts = [
    ('manage-pre-publish', False), ('manage-prepared', False),
    ('manage-built', False), ('manage-published', False),
    ('manage-source-assbox-packages.nix', False), ('manage-activating', True),
    ('manage-profile', True), ('manage-activated', True),
    ('manage-committed', False), ('manage-pre-retire', False), ('manage-retired', False),
]
for cut, inspect_activation in cuts:
    operation('remove')
    old = selected()
    floor = target.succeed('cat ' + STATE + '/release-state')
    start_cut('add', cut)
    target.crash()
    target.start()
    target.wait_for_unit('multi-user.target', timeout=600)
    clear_cut()
    if inspect_activation:
        assert 'activation may have partially changed' in operation('recover', False)
        target.succeed('test -d ' + TXN)
        operation('recover-rollback')
        assert selected() == old
    else:
        operation('recover')
    assert target.succeed('cat ' + STATE + '/release-state') == floor
    target.fail('test -e ' + TXN)
    boot_again()
    if cut not in ('manage-committed', 'manage-pre-retire', 'manage-retired'):
        target.fail('test -e /run/current-system/sw/bin/hello')
    else:
        target.succeed('hello')

# An intervening administrator edit is never silently overwritten by recovery.
operation('remove')
start_cut('add', 'manage-source-assbox-packages.nix')
candidate = target.succeed('cat /etc/nixos/assbox-packages.nix')
write(target, '/etc/nixos/assbox-packages.nix', candidate + '\n# administrator edit\n')
target.succeed('systemctl kill --signal=KILL acceptance-operation.service')
target.wait_until_succeeds('! systemctl is-active --quiet acceptance-operation.service')
clear_cut()
operation('recover', False)
target.succeed('grep "administrator edit" /etc/nixos/assbox-packages.nix; test -d ' + TXN)
write(target, '/etc/nixos/assbox-packages.nix', candidate)
operation('recover')

# Boot-menu limits are mutable policy. Immutable bindings and receipt versions
# are checked on the actual built target before a profile or loader write.
local_base = target.succeed('cat ' + LOCAL)


def local_extra(expression):
    assert local_base.rstrip().endswith('}')
    write(target, LOCAL, local_base.rstrip()[:-1] + expression + '\n}\n')


# A changed service definition also must not run the automatic check on switch.
local_extra('systemd.services.assbox-boot-check.environment.ASSBOX_ACCEPTANCE = "changed";')
before_check = target.succeed('systemctl show assbox-boot-check.service -p InvocationID --value').strip()
operation('switch')
assert target.succeed('systemctl show assbox-boot-check.service -p InvocationID --value').strip() == before_check
target.succeed('test ! -e ' + TXN)
write(target, LOCAL, local_base)

for limit in [4, 8]:
    local_extra('assbox.boot.generations = ' + str(limit) + ';')
    before = running()
    operation('stage')
    assert running() == before
    assert pending_system() == selected()
    boot_again()
    assert json.loads(target.succeed('cat /run/current-system/assbox-boot-policy.json'))['policy']['generations'] == limit

for expression in [
    'assbox.boot.disk = lib.mkForce "/dev/disk/by-id/foreign-disk";',
    '''system.systemBuilderCommands = lib.mkAfter ''
      rm "$out/assbox-boot-policy.json"
      ln -s ${pkgs.writeText "unknown-receipt.json" ''{"schema":999}''} "$out/assbox-boot-policy.json"
    '';''',
]:
    before = selected()
    local_extra(expression)
    operation('stage', False)
    assert selected() == before and running() == before
    target.fail('test -e ' + TXN)
write(target, LOCAL, local_base)

# Failed effects before publication leave source and profile untouched.
local_extra('system.systemBuilderCommands = lib.mkAfter "exit 71";')
before = selected()
operation('stage', False)
assert selected() == before
target.fail('test -e ' + TXN)
write(target, LOCAL, local_base)

# An activation program can fail after the profile has already changed. Keep the
# real journal, require explicit recovery, then boot the old selected generation.
local_extra('system.activationScripts.acceptanceFailure.text = "echo reached > /var/lib/assbox-acceptance/failed-activation; exit 72";')
old = selected()
operation('switch', False)
target.succeed('test -f ' + CASE + '/failed-activation; test "$(cat ' + TXN + '/phase)" = activating')
assert 'activation may have partially changed' in operation('recover', False)
operation('recover-rollback')
assert selected() == old
write(target, LOCAL, local_base)
boot_again()

# A real three-file authenticated update stops after each source rename. Recovery
# restores the source set but cannot rewind the independently persisted floor.
old_release = target.succeed('cat /etc/nixos/assbox-release.json')
old_floor = target.succeed('cat ' + STATE + '/release-state')
for name in ['flake.nix', 'flake.lock', 'assbox-release.json']:
    start_cut('update', 'manage-source-' + name)
    advanced_floor = target.succeed('cat ' + STATE + '/release-state')
    assert advanced_floor != old_floor
    target.crash()
    target.start()
    target.wait_for_unit('multi-user.target', timeout=600)
    clear_cut()
    operation('recover')
    assert target.succeed('cat /etc/nixos/assbox-release.json') == old_release
    assert target.succeed('cat ' + STATE + '/release-state') == advanced_floor
    assert running() == selected()

# Enable the actual runtime maintenance policy. Timers remain test-disabled so
# the test driver controls the moment of staging and reboot.
write(target, LOCAL, local_base.replace('enable = false; rebootGraceSeconds', 'enable = true; rebootGraceSeconds'))
operation('switch')
assert json.loads(target.succeed('cat /etc/assbox/runtime.json'))['updates']['enable']
target.succeed('cp ' + CASE + '/case.json ' + CASE + '/online.json')

for budget in ['not-a-number', '3']:
    # A distinct local configuration forces a real next generation even though
    # both test release envelopes contain the same reviewed source tree.
    current_local = target.succeed('cat ' + LOCAL)
    write(target, LOCAL, current_local.rstrip()[:-1] + '\n environment.etc."acceptance-budget-' + str(len(budget)) + '".text = "test";\n}\n')
    operation('update')
    desired = selected()
    assert desired != running()
    assert json.loads(target.succeed('cat /etc/nixos/assbox-release.json'))['tag'] == 'r-2'
    old_boot = target.succeed('cat /proc/sys/kernel/random/boot_id')
    booted = target.succeed('readlink -f /run/booted-system').strip()
    operation('switch')
    assert running() == desired and pending_system() == desired
    # Repeating the same update must not discharge a live-switched generation.
    operation('update')
    assert selected() == desired and pending_system() == desired
    # A further live change retargets the outstanding reboot.
    live_local = target.succeed('cat ' + LOCAL)
    write(target, LOCAL, live_local.rstrip()[:-1] + '\n environment.etc."acceptance-live-' + str(len(budget)) + '".text = "test";\n}\n')
    operation('switch')
    assert selected() != desired
    desired = selected()
    assert running() == desired and pending_system() == desired
    # The documented standard NixOS switch path also cannot count as a boot.
    target.succeed(shlex.quote(desired + '/bin/switch-to-configuration') + ' switch', timeout=600)
    target.fail('assbox internal boot-check')
    assert pending_system() == desired
    assert target.succeed('cat /proc/sys/kernel/random/boot_id') == old_boot
    assert target.succeed('readlink -f /run/booted-system').strip() == booted != desired
    write(target, STATE + '/stage-retry', budget)
    # Missing and unreadable recovery state must still take priority over reboot.
    for state_command in ['mkdir -m700 ' + TXN, 'ln -s /missing-journal ' + TXN]:
        target.succeed(state_command)
        assert 'interrupted operation' in operation('maintenance', False)
        assert pending_system() == desired
        target.succeed('rm -rf ' + TXN)
    offline = json.loads(target.succeed('cat ' + CASE + '/online.json'))
    offline['urls'] = {}
    write(target, CASE + '/case.json', json.dumps(offline))
    calls = target.succeed('wc -l < ' + CASE + '/calls.jsonl')
    boot_id = target.succeed('cat /proc/sys/kernel/random/boot_id')
    target.succeed('systemd-run --collect --unit=acceptance-reboot env ASSBOX_TEST_OPERATION=maintenance ' + MANAGE)
    target.wait_for_shutdown()
    target.start()
    target.wait_for_unit('multi-user.target', timeout=600)
    assert target.succeed('cat /proc/sys/kernel/random/boot_id') != boot_id
    target.wait_until_succeeds('test $(systemctl show assbox-boot-check.timer -p SubState --value) = elapsed')
    target.succeed('assbox internal boot-check')
    assert running() == desired == selected()
    assert target.succeed('readlink -f /run/booted-system').strip() == desired
    target.fail('test -e ' + PENDING)
    assert target.succeed('wc -l < ' + CASE + '/calls.jsonl') == calls
    assert target.succeed('cat ' + STATE + '/stage-retry') == budget
    target.succeed('cp ' + CASE + '/online.json ' + CASE + '/case.json')

# Retention removes actual obsolete profile generations and real unrooted data;
# current generation and test input roots survive. A further reboot checks the menu.
target.succeed('printf disposable-unrooted-garbage > /tmp/collect-me')
garbage = target.succeed('nix-store --add /tmp/collect-me').strip()
target.succeed('rm /tmp/collect-me')
operation('cleanup')
target.fail('test -e ' + shlex.quote(garbage))
generations = target.succeed('nix-env --profile ' + PROFILE + ' --list-generations').splitlines()
assert len(generations) <= 2, generations
assert running() == selected()
boot_again()
