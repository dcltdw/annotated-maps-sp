"""Tests for the Layer-1 doc link checker (ADR-0011)."""
import contextlib
import io
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import check_doc_links as mod


class LinkCheckTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def write(self, name, text):
        p = self.dir / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        return p

    def test_valid_relative_link_passes(self):
        self.write("other.md", "# Other\n")
        doc = self.write("doc.md", "See [other](other.md).\n")
        self.assertEqual(mod.check_file(doc), [])

    def test_broken_link_detected(self):
        doc = self.write("doc.md", "See [missing](nope.md).\n")
        errors = mod.check_file(doc)
        self.assertEqual(len(errors), 1)
        self.assertIn("broken link", errors[0])
        self.assertIn("doc.md:1", errors[0])

    def test_valid_anchor_passes(self):
        self.write("other.md", "# Other\n\n## My Section Name\n")
        doc = self.write("doc.md", "See [sec](other.md#my-section-name).\n")
        self.assertEqual(mod.check_file(doc), [])

    def test_broken_anchor_detected(self):
        self.write("other.md", "# Other\n")
        doc = self.write("doc.md", "See [sec](other.md#no-such-anchor).\n")
        errors = mod.check_file(doc)
        self.assertEqual(len(errors), 1)
        self.assertIn("broken anchor", errors[0])

    def test_same_file_anchor(self):
        doc = self.write("doc.md", "## Target Heading\n\nJump [here](#target-heading).\n")
        self.assertEqual(mod.check_file(doc), [])

    def test_anchor_slug_strips_punctuation(self):
        # GitHub's algorithm drops non-alnum chars (except space/hyphen) and
        # turns EACH space into a hyphen, so "Risk & rollback" ->
        # "risk--rollback" (double hyphen: the "&" vanishes, both spaces stay).
        doc = self.write("doc.md", "## Risk & rollback\n\n[x](#risk--rollback)\n")
        self.assertEqual(mod.check_file(doc), [])

    def test_duplicate_headings_get_numeric_suffix(self):
        doc = self.write("doc.md", "## Setup\n\n## Setup\n\n[a](#setup) [b](#setup-1)\n")
        self.assertEqual(mod.check_file(doc), [])

    def test_links_inside_code_fences_ignored(self):
        doc = self.write("doc.md", "```\n[fake](nope.md)\n```\n")
        self.assertEqual(mod.check_file(doc), [])

    def test_external_and_mailto_skipped(self):
        doc = self.write("doc.md", "[a](https://x.test/) [b](mailto:x@y.z)\n")
        self.assertEqual(mod.check_file(doc), [])

    def test_directory_link_passes(self):
        (self.dir / "sub").mkdir()
        doc = self.write("doc.md", "[dir](sub/)\n")
        self.assertEqual(mod.check_file(doc), [])

    def test_image_link_checked(self):
        doc = self.write("doc.md", "![shot](img/missing.png)\n")
        self.assertEqual(len(mod.check_file(doc)), 1)

    def test_superpowers_archive_out_of_scope(self):
        self.assertFalse(mod.in_scope(Path("docs/superpowers/plans/x.md")))
        self.assertTrue(mod.in_scope(Path("docs/aws-primer.md")))


class MainOverrideTests(unittest.TestCase):
    def run_main(self, argv, env_body=""):
        with mock.patch.object(sys, "argv", ["check_doc_links.py", *argv]), \
                mock.patch.dict(os.environ, {"PR_BODY": env_body}), \
                mock.patch.object(mod, "tracked_md_files",
                                  return_value=[Path("fake.md")]), \
                mock.patch.object(mod, "check_file",
                                  return_value=["fake.md:1: broken link -> x"]), \
                contextlib.redirect_stdout(io.StringIO()), \
                contextlib.redirect_stderr(io.StringIO()):
            try:
                mod.main()
            except SystemExit as e:
                return e.code
            return 0

    def test_valid_override_exits_zero(self):
        self.assertEqual(
            self.run_main(["--allow-override"], "Docs-Checks-Override: mid-restructure\n"), 0)

    def test_failure_without_override_exits_one(self):
        self.assertEqual(self.run_main([]), 1)


if __name__ == "__main__":
    unittest.main()
