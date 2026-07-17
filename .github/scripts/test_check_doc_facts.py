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


class AllowlistTests(unittest.TestCase):
    def test_pr_tier_allows_repo_readers(self):
        self.assertIsNone(mod.validate_cmd("yq '.a' f.yml", "pr"))
        self.assertIsNone(mod.validate_cmd("grep -c x f.md | wc -l", "pr"))

    def test_gh_rejected_in_pr_tier_allowed_in_scheduled(self):
        self.assertIsNotNone(mod.validate_cmd("gh run list", "pr"))
        self.assertIsNone(mod.validate_cmd("gh run list", "scheduled"))

    def test_every_pipe_segment_validated(self):
        self.assertIsNotNone(mod.validate_cmd("ls | curl http://x", "pr"))

    def test_forbidden_metacharacters(self):
        for cmd in ("ls; rm -rf /", "ls && ls", "ls > f", "ls `x`", "ls $(x)"):
            self.assertIsNotNone(mod.validate_cmd(cmd, "pr"), cmd)

    def test_python3_restricted_to_repo_scripts(self):
        self.assertIsNone(mod.validate_cmd("python3 .github/scripts/fact_demo_runs.py", "pr"))
        self.assertIsNotNone(mod.validate_cmd("python3 evil.py", "pr"))

    def test_quoted_pipe_is_data_not_pipeline(self):
        self.assertIsNone(mod.validate_cmd("yq '.services | length' render.yaml", "pr"))

    def test_unparseable_cmd_reports_cleanly(self):
        err = mod.validate_cmd("yq '.unclosed", "pr")
        self.assertIsNotNone(err)
        self.assertIn("unparseable", err)

    def test_git_readonly_subcommand_allowed(self):
        self.assertIsNone(mod.validate_cmd("git ls-files '*.md'", "pr"))

    def test_git_global_flags_rejected(self):
        err = mod.validate_cmd(
            "git -c core.fsmonitor='sh -c \"touch pwned\"' status", "pr")
        self.assertIsNotNone(err)
        self.assertIn("read-only subcommands", err)

    def test_python3_path_traversal_rejected(self):
        self.assertIsNotNone(
            mod.validate_cmd("python3 .github/scripts/../../evil.py", "pr"))

    def test_logical_or_rejected(self):
        err = mod.validate_cmd("ls || curl http://evil", "pr")
        self.assertIsNotNone(err)
        self.assertIn("'||'", err)


class ExecutionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def fact(self, cmd, expect, prose=None, following=None):
        return mod.Fact(path=Path("x.md"), lineno=1, tier="pr", cmd=cmd,
                        expect=expect, prose=prose,
                        following=following if following is not None else [expect])

    def test_matching_fact_passes(self):
        f = (self.dir / "v.txt"); f.write_text("42\n")
        self.assertIsNone(mod.check_fact(self.fact(f"cat {f}", "42", following=["The value is 42."])))

    def test_value_mismatch_fails_with_expected_vs_actual(self):
        f = (self.dir / "v.txt"); f.write_text("41\n")
        err = mod.check_fact(self.fact(f"cat {f}", "42", following=["The value is 42."]))
        self.assertIn("expected '42'", err)
        self.assertIn("got '41'", err)

    def test_adjacency_rule_expect_must_appear_in_prose(self):
        f = (self.dir / "v.txt"); f.write_text("42\n")
        err = mod.check_fact(self.fact(f"cat {f}", "42", following=["No number here."]))
        self.assertIn("adjacency", err)

    def test_adjacency_rule_uses_prose_attr_when_present(self):
        f = (self.dir / "v.txt"); f.write_text("3\n")
        fact = self.fact(f"cat {f}", "3", prose="three", following=["It shows three services."])
        self.assertIsNone(mod.check_fact(fact))

    def test_command_failure_reported(self):
        err = mod.check_fact(self.fact("cat /nonexistent-x", "1", following=["1"]))
        self.assertIn("exited", err)

    def test_empty_expect_rejected(self):
        err = mod.check_fact(self.fact("ls", "", following=["x"]))
        self.assertIn("expect must be non-empty", err)


class OverrideTests(unittest.TestCase):
    def test_reason_extracted(self):
        from docs_common import override_reason
        body = "## Summary\nstuff\nDocs-Checks-Override: mid-restructure, tracked in #99\n"
        self.assertEqual(override_reason(body), "mid-restructure, tracked in #99")

    def test_no_override_line(self):
        from docs_common import override_reason
        self.assertIsNone(override_reason("## Summary\nstuff\n"))

    def test_empty_reason_is_not_a_valid_override(self):
        from docs_common import override_reason
        self.assertIsNone(override_reason("Docs-Checks-Override:   \n"))


if __name__ == "__main__":
    unittest.main()
