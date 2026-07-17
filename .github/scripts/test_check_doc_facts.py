"""Tests for the Layer-2 doc facts checker (ADR-0011)."""
import tempfile
import unittest
from pathlib import Path

import check_doc_facts as mod


class ParsingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def write(self, name, text):
        p = self.dir / name
        p.write_text(text, encoding="utf-8")
        return p

    def test_status_marker_parsed(self):
        p = self.write("a.md", "<!-- doc-status: living -->\n# A\n")
        self.assertEqual(mod.doc_status(p), "living")

    def test_status_must_be_in_first_ten_lines(self):
        p = self.write("a.md", ("x\n" * 12) + "<!-- doc-status: living -->\n")
        self.assertIsNone(mod.doc_status(p))

    def test_fact_double_quoted_cmd(self):
        p = self.write("a.md",
            '<!-- fact: tier=pr cmd="yq \'.services | length\' render.yaml" expect="3" prose="three" -->\n'
            "Render shows three services.\n")
        facts = list(mod.facts_in(p))
        self.assertEqual(len(facts), 1)
        f = facts[0]
        self.assertEqual(f.tier, "pr")
        self.assertEqual(f.cmd, "yq '.services | length' render.yaml")
        self.assertEqual(f.expect, "3")
        self.assertEqual(f.prose, "three")
        self.assertEqual(f.lineno, 1)

    def test_fact_single_quoted_cmd_allows_inner_double_quotes(self):
        p = self.write("a.md",
            "<!-- fact: tier=scheduled cmd='gh api \"repos/x\"' expect=\"5\" -->\n"
            "Five runs.\n")
        f = list(mod.facts_in(p))[0]
        self.assertEqual(f.cmd, 'gh api "repos/x"')
        self.assertIsNone(f.prose)

    def test_following_lines_captured(self):
        p = self.write("a.md",
            '<!-- fact: tier=pr cmd="ls" expect="x" -->\nl1\nl2\nl3\nl4\n')
        self.assertEqual(list(mod.facts_in(p))[0].following, ["l1", "l2", "l3"])


if __name__ == "__main__":
    unittest.main()
