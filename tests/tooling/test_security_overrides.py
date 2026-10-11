# SPDX-License-Identifier: GPL-3.0-or-later
import hashlib
import json
from pathlib import Path
import re
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[2]
PATCHES = [
    ('78ea09ed1633a583dbcde6e7bab9df4639ec8a34',
     '62b176c6ccec58f4355611eb8ad74762bb93223035440e062fc54281492075f9'),
    ('708b4a56bae080a5b18c2e0c4c6fbe103131a2b0',
     'd82986f9c9962813ed7ca92ae8dc8f7a98319a7f0729c516411224d2a4437034'),
    ('2f00c7bfc408b6582d331932dfa47829c4819029',
     'd767beb97d608e7255a543d55e81bce8e0b093b89078d849e56c1285f92748a9'),
    ('5733d3c59a5651f64357ac11c98b4f39895c8d25',
     '42ec4ff09eb02ddbebda889f76fc67ce7986e0ad105b6e4da64d94d52a432dc2'),
]
BUSYBOX_PATCH = (
    'f5e1bf966b19ea1821f00a8c9ecd7774598689b4',
    '4930f18f03df86694e8a27d761f64e214a958601c00fb9664c7c744466c88d65',
)
PATCH_PATCHES = [
    ('e6d6a4e021660679d7fc9150f981d4920f722313',
     '0c57857b669953347ee784531355a93f06292f06ac4efba2f797d3dab83c7cf6'),
    ('faba04ef4f2b410257f76c1b9dc85e350929c4b9',
     '89332d15fd4ac7c9e71d51443956238587da8ac964d787f87dd038286fcc7849'),
]
JBIG2DEC_PATCH = (
    'ee53a7e4bc7819d32e8c0b2057885bcc97586bf3',
    'f88604fbcd4e7a0c094d6d7eb406321ae73e0bf46e2f0ec19b79fa36ad6b5b30',
)
LIBSNDFILE_PATCHES = [
    ('4755f5bd7854611d92ad0f1295587b439f9950ba',
     '6ec653a4d728e413db93a25c7a516b9dfb475b31d2ce9242e99d0262357fd0c6'),
    ('d9a35ea0d5c64c19dd635ae578e0028df8f66d6a',
     '62a5da78eea59142faa3500eedc55786860039d0c29240bdc01c602e1426190d'),
    ('3d63704f6654e8bc02fd5b97c069e7fd6a44e44c',
     '20c205f99d3a35108b2c7b04ab3f6684d2c885b4a12afc2e7ccf5090d2a83592'),
    ('7ff854d1e0bd9a751a9ff52ed980c62afced91fe',
     '6f68c3e0e0f0c4ebd4b56899268dea2de09dee6eca7ebf38df116752236731b1'),
]


class SecurityOverrideTests(unittest.TestCase):
    def test_reviewed_jbig2dec_and_libsndfile_patch_bytes_are_exact(self):
        module = (ROOT / 'modules/security-overrides.nix').read_text()
        commit, digest = JBIG2DEC_PATCH
        path = ROOT / 'nix/patches' / f'jbig2dec-{commit}.patch'
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), digest)
        self.assertTrue(path.read_text().startswith(f'From {commit} '))
        self.assertIn('previous.jbig2dec.version == "0.20"', module)
        self.assertIn(path.name, module)
        positions = []
        for commit, digest in LIBSNDFILE_PATCHES:
            path = ROOT / 'nix/patches' / f'libsndfile-{commit}.patch'
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), digest)
            self.assertTrue(path.read_text().startswith(f'From {commit} '))
            positions.append(module.index(path.name))
        self.assertEqual(positions, sorted(positions))
        self.assertIn('previous.libsndfile.version == "1.2.2"', module)
        self.assertIn('configureFlags = (old.configureFlags or [ ]) '
                      '++ [ "--disable-mpeg" ];', module)

    def test_reviewed_busybox_patch_bytes_are_exact(self):
        module = (ROOT / 'modules/security-overrides.nix').read_text()
        commit, digest = BUSYBOX_PATCH
        path = ROOT / 'nix/patches' / f'busybox-{commit}.patch'
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), digest)
        self.assertTrue(path.read_text().startswith(f'From {commit} '))
        self.assertIn('previous.busybox.version == "1.37.0"', module)
        self.assertIn(path.name, module)

    def test_reviewed_gnu_patch_bytes_and_order_are_exact(self):
        module = (ROOT / 'modules/security-overrides.nix').read_text()
        positions = []
        for commit, digest in PATCH_PATCHES:
            path = ROOT / 'nix/patches' / f'patch-{commit}.patch'
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), digest)
            self.assertTrue(path.read_text().startswith(f'From {commit} '))
            positions.append(module.index(path.name))
        self.assertEqual(positions, sorted(positions))
        self.assertIn('assboxPatchedPatch =', module)
        self.assertIn('previous.patch.version == "2.8"', module)

    def test_reviewed_library_point_releases_are_exact_and_version_gated(self):
        module = (ROOT / 'modules/security-overrides.nix').read_text()
        expected = {
            'capstoneVersion = "5.0.9";':
                'sha256-uAiiKWKGjEATPE0Xc3g+aOLCz5ffIlDmf+7jaGwaZ4I=',
            'libusbVersion = "1.0.30";':
                'sha256-qgs8h1vSqJg2muBDWN5nJlvaMjGYZnwMg1m07rqzHco=',
            'nghttp2Version = "1.70.0";':
                'sha256-j6yh94qpmsO8F2ina34PazbY5qYsE4GHUbHSBfAvlAU=',
            'sqliteVersion = "3.53.3";':
                'sha256-u4C/ijv/wZJBzoq6WkvHTpw5gAE8sLXw8JdqmVFpQq8=',
        }
        for version, source_hash in expected.items():
            self.assertIn(version, module)
            self.assertIn(source_hash, module)
        for vulnerable in ('5.0.7', '1.0.29', '1.69.0', '3.51.2'):
            self.assertIn(f'package.version == "{vulnerable}"' if vulnerable == '3.51.2'
                          else f'version == "{vulnerable}"', module)
        self.assertIn('sqlite-doc-3530300.zip', module)
        self.assertIn('4e4962f6b303688412746b54200ff5402c047aee.patch', module)

    def test_ffmpeg_point_release_source_is_exact_and_version_gated(self):
        module = (ROOT / 'modules/security-overrides.nix').read_text()
        self.assertIn('ffmpegVersion = "8.1.3";', module)
        self.assertIn('package.version == "8.1.2"', module)
        self.assertIn('https://ffmpeg.org/releases/ffmpeg-${ffmpegVersion}.tar.xz', module)
        self.assertIn('sha256-cTjSjJbZ0+OvTuPYytcnQfj/tA2pDBESI13qPs0xeKM=', module)
        for attribute in ('ffmpeg_8', 'ffmpeg_8-headless', 'ffmpeg_8-full'):
            self.assertIn(attribute + ' = upgradeFfmpeg previous.' + attribute, module)

    def test_reviewed_dhcpcd_patch_bytes_and_order_are_exact(self):
        module = (ROOT / 'modules/security-overrides.nix').read_text()
        positions = []
        for commit, digest in PATCHES:
            path = ROOT / 'nix/patches' / f'dhcpcd-{commit}.patch'
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), digest)
            self.assertTrue(path.read_text().startswith(f'From {commit} '))
            positions.append(module.index(path.name))
        self.assertEqual(positions, sorted(positions))
        self.assertIn('previous.dhcpcd.version == "10.3.1"', module)
        dhcpcd_override = module.split('dhcpcd =', 1)[1].split('else\n              previous.dhcpcd', 1)[0]
        self.assertIsNone(re.search(r'^\s*version\s*=', dhcpcd_override, re.MULTILINE))

    def test_real_system_evaluation_contains_the_reviewed_patches(self):
        result = subprocess.run([
            'nix', 'eval', '--json', '--no-update-lock-file', '--no-write-lock-file',
            '.#nixosConfigurations.x86_64-linux-bios-gpt-none.pkgs.dhcpcd.patches',
        ], cwd=ROOT, capture_output=True, text=True, timeout=120)
        self.assertEqual(result.returncode, 0, result.stderr)
        actual = json.loads(result.stdout)
        self.assertEqual(len(actual), len(PATCHES))
        for value, (commit, _) in zip(actual, PATCHES, strict=True):
            self.assertTrue(value.endswith(f'dhcpcd-{commit}.patch'), value)

    def test_real_system_contains_the_busybox_fix(self):
        result = subprocess.run([
            'nix', 'eval', '--json', '--no-update-lock-file', '--no-write-lock-file',
            '.#nixosConfigurations.x86_64-linux-bios-gpt-none.pkgs',
            '--apply', 'p: p.busybox.patches',
        ], cwd=ROOT, capture_output=True, text=True, timeout=180)
        self.assertEqual(result.returncode, 0, result.stderr)
        commit, _ = BUSYBOX_PATCH
        self.assertTrue(any(value.endswith(f'busybox-{commit}.patch')
                            for value in json.loads(result.stdout)))

    def test_real_system_contains_the_gnu_patch_fixes(self):
        result = subprocess.run([
            'nix', 'eval', '--json', '--no-update-lock-file', '--no-write-lock-file',
            '.#nixosConfigurations.x86_64-linux-bios-gpt-none.pkgs', '--apply',
            'p: { original = p.patch.drvPath; patched = p.assboxPatchedPatch.drvPath; '
            'patches = p.assboxPatchedPatch.patches; }',
        ], cwd=ROOT, capture_output=True, text=True, timeout=120)
        self.assertEqual(result.returncode, 0, result.stderr)
        actual = json.loads(result.stdout)
        self.assertNotEqual(actual['patched'], actual['original'])
        for commit, _ in PATCH_PATCHES:
            self.assertTrue(any(value.endswith(f'patch-{commit}.patch')
                                for value in actual['patches']))

    def test_real_system_profile_uses_fixed_patch_without_replacing_stdenv(self):
        expression = (
            'let f = builtins.getFlake (toString ./.); '
            'stock = import f.inputs.nixpkgs { system = "x86_64-linux"; }; '
            'machine = f.nixosConfigurations.x86_64-linux-bios-gpt-none; '
            'paths = map (package: package.drvPath) machine.config.environment.corePackages; '
            'in { names = map (package: package.pname or package.name) '
            'machine.config.environment.corePackages; '
            'hasOriginal = builtins.elem machine.pkgs.patch.drvPath paths; '
            'hasPatched = builtins.elem machine.pkgs.assboxPatchedPatch.drvPath paths; '
            'stockStdenv = stock.stdenv.drvPath; '
            'configuredStdenv = machine.pkgs.stdenv.drvPath; }'
        )
        result = subprocess.run([
            'nix', 'eval', '--impure', '--json', '--no-update-lock-file',
            '--no-write-lock-file', '--expr', expression,
        ], cwd=ROOT, capture_output=True, text=True, timeout=180)
        self.assertEqual(result.returncode, 0, result.stderr)
        actual = json.loads(result.stdout)
        self.assertEqual(len(actual['names']), 30)
        self.assertEqual(actual['names'].count('patch'), 1)
        self.assertFalse(actual['hasOriginal'])
        self.assertTrue(actual['hasPatched'])
        self.assertEqual(actual['configuredStdenv'], actual['stockStdenv'])

    def test_real_system_contains_the_jbig2dec_and_libsndfile_fixes(self):
        result = subprocess.run([
            'nix', 'eval', '--json', '--no-update-lock-file', '--no-write-lock-file',
            '.#nixosConfigurations.x86_64-linux-bios-gpt-none.pkgs',
            '--apply', 'p: { jbig2dec = p.jbig2dec.patches; '
                       'libsndfile = p.libsndfile.patches; '
                       'libsndfileFlags = p.libsndfile.configureFlags; }',
        ], cwd=ROOT, capture_output=True, text=True, timeout=180)
        self.assertEqual(result.returncode, 0, result.stderr)
        actual = json.loads(result.stdout)
        commit, _ = JBIG2DEC_PATCH
        self.assertTrue(any(value.endswith(f'jbig2dec-{commit}.patch')
                            for value in actual['jbig2dec']))
        for commit, _ in LIBSNDFILE_PATCHES:
            self.assertTrue(any(value.endswith(f'libsndfile-{commit}.patch')
                                for value in actual['libsndfile']))
        self.assertIn('--disable-mpeg', actual['libsndfileFlags'])

    def test_real_system_uses_the_fixed_ffmpeg_point_release(self):
        result = subprocess.run([
            'nix', 'eval', '--json', '--no-update-lock-file', '--no-write-lock-file',
            '.#nixosConfigurations.x86_64-linux-bios-gpt-none.pkgs',
            '--apply', 'p: { default = p.ffmpeg.version; small = p.ffmpeg_8.version; '
                       'headless = p.ffmpeg_8-headless.version; full = p.ffmpeg_8-full.version; }',
        ], cwd=ROOT, capture_output=True, text=True, timeout=120)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(set(json.loads(result.stdout).values()), {'8.1.3'})

    def test_real_system_uses_the_reviewed_library_point_releases(self):
        result = subprocess.run([
            'nix', 'eval', '--json', '--no-update-lock-file', '--no-write-lock-file',
            '.#nixosConfigurations.x86_64-linux-bios-gpt-none.pkgs',
            '--apply', 'p: { capstone = p.capstone.version; libusb = p.libusb1.version; '
                       'nghttp2 = p.nghttp2.version; sqlite = p.sqlite.version; '
                       'sqliteInteractive = p.sqlite-interactive.version; }',
        ], cwd=ROOT, capture_output=True, text=True, timeout=180)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {
            'capstone': '5.0.9',
            'libusb': '1.0.30',
            'nghttp2': '1.70.0',
            'sqlite': '3.53.3',
            'sqliteInteractive': '3.53.3',
        })

    def test_application_overlay_does_not_change_the_default_kernel_derivation(self):
        expression = '''let
          flake = builtins.getFlake (toString ./.);
          original = flake.outputs.nixosConfigurations.x86_64-linux-apple-11-1-chatgpt;
          changed = original.extendModules {
            modules = [
              {
                nixpkgs.overlays = [
                  (_final: previous: {
                    hello = previous.hello.overrideAttrs (_old: {
                      pname = "assbox-kernel-cache-regression-probe";
                    });
                  })
                ];
              }
            ];
          };
        in {
          originalKernel = original.config.boot.kernelPackages.kernel.drvPath;
          originalWorkerKernel = original.config.system.build.assboxWorkerImage.guestPolicy.kernelDrv;
          originalWorkerBuilderKernel = original.config.system.build.assboxWorkerImage.guestPolicy.builderKernelDrv;
          originalWorkerImage = original.config.system.build.assboxWorkerImage.drvPath;
          changedKernel = changed.config.boot.kernelPackages.kernel.drvPath;
          changedWorkerKernel = changed.config.system.build.assboxWorkerImage.guestPolicy.kernelDrv;
          changedWorkerBuilderKernel = changed.config.system.build.assboxWorkerImage.guestPolicy.builderKernelDrv;
          changedPackage = changed.pkgs.hello.pname;
        }'''
        result = subprocess.run([
            'nix', 'eval', '--impure', '--json', '--no-update-lock-file',
            '--no-write-lock-file', '--expr', expression,
        ], cwd=ROOT, capture_output=True, text=True, timeout=180)
        self.assertEqual(result.returncode, 0, result.stderr)
        actual = json.loads(result.stdout)
        self.assertEqual(actual['changedPackage'], 'assbox-kernel-cache-regression-probe')
        self.assertEqual(actual['changedKernel'], actual['originalKernel'])
        self.assertEqual(actual['originalWorkerKernel'], actual['originalKernel'])
        self.assertEqual(actual['originalWorkerBuilderKernel'], actual['originalKernel'])
        self.assertEqual(actual['changedWorkerKernel'], actual['changedKernel'])
        self.assertEqual(actual['changedWorkerBuilderKernel'], actual['changedKernel'])
        requirements = subprocess.run([
            'nix-store', '--query', '--requisites', actual['originalWorkerImage'],
        ], cwd=ROOT, capture_output=True, text=True, timeout=60)
        self.assertEqual(requirements.returncode, 0, requirements.stderr)
        kernels = {
            path for path in requirements.stdout.splitlines()
            if re.fullmatch(
                r'/nix/store/[0-9a-z]{32}-linux-[0-9]+(?:\.[0-9]+)+\.drv', path)
        }
        self.assertEqual(kernels, {actual['originalKernel']})


if __name__ == '__main__':
    unittest.main()
