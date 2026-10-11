# SPDX-License-Identifier: GPL-3.0-or-later
"""Real module evaluations; installed boot evidence belongs to the VM cases."""
import json
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[2]


def configuration(mode, extra=''):
    expression = '''let
      f = builtins.getFlake (toString ./.);
      lib = f.inputs.nixpkgs.lib;
      system = lib.nixosSystem {
        system = "x86_64-linux";
        modules = [ f.nixosModules.default ./tests/nix/fixture.nix
          ({ lib, ... }: {
            assbox.platform = "macbookpro11-1";
            assbox.boot.mode = MODE;
            assbox.updates.enable = false;
            EXTRA
          }) ];
      };
      c = system.config;
    in {
      mode = c.assbox.audit.boot;
      nvram = c.assbox.audit.efiWrites;
      fallback = c.boot.loader.grub.efiInstallAsRemovable;
      systemdBoot = c.boot.loader.systemd-boot.enable;
      grub = c.boot.loader.grub.enable;
      usbModules = c.boot.initrd.availableKernelModules;
      rejected = map (a: a.message) (lib.filter (a: !a.assertion) c.assertions);
    }'''.replace('MODE', json.dumps(mode)).replace('EXTRA', extra)
    result = subprocess.run([
        'nix', 'eval', '--impure', '--json', '--no-update-lock-file',
        '--no-write-lock-file', '--expr', expression,
    ], cwd=ROOT, capture_output=True, text=True, timeout=180)
    if result.returncode:
        raise AssertionError(result.stderr)
    return json.loads(result.stdout)


class LaptopBootTests(unittest.TestCase):
    def test_both_mac_strategies_keep_nvram_fixed_and_usb_root_drivers(self):
        for mode in ['apple-efi', 'apple-refind']:
            with self.subTest(mode=mode):
                value = configuration(mode)
                self.assertEqual(value['rejected'], [])
                self.assertEqual(value['mode'], mode)
                self.assertFalse(value['nvram'])
                self.assertFalse(value['systemdBoot'])
                self.assertTrue(value['grub'])
                self.assertEqual(value['fallback'], mode == 'apple-efi')
                self.assertTrue({'uhci_hcd', 'ohci_pci', 'ehci_pci', 'xhci_pci',
                                 'usb_storage', 'uas', 'sd_mod'} <= set(value['usbModules']))

    def test_direct_mac_configuration_refuses_firmware_writes_and_missing_fallback(self):
        for extra in [
            'boot.loader.efi.canTouchEfiVariables = lib.mkForce true;',
            'boot.loader.grub.efiInstallAsRemovable = lib.mkForce false;',
        ]:
            with self.subTest(extra=extra):
                value = configuration('apple-efi', extra)
                self.assertTrue(any('Direct Apple EFI' in message for message in value['rejected']))


if __name__ == '__main__':
    unittest.main()
