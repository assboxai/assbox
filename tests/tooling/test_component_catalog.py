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
                 substrate=False, instance=None, poison_tailscale=False):
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
                '--arg', 'instance', nix_json(instance or {}),
                '--arg', 'poisonTailscale', 'true' if poison_tailscale else 'false']
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

    def test_deselected_tailscale_is_not_retained_by_serve(self):
        network={'ssh':{'agent':{'enable':True,'keys':['ssh-ed25519 fixture']},
                        'exposure':'lan','lanInterfaces':['enp0s5']}}
        result=self.evaluate({'codex':{'enable':True}},network=network,substrate=True,poison_tailscale=True)
        self.assertFalse(result['failures'])
        self.assertIsNone(result['substrate']['serve']['tailscale'])
        self.assertNotIn('assbox-serve',result['services'].get('timers',{}))
        self.assertNotIn('assbox-serve',result['services'].get('services',{}))

    def test_checkpoint_tracks_custom_provider_homes_and_rejects_traversal(self):
        selected={'happier':{'enable':True},
                  'happier-daemon':{'enable':True,'home':'/home/agent/state/happier'},
                  'hermes':{'enable':True},
                  'hermes-dashboard':{'enable':True,'publicUrl':'https://fixture.example/'},
                  'hermes-gateway':{'home':'/home/agent/state/hermes'}}
        result=self.evaluate(selected,substrate=True)
        self.assertFalse(result['failures'])
        self.assertEqual(result['substrate']['state']['paths'],
                         ['.config/assbox','.happier','state/happier','.hermes','state/hermes'])
        dashboard=result['services']['user']['services']['assbox-hermes-dashboard']
        self.assertEqual(dashboard['environment']['HERMES_HOME'],'/home/agent/state/hermes')
        for home in ['/home/agent/state/../other','/home/agent/state//hermes','/home/agent/.']:
            selected['hermes-gateway']['home']=home
            with self.subTest(home=home):
                self.assertTrue(any('normalized directory' in f
                                    for f in self.evaluate(selected,substrate=True)['failures']))

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
        self.assertEqual(facts['services']['units']['chatgpt-desktop'],['chatgpt-desktop.service'])
        self.assertIn('chatgpt-desktop.service',facts['state']['units'])

    def test_native_lifecycle_uses_the_actual_declared_units(self):
        result=self.evaluate({app:{'enable':True,'allowMutableCode':True}
                              for app in ['chatgpt-desktop','claude-desktop']},presentation='x11',substrate=True)
        for app in ['chatgpt-desktop','claude-desktop']:
            units=result['substrate']['services']['units'][app]
            self.assertEqual(units,[app+'.service'])
            self.assertIn(app,result['services']['user']['services'])
            self.assertIn(app+'.service',result['substrate']['state']['units'])
            self.assertIn('assbox-native-policy launch '+app,
                          result['services']['user']['services'][app]['serviceConfig']['ExecStart'])

    def test_native_autostart_has_only_guarded_launchers(self):
        apps=['chatgpt-desktop','claude-desktop']
        result=self.evaluate({app:{'enable':True,'allowMutableCode':True} for app in apps},
                             presentation='x11',autostart=apps,substrate=True)
        self.assertFalse(result['failures'])
        self.assertEqual(set(result['services']['user']['services']),set(apps))
        for app in apps:
            unit=result['services']['user']['services'][app]
            self.assertEqual(unit['wantedBy'],['graphical-session.target'])
            self.assertIn('assbox-native-policy launch '+app,unit['serviceConfig']['ExecStart'])

    def test_web_kiosk_and_gui_lifecycle_matches_declared_units(self):
        result=self.evaluate({'chromium':{'enable':True}},presentation='x11',autostart=['chromium'],substrate=True,
                             instance={'kiosk':{'webApps':['chatgpt','claude']}})
        self.assertFalse(result['failures'])
        facts=result['substrate']
        self.assertEqual(facts['services']['units']['chromium'],
                         ['assbox-chromium.service','assbox-web-chatgpt.service','assbox-web-claude.service'])
        for site in ['chatgpt','claude']:
            self.assertIn('.local/share/assbox/web-'+site,facts['state']['paths'])
        editor=self.evaluate({'zed':{'enable':True}},presentation='x11',autostart=['zed'],substrate=True)
        self.assertFalse(editor['failures'])
        self.assertEqual(editor['substrate']['services']['units']['zed'],['assbox-zed.service'])
        for configuration in [result,editor]:
            for id, units in configuration['substrate']['services']['units'].items():
                for unit in units:
                    name=unit.removesuffix('.service')
                    self.assertIn(name,configuration['services']['user']['services'])
                    self.assertIn(unit,configuration['substrate']['state']['units'])
                    service=configuration['services']['user']['services'][name]
                    self.assertEqual(service['unitConfig']['ConditionPathExists'],
                                     '!%h/.config/assbox/disabled/'+id)
                    self.assertEqual(service['serviceConfig']['MemoryMax'],'4096M')
                    self.assertEqual(service['serviceConfig']['CPUWeight'],100)

    def test_computer_use_desktop_closure_requires_explicit_selection(self):
        disabled=self.evaluate({},substrate=True)
        self.assertIsNone(disabled['substrate']['computerUse'])
        self.assertNotIn('/nix/store/test-chromium',disabled['packages'])
        browser=self.evaluate({},substrate=True,instance={'computerUse':{'mode':'browser'}})
        self.assertEqual(browser['substrate']['computerUse'],{'modes':['browser','chromium'],'browser':'/nix/store/test-chromium/bin/chromium'})
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

    def test_direct_codex_relay_cannot_compete_with_happier_daemon(self):
        selected={id:{'enable':True} for id in ['codex','codex-relay','happier','happier-daemon']}
        staged=self.evaluate(selected)
        self.assertFalse(staged['failures'])
        self.assertNotIn('assbox-codex-relay',staged['services']['user']['services'])
        selected['codex-relay']['foregroundCommand']=['/nix/store/fixture-codex/bin/codex','remote-control']
        active=self.evaluate(selected)
        self.assertTrue(any('coexistence is not qualified' in f for f in active['failures']))
        selected['happier-daemon']['enable']=False
        separate=self.evaluate(selected)
        self.assertFalse(separate['failures'])
        self.assertIn('assbox-codex-relay',separate['services']['user']['services'])

    def test_hermes_public_origin_rejects_loopback_and_ambiguous_hosts(self):
        good=['https://assbox.example.ts.net/','https://10.0.0.2:8443/dashboard','https://host.example./']
        bad=['https://localhost/','https://LOCALHOST/','https://host.localhost./','https://127.0.0.2/',
             'https://127.1/','https://2130706433/','https://0x7f.0.0.1/','https://0x7f.0x0.0x0.0x1/',
             'https://0.0.0.0/','https://0127.0.0.1/','https://999.0.0.1/','https:///','https://-bad.example/',
             'https://good..example/','https://host.example:0/','https://host.example:65536/',
             'https://host.example:443:4/','https://host.example:0443/','https://user@host.example/',
             'http://host.example/','https://host.example/#fragment']
        for url in good+bad:
            with self.subTest(url=url):
                result=self.evaluate({'hermes':{'enable':True},'hermes-dashboard':{'enable':True,'publicUrl':url}})
                rejected=any('non-loopback HTTPS' in f for f in result['failures'])
                self.assertEqual(rejected,url in bad)

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
