"""Tests for scripts/ci/guards.py (infra-foundation T4). Every rule has a passing and a failing sample."""

from __future__ import annotations

import io
import unittest
from contextlib import redirect_stderr

from helpers import FAKE_ACCOUNT, PLACEHOLDER, REPO_ROOT, RepoCase, git  # noqa: E402  (helpers fixes sys.path)

import guards  # noqa: E402

SHA40 = "a1b2c3d4e5" * 4
SHA64 = "0123456789abcdef" * 4


class GuardCase(RepoCase):
    def findings(self, *names: str) -> list:
        return guards.run(self.repo, list(names) or list(guards.CHECKS))

    def reasons(self, check: str) -> list:
        return [f.render() for f in self.findings(check)]


class AccountIds(GuardCase):
    def test_account_id_in_terraform_fails(self) -> None:
        self.write("infra/main.tf", f'account = "{FAKE_ACCOUNT}"\n')
        self.assertEqual(len(self.findings("account-ids")), 1)

    def test_account_id_in_any_tracked_tf_file_fails(self) -> None:
        self.write("backend/other.tf", f'x = "{FAKE_ACCOUNT}"\n')
        self.assertEqual(len(self.findings("account-ids")), 1)

    def test_account_id_in_runbook_fails(self) -> None:
        self.write("docs/runbooks/a.md", f"the account is {FAKE_ACCOUNT}\n")
        self.assertEqual(len(self.findings("account-ids")), 1)

    def test_arn_with_account_in_workflow_fails(self) -> None:
        self.write(".github/workflows/x.yml", f"role: arn:aws:iam::{FAKE_ACCOUNT}:role/x\n")
        found = self.findings("account-ids")
        self.assertEqual(len(found), 1)
        self.assertIn("ARN", found[0].reason)

    def test_arn_in_other_partition_fails(self) -> None:
        self.write("infra/a.tf", f'a = "arn:aws-us-gov:iam::{FAKE_ACCOUNT}:role/x"\n')
        self.assertEqual(len(self.findings("account-ids")), 1)

    def test_placeholder_outside_a_test_file_fails(self) -> None:
        self.write("infra/main.tf", f'account = "{PLACEHOLDER}"\n')
        self.assertEqual(len(self.findings("account-ids")), 1)

    def test_placeholder_in_tftest_passes(self) -> None:
        self.write("infra/modules/m/tests/a.tftest.hcl", f'account_id = "{PLACEHOLDER}"\nx = "arn:aws:iam::{PLACEHOLDER}:role/y"\n')
        self.assertEqual(self.findings("account-ids"), [])

    def test_placeholder_in_example_file_passes(self) -> None:
        self.write("infra/bootstrap/terraform.tfvars.example", f'allowed_account_ids = ["{PLACEHOLDER}"]\n')
        self.write("infra/bootstrap/backend.hcl.example", f'kms_key_id = "arn:aws:kms:eu-west-2:{PLACEHOLDER}:key/x"\n')
        self.assertEqual(self.findings("account-ids"), [])

    def test_placeholder_in_ci_test_directory_passes(self) -> None:
        self.write("scripts/ci/tests/t.py", f"x = '{PLACEHOLDER}'\n")
        self.assertEqual(self.findings("account-ids"), [])

    def test_a_different_id_in_a_test_file_still_fails(self) -> None:
        self.write("infra/modules/m/tests/a.tftest.hcl", f'account_id = "{FAKE_ACCOUNT}"\n')
        self.assertEqual(len(self.findings("account-ids")), 1)

    def test_lock_file_hashes_pass(self) -> None:
        digits_inside_hex = "a" + "9" * 12 + "b" + "c" * 51
        self.write("infra/.terraform.lock.hcl", f'hashes = [\n  "zh:{digits_inside_hex}",\n  "h1:abc+/{"9" * 12}x=",\n]\n')
        self.assertEqual(self.findings("account-ids"), [])

    def test_a_uuid_ending_in_twelve_digits_passes(self) -> None:
        self.write("infra/modules/m/tests/a.tftest.hcl", 'key_id = "00000000-0000-0000-0000-000000000000"\n')
        self.write("infra/b.tf", f'id = "1b2c3d4e-5f60-4a1b-8c2d-{FAKE_ACCOUNT}"\n')
        self.assertEqual(self.findings("account-ids"), [])

    def test_an_account_id_glued_to_a_name_still_fails(self) -> None:
        self.write("infra/a.tf", f'bucket = "graveyard-tfstate-{FAKE_ACCOUNT}"\n')
        self.write("infra/b.tf", f'x = "1b2c3d4e-5f60-4a1b-8c2d-{FAKE_ACCOUNT}-{FAKE_ACCOUNT}"\n')
        self.assertEqual(sorted(f.path for f in self.findings("account-ids")), ["infra/a.tf", "infra/b.tf"])

    def test_other_digit_lengths_pass(self) -> None:
        self.write("infra/a.tf", f"a = {'9' * 11}\nb = {'9' * 13}\nc = x{'9' * 12}\nd = {'9' * 12}x\n")
        self.assertEqual(self.findings("account-ids"), [])

    def test_files_outside_the_scope_pass(self) -> None:
        self.write("backend/data.json", f'{{"n": {FAKE_ACCOUNT}}}\n')
        self.write("docs/PRD.md", f"{FAKE_ACCOUNT}\n")
        self.assertEqual(self.findings("account-ids"), [])

    def test_git_ignored_files_are_not_scanned(self) -> None:
        self.write(".gitignore", "*.tfvars\n!*.tfvars.example\n")
        self.write("infra/bootstrap/terraform.tfvars", f'allowed_account_ids = ["{FAKE_ACCOUNT}"]\n', add=False)
        self.assertEqual(self.findings("account-ids"), [])

    def test_a_new_untracked_file_is_scanned(self) -> None:
        self.write("infra/new.tf", f'x = "{FAKE_ACCOUNT}"\n', add=False)
        self.assertEqual(len(self.findings("account-ids")), 1)


class TrackedFiles(GuardCase):
    def test_forbidden_names_fail(self) -> None:
        for name in (
            "infra/bootstrap/terraform.tfstate",
            "infra/bootstrap/terraform.tfstate.backup",
            "x/a.tfplan",
            "infra/bootstrap/backend.hcl",
            "infra/bootstrap/local_backend_override.tf",
            "infra/bootstrap/terraform.tfvars",
        ):
            with self.subTest(name=name):
                self.write(name, "x", force=True)
                self.assertEqual([f.path for f in self.findings("tracked-files")], [name])
                (self.repo / name).unlink()
                git(self.repo, "rm", "-q", "--cached", "--", name)

    def test_example_files_pass(self) -> None:
        self.write("infra/bootstrap/backend.hcl.example", "bucket = \"x\"\n")
        self.write("infra/bootstrap/terraform.tfvars.example", "a = 1\n")
        self.write("infra/main.tf", "a = 1\n")
        self.assertEqual(self.findings("tracked-files"), [])

    def test_ignored_untracked_files_pass(self) -> None:
        self.write(".gitignore", "backend.hcl\n*_override.tf\n*.tfstate\n")
        self.write("infra/bootstrap/backend.hcl", "x", add=False)
        self.write("infra/bootstrap/local_backend_override.tf", "x", add=False)
        self.assertEqual(self.findings("tracked-files"), [])

    def test_force_added_ignored_file_fails(self) -> None:
        self.write(".gitignore", "backend.hcl\n")
        self.write("infra/bootstrap/backend.hcl", "x", force=True)
        self.assertEqual(len(self.findings("tracked-files")), 1)


class WorkflowTriggers(GuardCase):
    def test_every_form_of_pull_request_target_fails(self) -> None:
        forms = {
            "inline": "on: pull_request_target\njobs: {}\n",
            "flow list": "on: [push, pull_request_target]\njobs: {}\n",
            "block list": "on:\n  - push\n  - pull_request_target\njobs: {}\n",
            "map": "on:\n  pull_request_target:\n    branches: [main]\njobs: {}\n",
            "map with types": "on:\n  pull_request_target:\n    types: [opened]\n",
        }
        for label, text in forms.items():
            with self.subTest(form=label):
                self.write(".github/workflows/w.yml", text)
                self.assertEqual(len(self.findings("workflow-triggers")), 1, label)

    def test_safe_triggers_pass(self) -> None:
        self.write(".github/workflows/w.yml", "on:\n  pull_request:\n  push:\n    branches: [main]\n")
        self.assertEqual(self.findings("workflow-triggers"), [])

    def test_a_comment_that_names_it_passes(self) -> None:
        self.write(".github/workflows/w.yml", "# never pull_request_target\non: pull_request # not pull_request_target\n")
        self.assertEqual(self.findings("workflow-triggers"), [])

    def test_yaml_extension_is_scanned(self) -> None:
        self.write(".github/workflows/w.yaml", "on: pull_request_target\n")
        self.assertEqual(len(self.findings("workflow-triggers")), 1)

    def test_files_outside_workflows_are_ignored(self) -> None:
        self.write("docs/x.yml", "on: pull_request_target\n")
        self.assertEqual(self.findings("workflow-triggers"), [])


class ActionPins(GuardCase):
    def test_tag_pinned_action_fails(self) -> None:
        self.write(".github/workflows/w.yml", "jobs:\n  a:\n    steps:\n      - uses: actions/checkout@v4\n")
        self.assertEqual(len(self.findings("action-pins")), 1)

    def test_branch_pinned_action_fails(self) -> None:
        self.write(".github/workflows/w.yml", "      - uses: actions/checkout@main\n")
        self.assertEqual(len(self.findings("action-pins")), 1)

    def test_short_sha_fails(self) -> None:
        self.write(".github/workflows/w.yml", f"      - uses: a/b@{SHA40[:39]}\n")
        self.assertEqual(len(self.findings("action-pins")), 1)

    def test_unpinned_action_fails(self) -> None:
        self.write(".github/workflows/w.yml", "      - uses: a/b\n")
        self.assertEqual(len(self.findings("action-pins")), 1)

    def test_sha_pinned_with_version_comment_passes(self) -> None:
        self.write(".github/workflows/w.yml", f"      - uses: actions/checkout@{SHA40} # v7.0.1\n")
        self.assertEqual(self.findings("action-pins"), [])

    def test_quoted_sha_pin_passes(self) -> None:
        self.write(".github/workflows/w.yml", f"      uses: 'a/b@{SHA40}'\n")
        self.assertEqual(self.findings("action-pins"), [])

    def test_local_actions_and_workflows_pass(self) -> None:
        self.write(".github/workflows/w.yml", "      - uses: ./.github/actions/terraform-init\n    uses: ./.github/workflows/deploy.yml\n")
        self.assertEqual(self.findings("action-pins"), [])

    def test_docker_digest_passes_and_tag_fails(self) -> None:
        self.write(".github/workflows/w.yml", f"      - uses: docker://alpine@sha256:{SHA64}\n")
        self.assertEqual(self.findings("action-pins"), [])
        self.write(".github/workflows/w.yml", "      - uses: docker://alpine:3\n")
        self.assertEqual(len(self.findings("action-pins")), 1)

    def test_composite_action_files_are_scanned(self) -> None:
        self.write(".github/actions/x/action.yml", "runs:\n  steps:\n    - uses: a/b@v1\n")
        self.assertEqual(len(self.findings("action-pins")), 1)

    def test_commented_uses_passes(self) -> None:
        self.write(".github/workflows/w.yml", "      # uses: a/b@v1\n")
        self.assertEqual(self.findings("action-pins"), [])


class ModulePolicies(GuardCase):
    def test_data_source_in_a_module_fails(self) -> None:
        self.write("infra/modules/x/main.tf", 'data "aws_caller_identity" "current" {}\n')
        self.assertEqual(len(self.findings("module-policies")), 1)

    def test_data_source_in_a_root_passes(self) -> None:
        self.write("infra/bootstrap/main.tf", 'data "aws_caller_identity" "current" {}\n')
        self.assertEqual(self.findings("module-policies"), [])

    def test_policy_document_anywhere_in_infra_fails(self) -> None:
        self.write("infra/bootstrap/p.tf", 'data "aws_iam_policy_document" "x" {}\n')
        self.write("infra/modules/m/p.tf", 'resource "x" "y" { p = data.aws_iam_policy_document.x.json }\n')
        self.assertEqual(sorted(f.path for f in self.findings("module-policies")), ["infra/bootstrap/p.tf", "infra/modules/m/p.tf"])
        self.write("infra/modules/m/q.tf", 'data "aws_iam_policy_document" "y" {}\n')
        self.assertEqual(len([f for f in self.findings("module-policies") if f.path.endswith("q.tf")]), 2)

    def test_comments_and_strings_that_mention_it_pass(self) -> None:
        self.write(
            "infra/modules/m/a.tf",
            '# we do not use aws_iam_policy_document here\n// nor data "x" "y" {}\n/* data "a" "b" {} */\ndescription = "reads data from the table"\n',
        )
        self.assertEqual(self.findings("module-policies"), [])

    def test_indented_data_block_in_a_module_fails(self) -> None:
        self.write("infra/modules/x/main.tf", '  data   "aws_partition" "current" {}\n')
        self.assertEqual(len(self.findings("module-policies")), 1)

    def test_tftest_files_are_not_scanned(self) -> None:
        self.write("infra/modules/x/tests/a.tftest.hcl", 'mock_provider "aws" {}\n')
        self.assertEqual(self.findings("module-policies"), [])


class Runner(GuardCase):
    def test_all_runs_every_check(self) -> None:
        self.write("infra/modules/x/main.tf", f'data "a" "b" {{}}\nx = "{FAKE_ACCOUNT}"\n')
        self.write("infra/bootstrap/backend.hcl", "x", force=True)
        self.write(".github/workflows/w.yml", "on: pull_request_target\njobs:\n  a:\n    steps:\n      - uses: a/b@v1\n")
        names = {f.check for f in self.findings()}
        self.assertEqual(names, set(guards.CHECKS))

    def test_main_returns_one_on_findings_and_zero_on_clean(self) -> None:
        self.write("infra/main.tf", "a = 1\n")
        stderr = io.StringIO()
        with redirect_stderr(stderr):
            self.assertEqual(guards.main([], root=self.repo), 0)
        self.write("infra/main.tf", f'a = "{FAKE_ACCOUNT}"\n')
        with redirect_stderr(stderr):
            self.assertEqual(guards.main(["account-ids"], root=self.repo), 1)
        self.assertIn("account-ids: infra/main.tf:1:", stderr.getvalue())

    def test_main_rejects_an_unknown_check(self) -> None:
        stderr = io.StringIO()
        with redirect_stderr(stderr):
            self.assertEqual(guards.main(["nope"], root=self.repo), 2)
        self.assertIn("unknown check", stderr.getvalue())

    def test_a_directory_that_is_not_a_repository_returns_two(self) -> None:
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as plain, redirect_stderr(io.StringIO()):
            self.assertEqual(guards.main([], root=Path(plain)), 2)

    def test_binary_files_are_skipped(self) -> None:
        (self.repo / "infra").mkdir()
        (self.repo / "infra" / "blob.hcl").write_bytes(b"\0" + FAKE_ACCOUNT.encode())
        self.assertEqual(self.findings("account-ids"), [])


class RealRepository(unittest.TestCase):
    def test_all_checks_pass_on_the_real_repository(self) -> None:
        stderr = io.StringIO()
        with redirect_stderr(stderr):
            code = guards.main([], root=REPO_ROOT)
        self.assertEqual(code, 0, stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
