# SPDX-License-Identifier: GPL-3.0-or-later
"""Exercise selection modules with Nix's module library, without NixOS builds."""
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
import component_catalog as catalog
import component_families
import release_data


class ComponentCatalogTests(unittest.TestCase):
    def test_generated_metadata_and_release_families_match(self):
        subprocess.run([sys.executable, 'scripts/component_catalog.py', '--check'], cwd=ROOT, check=True)
        rows = catalog.read_catalog()
        self.assertEqual(len(rows), 33)
        expected = tuple(sorted({r['family'] for r in rows} - {'nixpkgs'}))
        self.assertEqual(component_families.FAMILIES, expected)
        release_data.validate_lock(json.loads((ROOT / 'flake.lock').read_text()))
        self.assertFalse({'happy','happy-remote','gemini-cli','cowork-dispatch'} & {r['id'] for r in rows})

    def test_release_workflow_requires_each_family_on_both_architectures(self):
        document = yaml.safe_load((ROOT / '.github/workflows/release.yml').read_text())
        rows = document['jobs']['probe']['strategy']['matrix']['include']
        actual = [(r['application'], r['system']) for r in rows]
        expected = [(family, system) for family in component_families.FAMILIES for system in release_data.SYSTEMS]
        self.assertEqual(sorted(actual), sorted(expected))

    @classmethod
    def setUpClass(cls):
        path = os.environ.get('ASSBOX_NIX_LIB')
        if not path:
            # The Nix dev shell supplies this in normal CI; local static runs may
            # use an already cached nixpkgs, never download or evaluate a flake.
            candidates = [p for p in Path('/nix/store').glob('*-source/lib')
                          if (p / 'modules.nix').is_file() and (p / 'default.nix').is_file()]
            path = str(sorted(candidates)[0]) if candidates else None
        cls.lib = path

    def evaluate(self, selected, *, presentation='headless', network=None, autostart=None,
                 accept_unfree=True, unfree_packages=None, package_revision='',
                 substrate=False, instance=None):
        if not self.lib:
            self.skipTest('Nix module library unavailable; run in the development shell')
        def nix_json(value):
            return 'builtins.fromJSON ' + json.dumps(json.dumps(value))
        args = ['nix-instantiate', '--eval', '--strict', '--json', 'tests/nix/component-eval.nix',
                '--arg', 'libPath', self.lib, '--arg', 'selection', nix_json(selected),
                '--argstr', 'presentation', presentation, '--arg', 'network', nix_json(network or {}),
                '--arg', 'autostart', nix_json(autostart or []),
                '--arg', 'acceptUnfree', nix_json(accept_unfree),
                '--arg', 'unfreePackages', nix_json(unfree_packages or []),
                '--argstr', 'packageRevision', package_revision,
                '--arg', 'substrate', 'true' if substrate else 'false',
                '--arg', 'instance', nix_json(instance or {})]
        result = subprocess.run(args, cwd=ROOT, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_standalone_substrate_scopes_services_resources_and_state(self):
        result=self.evaluate({'happier':{'enable':True},'happier-daemon':{'enable':True}},substrate=True)
        self.assertFalse(result['failures'])
        facts=result['substrate']
        self.assertFalse(facts['controller']['active'])
        self.assertIn('assbox-execution',facts['nft'])
        self.assertEqual(facts['services']['units'],{'happier-daemon':['assbox-happier-daemon.service']})
        self.assertIn('.happier',facts['state']['paths'])
        self.assertEqual(result['services']['user']['services']['assbox-happier-daemon']['serviceConfig']['MemoryMax'],'4096M')

    def test_native_none_is_staged_without_a_worker_or_execution_firewall(self):
        result=self.evaluate({'chatgpt-desktop':{'enable':True,'allowMutableCode':True}},
                             presentation='x11',substrate=True)
        self.assertFalse(result['failures'])
        facts=result['substrate']
        self.assertTrue(facts['controller']['active'])
        self.assertEqual(facts['native']['apps']['chatgpt-desktop']['mode'],'none')
        self.assertIsNone(facts['native']['apps']['chatgpt-desktop']['contract'])
        self.assertEqual(facts['nft'],{})
        self.assertEqual(result['services']['user']['services']['chatgpt-desktop']['serviceConfig']['MemoryMax'],'4096M')

    def test_computer_use_desktop_closure_requires_explicit_selection(self):
        disabled=self.evaluate({},substrate=True)
        self.assertIsNone(disabled['substrate']['computerUse'])
        self.assertNotIn('/nix/store/test-chromium',disabled['packages'])
        browser=self.evaluate({},substrate=True,instance={'computerUse':{'mode':'browser'}})
        self.assertEqual(browser['substrate']['computerUse'],{'modes':['browser']})
        self.assertNotIn('/nix/store/test-xorgserver',browser['packages'])
        desktop=self.evaluate({},substrate=True,instance={'computerUse':{'mode':'virtual-desktop'}})
        self.assertIn('display',desktop['substrate']['computerUse']['modes'])
        self.assertIn('/nix/store/test-xorgserver',desktop['packages'])

    def test_substrate_rejects_controller_execution_and_overlapping_restore_paths(self):
        result=self.evaluate({'chatgpt-desktop':{'enable':True,'allowMutableCode':True},'codex':{'enable':True}},
                             presentation='x11',substrate=True)
        self.assertTrue(any('sensitive controller' in f for f in result['failures']))
        result=self.evaluate({},substrate=True,instance={'state':{'additionalPaths':['.config']}})
        self.assertTrue(any('must not overlap' in f for f in result['failures']))

    def test_empty_selection_has_no_packages_or_remote_units(self):
        result = self.evaluate({})
        self.assertEqual(result['selected'], [])
        self.assertEqual(result['packages'], [])
        self.assertEqual(result['runtimeDependencies'], [])
        self.assertFalse(result['sshEnabled'])
        self.assertEqual(result['services']['user']['services'], {})
        self.assertTrue(all(isinstance(paths, list) and paths for paths in result['identities'].values()))

    def test_standalone_browser_and_workload_ssh_are_independent_of_editors(self):
        network = {'ssh': {'agent': {'enable': True, 'keys': ['ssh-ed25519 fixture']},
                           'exposure': 'lan', 'lanInterfaces': ['enp0s5']}}
        for presentation in ['x11', 'wayland']:
            with self.subTest(presentation=presentation):
                result = self.evaluate({'chromium': {'enable': True}, 'codex': {'enable': True}},
                                       presentation=presentation, network=network, autostart=['chromium'])
                self.assertFalse(result['failures'])
                self.assertTrue(result['sshEnabled'])
                self.assertEqual(result['selected'], ['chromium', 'codex'])
                self.assertNotIn('nix-ld', result['programs'])
                unit = result['services']['user']['services']['assbox-chromium']
                self.assertIn('/bin/chromium ', unit['serviceConfig']['ExecStart'])
                self.assertEqual(unit['partOf'], ['graphical-session.target'])
        self.assertTrue(self.evaluate({'chromium': {'enable': True}})['failures'])
        self.assertTrue(self.evaluate({}, presentation='x11', autostart=['chromium'])['failures'])
        result = self.evaluate({'codex': {'enable': True}}, network=network)
        self.assertFalse(result['failures'])
        self.assertTrue(result['sshEnabled'])
        self.assertNotIn('/nix/store/test-chromium', result['packages'])

    def test_closure_identities_preserve_overlays_without_granting_install_consent(self):
        if not self.lib:
            self.skipTest('Nix module library unavailable; run in the development shell')
        result = subprocess.run(
            ['nix-instantiate', '--eval', '--strict', '--json',
             'tests/nix/component-closure-eval.nix', '--arg', 'libPath', self.lib],
            cwd=ROOT, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIs(json.loads(result.stdout), True)

    def test_external_package_license_cannot_bypass_machine_consent(self):
        selection = {'codex': {'enable': True}}
        self.assertFalse(self.evaluate(selection, accept_unfree=False)['failures'])
        result = self.evaluate(selection, accept_unfree=False, unfree_packages=['codex'])
        self.assertTrue(any('package license' in failure for failure in result['failures']))

    def test_lan_source_cidrs_are_validated_before_firewall_generation(self):
        network = {'ssh': {'agent': {'enable': True, 'keys': ['ssh-ed25519 fixture']},
                           'exposure': 'lan', 'lanInterfaces': ['eth0']}}
        for cidr in ['192.0.2.0/24', '0.0.0.0/0', '2001:db8::/32', '::1/128']:
            network['ssh']['lanSourceCidrs'] = [cidr]
            with self.subTest(cidr=cidr):
                self.assertFalse(self.evaluate({}, network=network)['failures'])
        for cidr in ['999.0.0.0/8', '192.0.2.1/33', ':1::2/64', '::1:/64', '1::2::3/64', '::/129']:
            network['ssh']['lanSourceCidrs'] = [cidr]
            with self.subTest(cidr=cidr):
                self.assertTrue(any('CIDRs' in failure for failure in self.evaluate({}, network=network)['failures']))

    def test_dependency_and_mutable_code_consent_are_explicit(self):
        self.assertTrue(self.evaluate({'cursor-worker': {'enable': True}})['failures'])
        self.assertTrue(self.evaluate({'chatgpt-desktop': {'enable': True}}, presentation='x11')['failures'])
        result = self.evaluate({'cursor-agent': {'enable': True}, 'cursor-worker': {'enable': True}})
        self.assertFalse(result['failures'])
        unit = result['services']['user']['services']['assbox-cursor-worker']
        self.assertIn('/bin/cursor-agent', unit['serviceConfig']['ExecStart'])
        self.assertTrue(any('onboarded/cursor-worker-' in p for p in unit['unitConfig']['ConditionPathExists']))
        self.assertEqual(unit['unitConfig']['StartLimitIntervalSec'], 0)
        self.assertEqual(unit['serviceConfig']['Restart'], 'on-failure')
        self.assertEqual(unit['serviceConfig']['RestartSteps'], 5)
        self.assertEqual(unit['serviceConfig']['RestartMaxDelaySec'], 300)
        self.assertEqual(unit['serviceConfig']['StandardOutput'], 'null')

    def test_every_available_runtime_alone_has_no_implicit_runtime_or_service(self):
        for row in catalog.read_catalog():
            if not row['package'] or row['blocked']:
                continue
            with self.subTest(id=row['id']):
                result = self.evaluate({row['id']: {'enable': True, 'allowMutableCode': True}},
                                       presentation=row['presentations'][0])
                self.assertEqual(result['selected'], [row['id']])
                self.assertFalse(result['failures'])
                self.assertEqual(result['services']['user']['services'], {})

    def test_chatgpt_remote_requires_desktop_and_x11_not_an_obsolete_os_blocker(self):
        rows = {row['id']: row for row in catalog.read_catalog()}
        self.assertEqual(rows['chatgpt-remote']['blocked'], '')
        self.assertEqual(rows['chatgpt-remote']['dependencies'], ['chatgpt-desktop'])
        selected = {name: {'enable': True, 'allowMutableCode': True}
                    for name in ('chatgpt-desktop', 'chatgpt-remote')}
        self.assertFalse(self.evaluate(selected, presentation='x11')['failures'])
        self.assertTrue(self.evaluate({'chatgpt-remote': {'enable': True}}, presentation='x11')['failures'])
        self.assertTrue(self.evaluate(selected, presentation='headless')['failures'])

    def test_experimental_service_is_staged_until_an_immutable_runtime_is_selected(self):
        result = self.evaluate({'antigravity-cli': {'enable': True, 'allowMutableCode': True}, 'antigravity-remote': {'enable': True, 'allowMutableCode': True}})
        self.assertFalse(result['failures'])
        self.assertNotIn('assbox-antigravity-remote',result['services']['user']['services'])
        self.assertIn('assbox/onboarding/antigravity-remote', result['scripts'])

    def test_computer_use_cannot_inherit_a_physical_display(self):
        selected = {'cursor-worker': {'enable': True, 'computerUse': {'enable': True}}, 'cursor-agent': {'enable': True}}
        result = self.evaluate(selected,presentation='x11')
        self.assertTrue(any('private virtual desktop' in failure for failure in result['failures']))
        unit=result['services']['user']['services']['assbox-cursor-worker']
        self.assertIn('DISPLAY',unit['serviceConfig']['UnsetEnvironment'])
        self.assertNotIn('--display :0',unit['serviceConfig']['ExecStart'])

    def test_remote_recipes_merge_common_and_specific_options(self):
        cases = {
            'claude-code-remote': ['claude-code'],
            'openclaw-node': ['openclaw'],
            'happier-daemon': ['happier'],
            'vscode-tunnel': ['vscode-cli'],
        }
        for id, dependencies in cases.items():
            with self.subTest(id=id):
                selection = {key: {'enable': True, 'allowMutableCode': True} for key in [id, *dependencies]}
                result = self.evaluate(selection)
                self.assertFalse(result['failures'])
                unit = result['services']['user']['services']['assbox-' + id]
                self.assertEqual(unit['serviceConfig']['WorkingDirectory'], '/home/agent/projects')
                self.assertEqual(unit['unitConfig']['ConditionUser'], 'agent')
                self.assertTrue(any('onboarded/' + id in p for p in unit['unitConfig']['ConditionPathExists']))

    def test_editor_hosts_require_agent_access_and_consent(self):
        selected = {'zed-remote-host': {'enable': True, 'allowMutableCode': True}}
        self.assertTrue(self.evaluate(selected)['failures'])
        network = {'tailscale': {'enable': True}, 'ssh': {'agent': {'enable': True, 'keys': ['ssh-ed25519 fixture']}}}
        self.assertFalse(self.evaluate(selected, network=network)['failures'])
        network['tailscale']['enable'] = False
        self.assertTrue(self.evaluate(selected, network=network)['failures'])

    def test_editor_helper_loader_is_available_for_each_independent_selection(self):
        network = {'tailscale': {'enable': True}, 'ssh': {'agent': {'enable': True, 'keys': ['ssh-ed25519 fixture']}}}
        for id in ['zed', 'vscode', 'zed-remote-host', 'vscode-remote-host', 'vscode-tunnel']:
            with self.subTest(id=id):
                selection = {id: {'enable': True, 'allowMutableCode': True}}
                if id == 'vscode-tunnel':
                    selection['vscode-cli'] = {'enable': True}
                result = self.evaluate(selection, presentation='x11' if id in ['zed', 'vscode'] else 'headless', network=network)
                self.assertFalse(result['failures'])
                loader = result['programs']['nix-ld']
                self.assertTrue(loader['enable'])
                self.assertEqual(set(loader['libraries']),
                                 {'/nix/store/test-' + name for name in ['cc', 'zlib', 'openssl', 'curl']})
        for selection in [{}, {'vim': {'enable': True}}, {'vscode-cli': {'enable': True}}]:
            self.assertNotIn('nix-ld', self.evaluate(selection)['programs'])

    def test_desktop_account_login_has_a_browser_without_another_agent(self):
        for id in ['zed', 'vscode', 'chatgpt-desktop', 'claude-desktop']:
            with self.subTest(id=id):
                result = self.evaluate({id: {'enable': True, 'allowMutableCode': True}}, presentation='x11')
                self.assertFalse(result['failures'])
                self.assertEqual(result['selected'], [id])
                self.assertIn('/nix/store/test-chromium', result['packages'])
                self.assertEqual(result['runtimeDependencies'], ['chromium'])
                self.assertIn('/nix/store/test-xdg-utils', result['packages'])
                self.assertEqual(result['xdg']['mime']['defaultApplications'], {
                    'x-scheme-handler/http': 'chromium-browser.desktop',
                    'x-scheme-handler/https': 'chromium-browser.desktop',
                })
        for id in [None, 'vim', 'emacs', 'opencode', 'zed-remote-host', 'vscode-remote-host', 'vscode-cli']:
            result = self.evaluate({id: {'enable': True}} if id else {}, presentation='x11')
            self.assertNotIn('/nix/store/test-chromium', result['packages'])
            self.assertEqual(result['runtimeDependencies'], [])
            self.assertEqual(result['xdg']['mime'].get('defaultApplications', {}), {})

    def test_openclaw_browser_dependency_requires_dashboard_autostart(self):
        selected = {id: {'enable': True} for id in ['openclaw', 'openclaw-gateway']}
        for autostart in ([], ['openclaw-dashboard']):
            result = self.evaluate(selected, presentation='x11', autostart=autostart)
            self.assertFalse(result['failures'])
            self.assertEqual(result['runtimeDependencies'], ['chromium'] if autostart else [])
