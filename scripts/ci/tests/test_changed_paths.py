"""Tests for scripts/ci/changed_paths.py (infra-foundation T5, INF-CI-1)."""

from __future__ import annotations

import io
import unittest
from contextlib import redirect_stdout

from helpers import RepoCase  # noqa: E402  (helpers fixes sys.path)

import changed_paths  # noqa: E402


class ChangedPaths(RepoCase):
    def base_commit(self) -> str:
        self.write("README.md", "r\n")
        self.write("backend/a.py", "a\n")
        self.commit("base")
        return self.head()

    def change(self, path: str, base: str, merge_base: bool = False) -> bool:
        self.write(path, "changed\n")
        self.commit("change")
        return changed_paths.changed(self.repo, base, self.head(), merge_base)

    def test_each_pattern_is_true(self) -> None:
        for path in ("infra/main.tf", ".github/workflows/ci.yml", "scripts/ci/guards.py", "docs/runbooks/terraform-bootstrap.md", "scripts/build/build_lambda_zip.py", "backend/workflow/fetch.py", "backend/core/scan/ids.py", "backend/uv.lock"):
            with self.subTest(path=path):
                base = self.base_commit() if path == "infra/main.tf" else self.head()
                self.assertTrue(self.change(path, base))

    def test_only_unrelated_paths_is_false(self) -> None:
        base = self.base_commit()
        self.assertFalse(self.change("backend/b.py", base))
        self.assertFalse(self.change("docs/PRD.md", base))
        self.assertFalse(self.change("web/page.tsx", base))

    def test_a_similar_prefix_is_not_a_match(self) -> None:
        base = self.base_commit()
        self.assertFalse(self.change("infrastructure/x.tf", base))
        self.assertFalse(self.change("scripts/other/x.sh", base))

    def test_empty_base_is_true(self) -> None:
        self.base_commit()
        self.assertTrue(changed_paths.changed(self.repo, "", self.head()))

    def test_all_zero_base_is_true(self) -> None:
        self.base_commit()
        self.assertTrue(changed_paths.changed(self.repo, "0" * 40, self.head()))

    def test_unknown_base_is_true(self) -> None:
        self.base_commit()
        self.assertTrue(changed_paths.changed(self.repo, "1" * 40, self.head()))

    def test_unknown_head_is_true(self) -> None:
        base = self.base_commit()
        self.assertTrue(changed_paths.changed(self.repo, base, "2" * 40))

    def test_merge_base_form_ignores_changes_made_on_the_base_branch(self) -> None:
        base = self.base_commit()
        self.write("infra/on-main.tf", "x\n")
        self.commit("main moves on")
        main_tip = self.head()
        # a pull request branch from `base` that touches only backend/
        from helpers import git

        git(self.repo, "checkout", "-q", "-b", "pr", base)
        self.write("backend/pr.py", "p\n")
        self.commit("pr")
        pr_tip = self.head()
        self.assertFalse(changed_paths.changed(self.repo, main_tip, pr_tip, merge_base=True))
        self.assertTrue(changed_paths.changed(self.repo, main_tip, pr_tip, merge_base=False))

    def test_command_line_prints_a_github_output_line(self) -> None:
        base = self.base_commit()
        self.write("infra/a.tf", "x\n")
        self.commit("infra")
        out = io.StringIO()
        with redirect_stdout(out):
            code = changed_paths.main(["--base", base, "--head", self.head()], root=self.repo)
        self.assertEqual((code, out.getvalue()), (0, "infra=true\n"))
        out = io.StringIO()
        with redirect_stdout(out):
            changed_paths.main(["--base", self.head(), "--head", self.head()], root=self.repo)
        self.assertEqual(out.getvalue(), "infra=false\n")

    def test_rename_out_of_infra_counts(self) -> None:
        self.write("infra/a.tf", "x\n")
        self.commit("add")
        base = self.head()
        from helpers import git

        (self.repo / "backend").mkdir()
        git(self.repo, "mv", "infra/a.tf", "backend/a.tf")
        self.commit("move")
        self.assertTrue(changed_paths.changed(self.repo, base, self.head()))


if __name__ == "__main__":
    unittest.main()
