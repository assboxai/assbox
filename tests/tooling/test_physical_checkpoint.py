# SPDX-License-Identifier: GPL-3.0-or-later
"""Physical checkpoint image policy and release-bound output contracts."""

import json
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class PhysicalCheckpointTests(unittest.TestCase):
    def test_mac_milestone_keeps_direct_efi_and_refind_as_separate_runs(self):
        checkpoint = (ROOT / 'docs/physical-checkpoint.md').read_text()
        acceptance = (ROOT / 'docs/intel-mac-acceptance.md').read_text()
        for document in (checkpoint, acceptance):
            self.assertIn('rEFInd', document)
            self.assertIn('separately', document)
        checkpoint_words = ' '.join(checkpoint.split())
        acceptance_words = ' '.join(acceptance.split())
        self.assertIn('Option at power-on', checkpoint_words)
        self.assertIn('one path does not stand in for the other', checkpoint_words)
        self.assertIn("Apple's Option boot menu", acceptance_words)
        self.assertIn('neither boot path substitutes', acceptance_words)

    def test_flake_exposes_one_x86_image_as_a_configuration_package_and_check(self):
        flake = (ROOT / 'flake.nix').read_text()
        self.assertEqual(flake.count('physical-checkpoint-iso = (physicalCheckpoint system).config.system.build.isoImage;'), 2)
        self.assertIn('x86_64-linux-physical-checkpoint = physicalCheckpoint "x86_64-linux";', flake)
        self.assertIn('nixpkgs.lib.optionalAttrs (system == "x86_64-linux")', flake)
        self.assertIn('physical-checkpoint-boot =', flake)
        self.assertGreater(flake.index('physical-checkpoint-boot ='),
                           flake.index('checks = eachSystem'))

    def test_checkpoint_assbox_does_not_retain_installer_or_rebuild_tools(self):
        flake = (ROOT / 'flake.nix').read_text()
        tools = flake.split('checkpointTools = with p.pkgs; [', 1)[1].split('];', 1)[0]
        self.assertNotIn('\n            nix\n', tools)
        self.assertNotIn('nixos-install', tools)
        self.assertNotIn('nixos-rebuild', tools)
        self.assertNotIn('gptfdisk', tools)
        self.assertIn('checkpointAssbox = p.assbox.overrideAttrs', flake)
        self.assertIn('checkpointSystemd = p.pkgs.systemd.override', flake)
        self.assertIn('withLibBPF = false;', flake)
        self.assertIn('withTpm2Tss = false;', flake)
        self.assertIn('ASSBOX_TOOL_PATH = p.pkgs.lib.makeBinPath checkpointTools;', flake)
        self.assertIn('doCheck = false;', flake)
        self.assertIn('assboxMode = "diagnostic-only";',
                      (ROOT / 'nix/physical-checkpoint-iso.nix').read_text())
        self.assertIn('checkpointDbus = pkgs.dbus.override { x11Support = false; };',
                      (ROOT / 'nix/physical-checkpoint-iso.nix').read_text())

    def test_boot_check_uses_the_same_image_for_bios_and_uefi_usb(self):
        source = (ROOT / 'tests/nix/physical-checkpoint-boot.nix').read_text()
        self.assertIn('requiredSystemFeatures = [ "kvm" ];', source)
        self.assertIn('-machine pc,accel=kvm', source)
        self.assertIn('-drive "if=ide,format=raw,readonly=on,file=$iso"', source)
        self.assertIn('-machine q35,accel=kvm', source)
        self.assertIn('${ovmf.firmware}', source)
        self.assertIn('${ovmf.variables}', source)
        self.assertIn('-device usb-storage,drive=checkpoint,bootindex=1', source)
        self.assertEqual(source.count('wait_for_ready '), 2)
        for symbol in ('CONFIG_CFG80211=m', 'CONFIG_MAC80211=m', 'CONFIG_BT=m',
                       'CONFIG_SND=m', 'CONFIG_SND_HDA_INTEL=m',
                       'CONFIG_SND_USB_AUDIO=m', 'CONFIG_USB_VIDEO_CLASS=m',
                       '# CONFIG_RFKILL_INPUT is not set'):
            self.assertIn(symbol, source)
        for symbol in ('CONFIG_BT_HCIBTUSB', 'CONFIG_USB_NET_CDC_MBIM',
                       'CONFIG_IEEE802154', 'CONFIG_NFC',
                       'CONFIG_USB_NET_QMI_WWAN', 'CONFIG_UWB', 'CONFIG_WWAN'):
            self.assertIn(symbol, source)
        self.assertIn('is built into the checkpoint kernel', source)

    def test_live_readiness_is_fail_closed_and_reports_only_after_checks(self):
        source = (ROOT / 'nix/physical-checkpoint-iso.nix').read_text()
        self.assertIn('boot.supportedFilesystems = lib.mkForce [', source)
        self.assertIn('environment.systemPackages = lib.mkForce [', source)
        marker = source.index('ASSBOX_PHYSICAL_CHECKPOINT_READY')
        for required in (
                'systemctl is-active --quiet assbox-device-policy-check.service',
                'module_blacklist=.*cfg80211.*snd',
                'rfkill.default_state=0',
                '/sys/class/net/*',
                'test "$wired_carrier" = 1',
                '/sys/class/rfkill/rfkill*',
                '/sys/class/bluetooth/*',
                '/sys/class/wwan/*',
                '/sys/class/sound/*',
                '/dev/snd/*',
                '/sys/class/video4linux/*',
                '${assboxCodex}/bin/codex',
                '${assboxHappier}/bin/happier'):
            self.assertIn(required, source[:marker], required)
        self.assertIn('wiredCarrierPresent:true', source)
        self.assertIn('requires = [ "assbox-device-policy-check.service" ];', source)
        self.assertIn('_module.args.assboxDevicePolicyNetworkUnit = "systemd-networkd.service";',
                      source)
        self.assertIn('after = [', source)
        self.assertIn('"systemd-networkd.service"', source)

    def test_release_gate_scans_the_exact_iso_closure(self):
        source = (ROOT / 'scripts/release-check').read_text()
        self.assertIn('".#packages.$architecture.physical-checkpoint-iso"', source)
        self.assertIn('closure_targets+=("$checkpoint_iso")', source)
        self.assertIn('scan_closures "reports/vulnix-$architecture-release-closures.json"',
                      source)

    def test_evaluated_image_keeps_hybrid_boot_and_disabled_devices(self):
        expression = '''c: {
          devices = c.assbox.devices;
          suspend = c.assbox.power.suspend.enable;
          blacklist = c.boot.blacklistedKernelModules;
          kernelParams = c.boot.kernelParams;
          supportedFilesystems = c.boot.supportedFilesystems;
          initrdEmergencyAccess = c.boot.initrd.systemd.emergencyAccess;
          initrdSystemd = c.boot.initrd.systemd.enable;
          zfsForceImportRoot = c.boot.zfs.forceImportRoot;
          lvm = c.services.lvm.enable;
          initrdLvm = c.boot.initrd.services.lvm.enable;
          bcache = c.boot.bcache.enable;
          initrdBcache = c.boot.initrd.services.bcache.enable;
          swraid = c.boot.swraid.enable;
          modemManager = c.networking.modemmanager.enable;
          nixEnabled = c.nix.enable;
          switchEnabled = c.system.switch.enable;
          coredumpEnabled = c.systemd.coredump.enable;
          registerNixPaths = c.systemd.services.register-nix-paths.enable;
          networkManager = c.networking.networkmanager.enable;
          networkd = c.systemd.network.enable;
          systemdPackage = c.systemd.package.pname;
          hwdbName = c.environment.etc."udev/hwdb.bin".source.name;
          wireless = c.networking.wireless.enable;
          openssh = c.services.openssh.enable;
          dbusImplementation = c.services.dbus.implementation;
          fontconfig = c.fonts.fontconfig.enable;
          iso = {
            bios = c.isoImage.makeBiosBootable;
            efi = c.isoImage.makeEfiBootable;
            usb = c.isoImage.makeUsbBootable;
            volume = c.isoImage.volumeID;
            baseName = c.image.baseName;
          };
          readiness = {
            requiredBy = c.systemd.services.assbox-physical-checkpoint-readiness.requiredBy;
            requires = c.systemd.services.assbox-physical-checkpoint-readiness.requires;
          };
          deviceGateRequiredBy = c.systemd.services.assbox-device-policy-check.requiredBy;
          accounts = {
            autologin = c.services.getty.autologinUser;
            sudo = c.security.sudo.enable;
            polkit = c.security.polkit.enable;
            rootPassword = c.users.users.root.hashedPassword;
            hasNixosUser = c.users.users ? nixos;
            agentGroups = c.users.users.agent.extraGroups;
            suForwardXAuth = c.security.pam.services.su.forwardXAuth;
          };
          systemPackages = map (package: package.pname or package.name or "unknown") c.environment.systemPackages;
        }'''
        result = subprocess.run([
            'nix', 'eval', '--json', '--no-update-lock-file', '--no-write-lock-file',
            '.#nixosConfigurations.x86_64-linux-physical-checkpoint.config',
            '--apply', expression,
        ], cwd=ROOT, capture_output=True, text=True, timeout=180)
        self.assertEqual(result.returncode, 0, result.stderr)
        value = json.loads(result.stdout)
        self.assertEqual(value['devices'], {
            'audio': {'enable': False},
            'bluetooth': {'enable': False},
            'camera': {'enable': False},
            'wifi': {'enable': False},
        })
        self.assertFalse(value['suspend'])
        self.assertFalse(value['networkManager'])
        self.assertTrue(value['networkd'])
        self.assertEqual(value['systemdPackage'], 'systemd-assbox-checkpoint')
        self.assertTrue(value['hwdbName'].startswith('assbox-checkpoint-hwdb.bin'))
        self.assertFalse(value['wireless'])
        self.assertFalse(value['openssh'])
        self.assertEqual(value['dbusImplementation'], 'dbus')
        self.assertFalse(value['fontconfig'])
        for module in ('cfg80211', 'mac80211', 'wl', 'bluetooth', 'wwan', 'snd',
                       'snd_hda_intel', 'snd_usb_audio', 'facetimehd', 'uvcvideo'):
            self.assertIn(module, value['blacklist'])
        self.assertTrue(any(item.startswith('module_blacklist=') for item in value['kernelParams']))
        self.assertIn('rfkill.default_state=0', value['kernelParams'])
        self.assertFalse(value['zfsForceImportRoot'])
        self.assertFalse(value['lvm'])
        self.assertFalse(value['initrdLvm'])
        self.assertFalse(value['bcache'])
        self.assertFalse(value['initrdBcache'])
        self.assertFalse(value['swraid'])
        self.assertFalse(value['modemManager'])
        self.assertFalse(value['nixEnabled'])
        self.assertFalse(value['switchEnabled'])
        self.assertFalse(value['coredumpEnabled'])
        self.assertFalse(value['registerNixPaths'])
        self.assertTrue(value['initrdSystemd'])
        self.assertFalse(value['initrdEmergencyAccess'])
        self.assertEqual(value['supportedFilesystems'], {
            'iso9660': True,
            'overlay': True,
            'squashfs': True,
            'tmpfs': True,
            'vfat': True,
        })
        self.assertNotIn('zfs', value['systemPackages'])
        self.assertNotIn('nixos-install', value['systemPackages'])
        self.assertNotIn('gptfdisk', value['systemPackages'])
        self.assertNotIn('parted', value['systemPackages'])
        for package in ('assbox', 'codex', 'happier', 'git',
                        'openssh', 'pciutils', 'usbutils', 'util-linux'):
            self.assertIn(package, value['systemPackages'])
        self.assertNotIn('networkmanager', value['systemPackages'])
        self.assertTrue(value['iso']['bios'])
        self.assertTrue(value['iso']['efi'])
        self.assertTrue(value['iso']['usb'])
        self.assertEqual(value['iso']['volume'], 'ASSBOX_CHECKPOINT')
        self.assertTrue(value['iso']['baseName'].startswith('assbox-checkpoint-'))
        self.assertTrue(value['iso']['baseName'].endswith('-x86_64-linux'))
        self.assertEqual(value['readiness']['requiredBy'], ['multi-user.target'])
        self.assertEqual(value['readiness']['requires'], ['assbox-device-policy-check.service'])
        self.assertEqual(value['deviceGateRequiredBy'], ['systemd-networkd.service'])
        self.assertEqual(value['accounts'], {
            'agentGroups': [],
            'autologin': 'agent',
            'hasNixosUser': False,
            'polkit': False,
            'rootPassword': '!',
            'suForwardXAuth': False,
            'sudo': False,
        })


if __name__ == '__main__':
    unittest.main()
