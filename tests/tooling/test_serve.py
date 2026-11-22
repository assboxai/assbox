# SPDX-License-Identifier: GPL-3.0-or-later
"""Serve contract checks without enrollment, sockets or privileged mutation."""
import importlib.util
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('assbox_serve',ROOT/'scripts/access/serve.py')
serve=importlib.util.module_from_spec(spec)
spec.loader.exec_module(serve)

class ServeTests(unittest.TestCase):
    def test_missing_backend_refuses_before_external_mutation(self):
        with patch.object(serve.subprocess,'run',side_effect=AssertionError('must not invoke control')):
            with self.assertRaisesRegex(serve.Refusal,'before deselecting'):
                serve.command(None,'serve','status','--json')

    def test_retargeting_checks_live_ownership_after_withdrawal(self):
        host = 'assbox.example.test'
        path = '/dashboard'
        current = 'http://127.0.0.1:9119'
        desired = 'http://127.0.0.1:9120'
        replaced = 'http://127.0.0.1:9900'
        config = {'tailscale': 'fixture', 'mappings': [
            {'publicUrl': 'https://' + host + path, 'port': 9120, 'component': 'hermes-dashboard'},
        ]}
        initial_owned = serve.paths({**config, 'mappings': [{**config['mappings'][0], 'port': 9119}]})
        for owner_takes_path in (False, True):
            with self.subTest(owner_takes_path=owner_takes_path), tempfile.TemporaryDirectory() as directory:
                state = Path(directory) / 'state'
                state.mkdir(mode=0o700)
                record = state / 'owned.json'
                unrelated = {'Proxy': 'http://127.0.0.1:9901'}
                routes = {path: {'Proxy': current}, '/manual': unrelated}
                lstat = Path.lstat

                def root_owned(file):
                    info = lstat(file)
                    if file in (state, record):
                        return SimpleNamespace(st_mode=info.st_mode, st_uid=0, st_size=info.st_size)
                    return info

                def control(_binary, *args):
                    if args == ('serve', 'status', '--json'):
                        return json.dumps({'Web': {host + ':443': {'Handlers': routes}}})
                    if args == ('status', '--json'):
                        return json.dumps({'BackendState': 'Running', 'Self': {'DNSName': host + '.'}})
                    if args == ('serve', '--https=443', '--set-path=' + path, 'off'):
                        del routes[path]
                        if owner_takes_path:
                            routes[path] = {'Proxy': replaced}
                        return ''
                    self.assertEqual(args, ('serve', '--bg', '--https=443', '--set-path=' + path, desired))
                    self.assertNotIn(path, routes)
                    routes[path] = {'Proxy': desired}
                    return ''

                with (patch.object(serve, 'STATE', state), patch.object(serve.os, 'geteuid', return_value=0),
                      patch.object(Path, 'lstat', root_owned), patch.object(serve, 'command', side_effect=control)):
                    serve.persist(record, initial_owned)
                    if owner_takes_path:
                        with self.assertRaisesRegex(serve.Refusal, 'owner-managed'):
                            serve.run(config)
                    else:
                        serve.run(config)

                self.assertEqual(json.loads(record.read_text()), {} if owner_takes_path else serve.paths(config))
                self.assertEqual(routes, {path: {'Proxy': replaced if owner_takes_path else desired},
                                          '/manual': unrelated})

if __name__=='__main__':unittest.main()
