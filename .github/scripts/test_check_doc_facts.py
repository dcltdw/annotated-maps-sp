"""Tests for the Layer-2 doc facts checker (ADR-0011)."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

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


class TaxonomyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)
        self._cwd = os.getcwd()
        os.chdir(self.dir)
        self.addCleanup(os.chdir, self._cwd)

    def write(self, rel, text):
        p = Path(rel)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        return p

    def patch_tracked(self, paths):
        patcher = mock.patch.object(
            mod, "tracked_md_files", return_value=[Path(p) for p in paths]
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_missing_marker_reported(self):
        self.write("docs/DEPLOY.md", "# Deploy\n")
        self.patch_tracked(["docs/DEPLOY.md"])
        errors = mod.taxonomy_errors()
        self.assertEqual(len(errors), 1)
        self.assertIn("missing", errors[0])

    def test_living_doc_marked_dated_reported(self):
        self.write("docs/DEPLOY.md", "<!-- doc-status: dated -->\n# Deploy\n")
        self.patch_tracked(["docs/DEPLOY.md"])
        errors = mod.taxonomy_errors()
        self.assertEqual(len(errors), 1)
        self.assertIn("listed as living but marked 'dated'", errors[0])

    def test_non_living_doc_marked_living_reported(self):
        self.write("docs/adr/0001-x.md", "<!-- doc-status: living -->\n# ADR\n")
        self.patch_tracked(["docs/adr/0001-x.md"])
        errors = mod.taxonomy_errors()
        self.assertEqual(len(errors), 1)
        self.assertIn("marked living but not in the LIVING set", errors[0])

    def test_fact_in_dated_doc_reported(self):
        self.write(
            "docs/adr/0001-x.md",
            '<!-- doc-status: dated -->\n<!-- fact: tier=pr cmd="ls" expect="x" -->\nx\n',
        )
        self.patch_tracked(["docs/adr/0001-x.md"])
        errors = mod.taxonomy_errors()
        self.assertEqual(len(errors), 1)
        self.assertIn("facts belong only in living docs", errors[0])

    def test_exempt_paths_skipped(self):
        self.write("docs/superpowers/plans/p.md", "no marker here\n")
        self.write("CLAUDE.md", "no marker here\n")
        self.patch_tracked(["docs/superpowers/plans/p.md", "CLAUDE.md"])
        self.assertEqual(mod.taxonomy_errors(), [])

    def test_clean_taxonomy_no_errors(self):
        self.write("docs/DEPLOY.md", "<!-- doc-status: living -->\n# Deploy\n")
        self.write("docs/adr/0001-x.md", "<!-- doc-status: dated -->\n# ADR\n")
        self.patch_tracked(["docs/DEPLOY.md", "docs/adr/0001-x.md"])
        self.assertEqual(mod.taxonomy_errors(), [])


if __name__ == "__main__":
    unittest.main()
