# SPDX-License-Identifier: GPL-3.0-or-later
"""Validate local documentation navigation without fetching external services."""
from __future__ import annotations
import re
import subprocess
import sys
import unittest
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[2]


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
