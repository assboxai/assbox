# SPDX-License-Identifier: GPL-3.0-or-later
"""Execute release graph/archive/evidence code with synthetic, non-release fixtures."""
from __future__ import annotations
import copy
import io
import json
from pathlib import Path
import sys
import tarfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
import release_data as data


def lock(letter='a'):
    nodes = {'root': {'inputs': {name: name for name in data.INPUTS}}}
    for name in data.INPUTS:
        nodes[name] = {'locked': {'type': 'github', 'rev': letter * 40,
                                  'narHash': 'sha256-' + 'A' * 43 + '='},
                       'original': {'type': 'github', 'owner': 'fixture', 'repo': name}}
    # Application dependencies include both a root-relative follows path and an
    # independently pinned helper. A fallback must retain that helper as well.
    for app in data.APPLICATIONS:
        name = app + '-packages'
        nodes[name]['inputs'] = {'nixpkgs': ['nixpkgs'], 'helper': 'helper'}
    nodes['helper'] = {'locked': {'type': 'github', 'rev': letter * 40, 'narHash': 'sha256-' + 'B' * 43 + '='}}
    return {'version': 7, 'root': 'root', 'nodes': nodes}


def core():
    return {'flake.nix': (0o644, b'{ inputs = {}; outputs = _: {}; }\n'),
            'flake.lock': (0o644, data.json_bytes(lock())),
            'scripts/example': (0o755, b'#!/bin/sh\nexit 0\n')}


def manifest(now=1000, old=None):
    return data.make_manifest('a'*40, '0.1.0', now, old, '1'*64, 'sha256-'+'A'*43+'=', '2'*64, [])


class ReleaseDataTests(unittest.TestCase):
    def test_decode_rejects_duplicate_keys_and_nonfinite_numbers(self):
        for raw in [b'{"id":1,"id":2}', b'{"x":NaN}', b'{"x":Infinity}']:
            with self.assertRaises(ValueError): data.decode(raw)

    def test_fallback_copies_complete_subtree_and_preserves_follows(self):
        old, new = lock('a'), lock('b')
        result = data.compose_lock(old, new, {'nixpkgs', 'opencode-packages'})
        roots = result['nodes']['root']['inputs']
        for name in data.INPUTS:
            node = result['nodes'][roots[name]]
            expected = ('b' if name in {'nixpkgs', 'opencode-packages'} else 'a') * 40
            self.assertEqual(node['locked']['rev'], expected)
            if 'inputs' in node:
                self.assertEqual(node['inputs']['nixpkgs'], ['nixpkgs'])
                self.assertEqual(result['nodes'][node['inputs']['helper']]['locked']['rev'], expected)
        self.assertNotEqual(result['nodes'][roots['chatgpt-packages']]['inputs']['helper'],
                            result['nodes'][roots['openclaw-packages']]['inputs']['helper'])
        self.assertEqual(old, lock('a'))
        self.assertEqual(new, lock('b'))

    def test_namespacing_is_idempotent_not_unbounded_daily_growth(self):
        result = data.compose_lock(lock(), lock(), set(data.INPUTS))
        for _ in range(30):
            self.assertEqual(data.compose_lock(result, lock('c'), set()), result)
            result = data.compose_lock(result, result, set(data.INPUTS))
        self.assertLess(len(data.json_bytes(result)), 10000)

    def test_graph_identity_allows_renaming_sharing_and_equivalent_follows(self):
        original = lock()
        renamed = data.compose_lock(original, original, set())
        data.require_same_inputs(original, renamed)
        for node in renamed['nodes'].values():
            if node.get('inputs', {}).get('nixpkgs') == ['nixpkgs']:
                node['inputs']['nixpkgs'] = renamed['nodes']['root']['inputs']['nixpkgs']
        data.require_same_inputs(original, renamed)

    def test_graph_identity_rejects_dependency_and_edge_changes(self):
        original = lock()
        for change in ['revision', 'hash', 'original', 'added', 'removed', 'redirected']:
            changed = copy.deepcopy(original)
            helper = changed['nodes']['helper']
            app = changed['nodes']['opencode-packages']
            if change == 'revision': helper['locked']['rev'] = 'b' * 40
            elif change == 'hash': helper['locked']['narHash'] = 'sha256-' + 'C' * 43 + '='
            elif change == 'original': app['original']['repo'] = 'different'
            elif change == 'added': app['inputs']['extra'] = 'helper'
            elif change == 'removed': del app['inputs']['helper']
            else: app['inputs']['helper'] = 'nixpkgs'
            with self.assertRaisesRegex(ValueError, 'changed a selected dependency', msg=change):
                data.require_same_inputs(original, changed)

    def test_graph_identity_checks_edges_in_recursive_graphs(self):
        original = lock()
        original['nodes']['helper']['inputs'] = {'cycle': 'helper'}
        data.require_same_inputs(original, copy.deepcopy(original))
        changed = copy.deepcopy(original)
        changed['nodes']['helper']['inputs']['cycle'] = 'nixpkgs'
        with self.assertRaises(ValueError): data.require_same_inputs(original, changed)

    def test_invalid_graphs_fail_closed(self):
        for name in ['path', 'parent', 'dangling', 'follows-cycle', 'missing-input', 'new-input']:
            value = lock()
            if name == 'path': value['nodes']['helper']['locked']['type'] = 'path'
            elif name == 'parent': value['nodes']['helper']['parent'] = []
            elif name == 'dangling': value['nodes']['opencode-packages']['inputs']['helper'] = 'absent'
            elif name == 'follows-cycle': value['nodes']['root']['inputs']['nixpkgs'] = ['nixpkgs']
            elif name == 'missing-input': del value['nodes']['root']['inputs']['nixpkgs']
            else: value['nodes']['root']['inputs']['extra'] = 'helper'
            with self.assertRaises(ValueError, msg=name): data.validate_lock(value)

    def test_every_application_requires_both_native_reports(self):
        reports = [{'application': app, 'system': system, 'planSha256': 'd'*64, 'passed': True, 'exitCode': 0}
                   for app in data.APPLICATIONS for system in data.SYSTEMS]
        self.assertEqual(data.select_inputs(reports, 'd'*64), set(data.INPUTS))
        reports[0].update(passed=False, exitCode=1)
        self.assertEqual(data.select_inputs(reports, 'd'*64), set(data.INPUTS) - {data.APPLICATIONS[0] + '-packages'})
        for bad in [reports[:-1], reports + [reports[0]], [dict(r, planSha256='wrong') for r in reports],
                    [dict(r, passed=False, exitCode=0) for r in reports]]:
            with self.assertRaises(ValueError): data.select_inputs(bad, 'd'*64)

    def test_archive_is_deterministic_and_only_two_source_differences_allowed(self):
        original = core(); new_lock = data.json_bytes(lock('b')); context = {'coreCommit': 'a'*40}
        files = data.source_files(original, new_lock, context)
        archive = data.pack_source(files)
        self.assertEqual(archive, data.pack_source(dict(reversed(list(files.items())))))
        self.assertEqual(data.validate_source(archive, original, new_lock, context), files)
        for change in ['core', 'executable', 'unexpected', 'missing']:
            mutated = dict(files)
            if change == 'core': mutated['flake.nix'] = (0o644, b'changed')
            elif change == 'executable': mutated['scripts/example'] = (0o644, files['scripts/example'][1])
            elif change == 'unexpected': mutated['unexpected'] = (0o644, b'')
            else: del mutated['scripts/example']
            with self.assertRaises(ValueError, msg=change):
                data.validate_source(data.pack_source(mutated), original, new_lock, context)

    def test_archive_inspection_never_extracts_links_or_traversal(self):
        for name, kind in [('assbox/../evil', tarfile.REGTYPE), ('assbox/a', tarfile.SYMTYPE), ('/assbox/a', tarfile.REGTYPE)]:
            out = io.BytesIO()
            with tarfile.open(fileobj=out, mode='w:gz') as tar:
                entry = tarfile.TarInfo(name); entry.type = kind; entry.mode = 0o644
                entry.linkname = '/etc/passwd' if kind == tarfile.SYMTYPE else ''
                tar.addfile(entry)
            with self.assertRaises(ValueError): data.unpack_source(out.getvalue())

    def test_duplicate_archive_members_are_refused(self):
        out = io.BytesIO()
        with tarfile.open(fileobj=out, mode='w:gz') as tar:
            for _ in range(2):
                entry = tarfile.TarInfo('assbox/a'); entry.mode = 0o644; tar.addfile(entry)
        with self.assertRaises(ValueError): data.unpack_source(out.getvalue())

    def test_heartbeat_refreshes_authentication_without_changing_source(self):
        first = manifest()
        second = manifest(1001, first)
        self.assertFalse(data.needs_release(first, second, 1001))
        renewed = manifest(1000 + 259200, first)
        self.assertTrue(data.needs_release(first, renewed, renewed['issuedAt']))
        self.assertEqual(first['sourceSha256'], renewed['sourceSha256'])
        self.assertEqual(renewed['expiresAt'] - renewed['issuedAt'], 604800)
        with self.assertRaises(ValueError): manifest(999, first)

    def test_metadata_changes_and_held_pins_are_explicit(self):
        first = manifest(); second = manifest(1001, first)
        for key in ['coreCommit', 'sourceNarHash', 'lockSha256']:
            candidate = dict(second, **{key: 'changed'})
            self.assertTrue(data.needs_release(first, candidate, 1001))
        for held in [['nixpkgs'], ['opencode-packages', 'opencode-packages'], ['unknown']]:
            with self.assertRaises(ValueError):
                data.make_manifest('a'*40, '0.1.0', 1000, None, '1'*64, 'sha256-'+'A'*43+'=', '2'*64, held)


if __name__ == '__main__': unittest.main()
