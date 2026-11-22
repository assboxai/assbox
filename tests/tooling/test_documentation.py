# SPDX-License-Identifier: GPL-3.0-or-later
"""Validate local documentation navigation without fetching external services."""
from __future__ import annotations
from datetime import date
import json
import re
import subprocess
import sys
import unittest
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
from product_docs import CONTROLLER_ROUTE_CASES, computer_use_status, controller_route_status


def heading_ids(text: str) -> set[str]:
    """GitHub-style anchors for the project's ordinary ATX Markdown headings."""
    identifiers, counts = set(), {}
    fenced = False
    for line in text.splitlines():
        if line.lstrip().startswith(("```", "~~~")):
            fenced = not fenced
        if fenced:
            continue
        identifiers.update(re.findall(r'<a\s+(?:id|name)=["\']([^"\']+)["\']', line))
        heading = re.match(r"^#{1,6}\s+(.*?)\s*#*\s*$", line)
        if heading is None:
            continue
        slug = re.sub(r"[^\w\- ]", "", heading[1].lower()).replace(" ", "-")
        count = counts.get(slug, 0)
        counts[slug] = count + 1
        identifiers.add(slug if count == 0 else f"{slug}-{count}")
    return identifiers


class DocumentationTests(unittest.TestCase):
    def test_product_tables_match_reviewed_catalog_and_evidence(self):
        subprocess.run([sys.executable, 'scripts/product_docs.py', '--check'], cwd=ROOT, check=True)

    def test_controller_route_pass_requires_its_own_acceptance_receipts(self):
        data = json.loads((ROOT / 'qualification/codex-controller-routes.json').read_text())
        acceptance = {row['id']: row for row in json.loads((ROOT / 'qualification/acceptance.json').read_text())}
        routes = {row['id']: row for row in data['routes']}
        mac = routes['macos-desktop-ssh']
        linux = routes['linux-desktop-worker-ssh']
        mobile = routes['mobile-through-linux-worker']
        self.assertEqual(controller_route_status({**mobile, 'evidence': None}, acceptance), 'not run')
        with self.assertRaisesRegex(ValueError, 'exact controller route'):
            controller_route_status({**linux, 'evidence': 'S19'}, acceptance)

        source = '1' * 40
        checks = {case: str(index) * 64 for index, case in enumerate(CONTROLLER_ROUTE_CASES[mac['id']], 2)}
        receipt = {'route': mac['id'], 'source': source, 'checks': checks}
        for case, digest in checks.items():
            acceptance[case].update(status='passed', evidence={'route': mac['id'], 'source': source, 'sha256': digest})
        self.assertEqual(controller_route_status({**mac, 'evidence': receipt}, acceptance), 'passed')
        for route in (linux, mobile, routes['mobile-through-macos-ssh'], routes['direct-cli-relay']):
            with self.subTest(route=route['id']), self.assertRaisesRegex(ValueError, 'exact controller route'):
                controller_route_status({**route, 'evidence': receipt}, acceptance)

        digest = checks['A099']
        linux_receipt = {'route': linux['id'], 'source': source, 'checks': {'A059': digest}}
        acceptance['A059'].update(status='passed', evidence=acceptance['A099']['evidence'])
        with self.assertRaisesRegex(ValueError, 'own reviewed A059'):
            controller_route_status({**linux, 'evidence': linux_receipt}, acceptance)
        acceptance['A059']['evidence'] = 'S53'
        with self.assertRaisesRegex(ValueError, 'own reviewed A059'):
            controller_route_status({**linux, 'evidence': linux_receipt}, acceptance)

    def test_computer_use_receipt_matches_the_exact_build_and_surface(self):
        data = json.loads((ROOT / 'qualification/linux-computer-use.json').read_text())
        row = next(row for row in data['rows'] if row['id'] == 'CU07')
        reviewed = date.fromisoformat(data['reviewed_local_date'])
        lock = '1' * 64
        scope = {'architecture': 'x86_64-linux', 'surface': 'desktop', 'authentication': 'fixture account',
                 'package_sha256': '2' * 64, 'helper_sha256': {'display': '3' * 64},
                 'compiled_features': ['x11 capture', 'x11 input'], 'display_backend': 'x11'}
        identity = {'row': row['id'], 'product_path': row['path'], 'source': '4' * 40, 'lock_sha256': lock,
                    'observed_on': row['reviewed_local_date'], 'scope': scope}
        checks = {case: '5' * 64 for case in row['requirements'] if case != 'A114'}
        acceptance = {case: {'status': 'passed',
                             'evidence': {'linux_computer_use': {row['id']: {**identity, 'sha256': digest}}}}
                      for case, digest in checks.items()}
        receipt = {**identity, 'checks': checks}
        passed = {**row, 'assbox_status': 'passed', 'evidence': receipt}
        self.assertEqual(computer_use_status(row, acceptance, lock, reviewed), 'not run')
        self.assertEqual(computer_use_status(passed, acceptance, lock, reviewed), 'passed (desktop, x86_64-linux, x11)')

        with self.assertRaisesRegex(ValueError, 'requires null evidence'):
            computer_use_status({**row, 'evidence': receipt}, acceptance, lock, reviewed)
        for unreviewed in (None, row['sources'][0]):
            with self.subTest(unreviewed=unreviewed), self.assertRaisesRegex(ValueError, 'product path and lock'):
                computer_use_status({**passed, 'evidence': unreviewed}, acceptance, lock, reviewed)
        with self.assertRaisesRegex(ValueError, 'product path and lock'):
            computer_use_status(passed, acceptance, '6' * 64, reviewed)
        with self.assertRaisesRegex(ValueError, 'product path and lock'):
            computer_use_status({**passed, 'path': 'different OMP product path'}, acceptance, lock, reviewed)
        with self.assertRaisesRegex(ValueError, 'reviewed date range'):
            computer_use_status({**passed, 'evidence': {**receipt, 'observed_on': '2026-01-01'}},
                                acceptance, lock, reviewed)
        with self.assertRaisesRegex(ValueError, 'own runtime acceptance checks'):
            computer_use_status({**passed, 'evidence': {**receipt, 'checks': {'A114': '5' * 64}}},
                                acceptance, lock, reviewed)

        for field, value in (
            ('package_sha256', '7' * 64),
            ('compiled_features', []),
            ('display_backend', 'wayland'),
            ('surface', 'browser'),
            ('architecture', 'aarch64-linux'),
            ('authentication', 'other account scope'),
            ('helper_sha256', {'display': '8' * 64}),
        ):
            other = {**passed, 'evidence': {**receipt, 'scope': {**scope, field: value}}}
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'matching reviewed'):
                computer_use_status(other, acceptance, lock, reviewed)

    def test_relative_files_and_heading_links_resolve(self):
        checked = 0
        for source in ROOT.rglob("*.md"):
            if any(part in {".git", "target", "node_modules", "reports", ".cache", ".chainman"} for part in source.relative_to(ROOT).parts):
                continue
            for target in re.findall(r"\[[^\]\n]+\]\(([^)\s]+)\)", source.read_text()):
                link = urlsplit(target)
                if link.scheme or link.netloc:
                    continue
                with self.subTest(source=str(source.relative_to(ROOT)), target=target):
                    path = (source.parent / unquote(link.path)).resolve() if link.path else source.resolve()
                    self.assertTrue(path.is_relative_to(ROOT.resolve()), "link escapes repository")
                    self.assertTrue(path.exists(), "missing local target")
                    if link.fragment and path.suffix == ".md":
                        self.assertIn(unquote(link.fragment), heading_ids(path.read_text()), "missing heading")
                    checked += 1
        self.assertGreater(checked, 0, "documentation discovery must not pass vacuously")


if __name__ == "__main__":
    unittest.main()
