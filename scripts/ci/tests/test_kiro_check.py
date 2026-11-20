"""Tests for scripts/ci/check_kiro_not_ignored.py (infra-foundation T5, INF-KIRO-1)."""

from __future__ import annotations

import io
import unittest
from contextlib import redirect_stderr
from pathlib import Path

from helpers import REPO_ROOT, RepoCase, git  # noqa: E402  (helpers fixes sys.path)

import check_kiro_not_ignored as kiro  # noqa: E402



class KiroCheck(RepoCase):
    def result(self) -> tuple:
        err = io.StringIO()
        with redirect_stderr(err):
            code = kiro.main(root=self.repo)
        return code, err.getvalue()

    def clean_repo(self) -> None:
        self.write(".kiro/specs/a/requirements.md", "# a\n")
        self.write(".kiro/steering/x.md", "x\n")
        self.write("README.md", "r\n")

    def test_clean_repository_passes(self) -> None:
        self.clean_repo()
        self.assertEqual(self.result(), (0, ""))

    def test_root_gitignore_with_kiro_dir_fails(self) -> None:
        self.clean_repo()
        self.write(".gitignore", ".kiro/\n")
        code, message = self.result()
        self.assertEqual(code, 1)
        self.assertIn(".gitignore:1", message)
        self.assertIn("'.kiro/'", message)

    def test_root_gitignore_with_kiro_name_fails(self) -> None:
        self.clean_repo()
        self.write(".gitignore", ".kiro\n")
        self.assertEqual(self.result()[0], 1)

    def test_glob_pattern_fails(self) -> None:
        self.clean_repo()
        self.write(".gitignore", "**/.kiro\n")
        self.assertEqual(self.result()[0], 1)

    def test_contents_pattern_fails_even_for_tracked_files(self) -> None:
        self.clean_repo()
        self.write(".gitignore", ".kiro/*\n")
        code, message = self.result()
        self.assertEqual(code, 1)
        self.assertIn(".kiro/specs/a/requirements.md", message)

    def test_nested_gitignore_inside_kiro_fails(self) -> None:
        self.clean_repo()
        self.write(".kiro/.gitignore", "specs/\n")
        code, message = self.result()
        self.assertEqual(code, 1)
        self.assertIn(".kiro/.gitignore:1", message)

    def test_info_exclude_fails(self) -> None:
        self.clean_repo()
        exclude = self.repo / ".git" / "info" / "exclude"
        exclude.parent.mkdir(parents=True, exist_ok=True)
        exclude.write_text(".kiro/*\n", encoding="utf-8")
        code, message = self.result()
        self.assertEqual(code, 1)
        self.assertIn("exclude", message)

    def test_a_later_negation_makes_it_pass(self) -> None:
        self.clean_repo()
        self.write(".gitignore", ".kiro/\n!.kiro/\n")
        self.assertEqual(self.result()[0], 0)

    def test_a_gitignore_for_other_paths_passes(self) -> None:
        self.clean_repo()
        self.write(".gitignore", "node_modules/\n*.tfstate\n.terraform/\n")
        self.assertEqual(self.result()[0], 0)

    def test_empty_kiro_directory_fails(self) -> None:
        (self.repo / ".kiro").mkdir()
        self.write("README.md", "r\n")
        code, message = self.result()
        self.assertEqual(code, 1)
        self.assertIn("no tracked files", message)

    def test_missing_kiro_directory_fails(self) -> None:
        self.write("README.md", "r\n")
        self.assertEqual(self.result()[0], 1)

    def test_kiro_files_that_are_only_untracked_fail(self) -> None:
        self.write(".kiro/a.md", "a\n", add=False)
        self.assertEqual(self.result()[0], 1)

    def test_not_a_repository_returns_two(self) -> None:
        import tempfile

        err = io.StringIO()
        with tempfile.TemporaryDirectory() as plain, redirect_stderr(err):
            self.assertEqual(kiro.main(root=Path(plain)), 2)

    def test_filenames_with_spaces_are_handled(self) -> None:
        self.write(".kiro/specs/my spec/requirements.md", "x\n")
        self.assertEqual(self.result()[0], 0)
        self.write(".gitignore", ".kiro/specs/my spec/\n")
        self.assertEqual(self.result()[0], 1)


class RealRepository(unittest.TestCase):
    def test_the_real_repository_passes(self) -> None:
        err = io.StringIO()
        with redirect_stderr(err):
            code = kiro.main(root=REPO_ROOT)
        self.assertEqual(code, 0, err.getvalue())

    def test_the_real_repository_has_tracked_kiro_files(self) -> None:
        out = git(REPO_ROOT, "ls-files", ".kiro").stdout.split()
        self.assertTrue(out)


if __name__ == "__main__":
    unittest.main()
