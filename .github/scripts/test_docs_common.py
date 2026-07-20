"""Tests for the shared docs-checker helpers (ADR-0011)."""
import contextlib
import os
import tempfile
import unittest
from pathlib import Path

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


if __name__ == "__main__":
    unittest.main()
