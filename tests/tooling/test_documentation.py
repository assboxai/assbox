# SPDX-License-Identifier: GPL-3.0-or-later
"""Validate local documentation navigation without fetching external services."""
from __future__ import annotations
import json
import re
import subprocess
import sys
import unittest
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
from product_docs import CONTROLLER_ROUTE_CASES, controller_route_status


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
