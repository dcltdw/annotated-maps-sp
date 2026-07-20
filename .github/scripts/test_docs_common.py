"""Tests for the shared docs-checker helpers (ADR-0011)."""
import contextlib
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import docs_common


@contextlib.contextmanager
def chdir(path):
    prior = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(prior)


class RepoRootTests(unittest.TestCase):
    def test_repo_root_is_the_worktree_root(self):
        root = docs_common.repo_root()
        self.assertTrue((root / ".git").exists())
        self.assertTrue((root / "README.md").is_file())

    def test_repo_root_same_from_a_subdirectory(self):
        root = docs_common.repo_root()
        with chdir(root / ".github" / "scripts"):
            self.assertEqual(docs_common.repo_root(), root)


class TrackedMdFilesTests(unittest.TestCase):
    def test_paths_are_repo_relative(self):
        files = docs_common.tracked_md_files()
        self.assertIn(Path("README.md"), files)
        self.assertIn(Path("docs/adr/0011-documentation-accuracy-practice.md"), files)
        self.assertFalse([p for p in files if p.is_absolute()])

    def test_identical_from_a_subdirectory(self):
        """Plain `git ls-files` run from a subdir lists only that subtree —
        the whole point of anchoring to the repo root."""
        from_root = docs_common.tracked_md_files()
        with chdir(docs_common.repo_root() / ".github" / "scripts"):
            from_subdir = docs_common.tracked_md_files()
        self.assertEqual(from_root, from_subdir)
        self.assertIn(Path("README.md"), from_subdir)


class ReadDocTextTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def test_utf8_read_normally(self):
        p = self.dir / "ok.md"
        p.write_text("# Héllo\n", encoding="utf-8")
        self.assertEqual(docs_common.read_doc_text(p), "# Héllo\n")

    def test_non_utf8_raises_doc_read_error_with_path(self):
        p = self.dir / "bad.md"
        p.write_bytes(b"# Title\n\xff\xfe\n")
        with self.assertRaises(docs_common.DocReadError) as ctx:
            docs_common.read_doc_text(p)
        self.assertIn("bad.md", str(ctx.exception))
        self.assertIn("not valid UTF-8", str(ctx.exception))

    def test_missing_file_raises_doc_read_error(self):
        with self.assertRaises(docs_common.DocReadError) as ctx:
            docs_common.read_doc_text(self.dir / "gone.md")
        self.assertIn("file not found", str(ctx.exception))

    def test_doc_read_error_is_not_the_underlying_oserror(self):
        """Callers catch DocReadError specifically; it must not be swallowed
        by an incidental OSError handler."""
        self.assertFalse(issubclass(docs_common.DocReadError, OSError))


class OverriddenTests(unittest.TestCase):
    """The warn-and-continue block both checkers share."""

    def run_overridden(self, errors, allow, body=""):
        out = io.StringIO()
        with mock.patch.dict(os.environ, {"PR_BODY": body}), \
                contextlib.redirect_stdout(out):
            result = docs_common.overridden(errors, allow)
        return result, out.getvalue()

    def test_valid_override_accepted(self):
        result, out = self.run_overridden(
            ["a.md:1: broken"], True, "Docs-Checks-Override: mid-restructure\n")
        self.assertTrue(result)
        self.assertIn("OVERRIDDEN (1 failure(s))", out)
        self.assertIn("mid-restructure", out)

    def test_failures_are_printed_as_warnings(self):
        _, out = self.run_overridden(
            ["a.md:1: broken", "b.md:2: broken"], True,
            "Docs-Checks-Override: reason\n")
        self.assertIn("  warning: a.md:1: broken", out)
        self.assertIn("  warning: b.md:2: broken", out)
        self.assertIn("OVERRIDDEN (2 failure(s))", out)

    def test_deferral_is_stated_explicitly(self):
        """The override defers, never erases — the message must say so."""
        _, out = self.run_overridden(["a.md:1: x"], True,
                                     "Docs-Checks-Override: reason\n")
        self.assertIn("Deferred, not erased", out)

    def test_rejected_without_the_flag(self):
        result, out = self.run_overridden(
            ["a.md:1: x"], False, "Docs-Checks-Override: reason\n")
        self.assertFalse(result)
        self.assertEqual(out, "")

    def test_rejected_without_a_reason(self):
        result, out = self.run_overridden(
            ["a.md:1: x"], True, "Docs-Checks-Override:   \n")
        self.assertFalse(result)
        self.assertEqual(out, "")

    def test_rejected_with_no_override_line(self):
        result, _ = self.run_overridden(["a.md:1: x"], True, "A normal PR body.\n")
        self.assertFalse(result)

    def test_missing_pr_body_env_var_is_not_an_error(self):
        with mock.patch.dict(os.environ, {}, clear=True), \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertFalse(docs_common.overridden(["a.md:1: x"], True))


class OverrideReasonTests(unittest.TestCase):
    """Moved here from test_check_doc_facts.py — override_reason lives in
    docs_common and is used by both checkers."""

    def test_reason_extracted_from_a_full_pr_body(self):
        body = "## Summary\nstuff\nDocs-Checks-Override: mid-restructure, tracked in #99\n"
        self.assertEqual(
            docs_common.override_reason(body), "mid-restructure, tracked in #99")

    def test_trailing_whitespace_trimmed(self):
        self.assertEqual(
            docs_common.override_reason("Docs-Checks-Override: reason   \n"),
            "reason")

    def test_no_override_line(self):
        self.assertIsNone(docs_common.override_reason("Nothing here.\n"))

    def test_empty_reason_rejected(self):
        self.assertIsNone(docs_common.override_reason("Docs-Checks-Override:   \n"))


if __name__ == "__main__":
    unittest.main()
