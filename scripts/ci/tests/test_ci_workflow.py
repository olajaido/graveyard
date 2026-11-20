"""ci.yml and deploy.yml (infra-foundation T16.3, T17.2; INF-CI-1..11, INF-KIRO-1, INF-OIDC-3, INF-OIDC-4, INF-OIDC-9).

The rules live in workflow_rules.py as functions over the file text. They must find nothing in the real files and
must find something in every broken copy below, so no rule can pass vacuously.
"""

from __future__ import annotations

import shutil
import subprocess
import unittest

from helpers import REPO_ROOT

import actions_text as a
import workflow_rules as rules

CI = (REPO_ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
DEPLOY = (REPO_ROOT / ".github/workflows/deploy.yml").read_text(encoding="utf-8")


class RealFiles(unittest.TestCase):
    def test_ci_has_no_problems(self) -> None:
        self.assertEqual(rules.ci_problems(CI), [])

    def test_deploy_has_no_problems(self) -> None:
        self.assertEqual(rules.deploy_problems(DEPLOY), [])

    def test_the_two_workflows_agree_on_the_inputs(self) -> None:
        deploy_inputs = rules.DEPLOY_INPUTS
        ci_with = sorted(a.jobs_of(CI)["deploy"]["with"])
        self.assertEqual(ci_with, sorted(deploy_inputs))

    def test_dev_is_never_wired_to_prod_values(self) -> None:
        jobs = a.jobs_of(DEPLOY)
        dev, prod = jobs["apply-dev"]["steps"][1]["with"], jobs["apply-prod"]["steps"][1]["with"]
        self.assertTrue(all("prod" not in v for v in dev.values()))
        self.assertTrue(all("dev" not in v for v in prod.values()))
        ci_deploy = a.jobs_of(CI)["deploy"]["with"]
        self.assertTrue(all("plan-dev" in v for k, v in ci_deploy.items() if k.startswith("dev_")))
        self.assertTrue(all("plan-prod" in v for k, v in ci_deploy.items() if k.startswith("prod_")))

    def test_the_apply_roles_and_the_environments_are_the_ones_the_trust_policy_names(self) -> None:
        trust = (REPO_ROOT / "infra/modules/github-oidc/apply_roles.tf").read_text(encoding="utf-8")
        self.assertIn('"repo:${local.repo}:environment:${e}"', trust)
        jobs = a.jobs_of(DEPLOY)
        self.assertEqual({jobs["apply-dev"]["keys"]["environment"], jobs["apply-prod"]["keys"]["environment"]}, {"dev", "prod"})
        # The plan jobs have no environment, so their subject is pull_request or the main branch, as the plan role trusts.
        plan_trust = (REPO_ROOT / "infra/modules/github-oidc/plan_role.tf").read_text(encoding="utf-8")
        self.assertIn(":pull_request", plan_trust)
        self.assertIn(":ref:refs/heads/main", plan_trust)

    def test_the_state_variables_are_the_ones_the_runbook_will_list(self) -> None:
        text = CI + DEPLOY
        for name in ("vars.TF_STATE_BUCKET", "vars.TF_STATE_KMS_KEY_ID", "vars.AWS_REGION", "secrets.AWS_ACCOUNT_ID"):
            self.assertIn(name, text)
        # The one other secret: the workflow token, in the tflint job of ci.yml only (decision T24).
        self.assertNotRegex(text, r"secrets\.(?!AWS_ACCOUNT_ID\b|GITHUB_TOKEN\b)[A-Z_]+")
        self.assertNotIn("secrets.GITHUB_TOKEN", DEPLOY)
        self.assertEqual(CI.count("secrets.GITHUB_TOKEN"), 1)
        self.assertNotIn("secrets: inherit", text)

    @unittest.skipUnless(shutil.which("ruby"), "ruby is on the CI runners; skipped where it is not installed")
    def test_every_yaml_file_parses(self) -> None:
        for path in sorted((REPO_ROOT / ".github").rglob("*.yml")):
            done = subprocess.run(["ruby", "-ryaml", "-e", "YAML.safe_load(File.read(ARGV[0]), aliases: false)", str(path)], capture_output=True, text=True)
            self.assertEqual(done.returncode, 0, f"{path}: {done.stderr}")

    @unittest.skipUnless(shutil.which("ruby"), "ruby is on the CI runners; skipped where it is not installed")
    def test_the_yaml_parse_check_can_fail(self) -> None:
        bad = "run: echo \"a: b\"\nname: x: y\n"
        done = subprocess.run(["ruby", "-ryaml", "-e", "YAML.safe_load(ARGV[0])", bad], capture_output=True, text=True)
        self.assertNotEqual(done.returncode, 0)


def CI_WITH_TFLINT_WRITE() -> list:
    marker = "  tflint:\n    needs: changes\n    if: needs.changes.outputs.infra == 'true'\n    runs-on: ubuntu-24.04\n    timeout-minutes: 15\n    permissions:\n      contents: read\n"
    assert marker in CI
    return rules.ci_problems(CI.replace(marker, marker + "      pull-requests: write\n", 1))
class BrokenCi(unittest.TestCase):
    """Each change below breaks one rule of ci.yml, and the rules must notice."""

    def broken(self, old: str, new: str, count: int = 1) -> list:
        self.assertIn(old, CI, f"the sample's anchor is gone: {old!r}")
        return rules.ci_problems(CI.replace(old, new, count))

    def assertCaught(self, problems: list, fragment: str) -> None:
        self.assertTrue(any(fragment in p for p in problems), f"{fragment!r} not in {problems}")

    def test_pull_request_target(self) -> None:
        self.assertCaught(self.broken("on:\n  pull_request:\n", "on:\n  pull_request_target:\n"), "pull_request_target")

    def test_a_manual_trigger(self) -> None:
        self.assertCaught(self.broken("  push:\n    branches: [main]\n", "  push:\n    branches: [main]\n  workflow_dispatch:\n"), "workflow_dispatch")

    def test_a_branch_other_than_main(self) -> None:
        self.assertCaught(self.broken("branches: [main]", "branches: [main, dev]"), "pull_request and push to main only")

    def test_top_level_permissions_removed(self) -> None:
        self.assertCaught(self.broken("permissions: {}\n\nconcurrency", "concurrency"), "top-level permissions")

    def test_id_token_on_a_static_job(self) -> None:
        self.assertCaught(self.broken("  tflint:\n    needs: changes\n    if: needs.changes.outputs.infra == 'true'\n    runs-on: ubuntu-24.04\n    timeout-minutes: 15\n    permissions:\n      contents: read\n",
                                      "  tflint:\n    needs: changes\n    if: needs.changes.outputs.infra == 'true'\n    runs-on: ubuntu-24.04\n    timeout-minutes: 15\n    permissions:\n      contents: read\n      id-token: write\n"), "id-token")

    def test_the_token_in_another_job(self) -> None:
        self.assertCaught(self.broken("      - name: actionlint\n        run: scripts/ci/local-checks.sh actionlint", "      - name: actionlint\n        env:\n          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}\n        run: scripts/ci/local-checks.sh actionlint"), "tflint job only")
    def test_the_token_removed_from_the_tflint_step(self) -> None:
        self.assertCaught(self.broken("        env:\n          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}\n        run: scripts/ci/local-checks.sh tflint", "        run: scripts/ci/local-checks.sh tflint"), "tflint job only")
    def test_the_tflint_job_with_more_than_read_access(self) -> None:
        self.assertCaught(CI_WITH_TFLINT_WRITE(), "exactly contents: read")
    def test_the_tflint_cache_removed(self) -> None:
        self.assertCaught(self.broken("hashFiles('infra/.tflint.hcl', 'infra/.tool-versions')", "hashFiles('infra/.tool-versions')"), "plugin cache")
    def test_write_permission_on_contents(self) -> None:
        self.assertCaught(self.broken("permissions:\n      contents: read\n", "permissions:\n      contents: write\n"), "contents must be read")

    def test_an_environment_on_a_plan_job(self) -> None:
        self.assertCaught(self.broken("  plan-dev:\n", "  plan-dev:\n    environment: dev\n"), "no environment")

    def test_a_condition_on_the_kiro_check(self) -> None:
        self.assertCaught(self.broken("  kiro-not-ignored:\n", "  kiro-not-ignored:\n    if: github.event_name == 'push'\n"), "no needs and no if")

    def test_the_kiro_check_needing_another_job(self) -> None:
        self.assertCaught(self.broken("  kiro-not-ignored:\n", "  kiro-not-ignored:\n    needs: changes\n"), "no needs and no if")

    def test_a_static_job_that_always_runs(self) -> None:
        self.assertCaught(self.broken("  tf-fmt:\n    needs: changes\n    if: needs.changes.outputs.infra == 'true'\n", "  tf-fmt:\n    needs: changes\n"), "must run only when infra changed")

    def test_a_plan_job_that_does_not_wait_for_the_checks(self) -> None:
        self.assertCaught(self.broken("needs: [changes, kiro-not-ignored, guards, tf-fmt, tf-validate, tf-test, tflint, checkov, actionlint]", "needs: [changes]"), "must need every static job")

    def test_a_plan_job_for_forks(self) -> None:
        self.assertCaught(self.broken(" && github.actor != 'dependabot[bot]'", ""), "dependabot")

    def test_a_plan_that_is_always_stored(self) -> None:
        self.assertCaught(self.broken("upload: ${{ github.event_name == 'push' && github.ref == 'refs/heads/main' }}", "upload: \"true\""), "stored only on a push to main")

    def test_an_account_id_from_a_variable(self) -> None:
        self.assertCaught(self.broken("account-id: ${{ secrets.AWS_ACCOUNT_ID }}", "account-id: ${{ vars.AWS_ACCOUNT_ID }}"), "from the secret")

    def test_deploy_without_the_push_condition(self) -> None:
        self.assertCaught(self.broken("github.event_name == 'push' && github.ref == 'refs/heads/main' &&\n      (needs", "(needs"), "deploy: the if must include")

    def test_deploy_inheriting_secrets(self) -> None:
        self.assertCaught(self.broken("    secrets:\n      AWS_ACCOUNT_ID: ${{ secrets.AWS_ACCOUNT_ID }}\n", "    secrets: inherit\n"), "never inherit")

    def test_deploy_crossing_the_envs(self) -> None:
        self.assertCaught(self.broken("dev_sha256: ${{ needs.plan-dev.outputs.sha256 }}", "dev_sha256: ${{ needs.plan-prod.outputs.sha256 }}"), "dev_sha256 must come from plan-dev")

    def test_an_expression_inside_a_run_block(self) -> None:
        self.assertCaught(self.broken('run: terraform -chdir="$ROOT" validate', 'run: terraform -chdir="${{ matrix.root }}" validate'), "script injection")

    def test_a_tag_pinned_action(self) -> None:
        self.assertCaught(self.broken("actions/cache@55cc8345863c7cc4c66a329aec7e433d2d1c52a9 # v6.1.0", "actions/cache@v6"), "not pinned")

    def test_a_checkout_that_keeps_credentials(self) -> None:
        self.assertCaught(self.broken("          persist-credentials: false\n", "", 1), "persist-credentials")

    def test_a_floating_runner(self) -> None:
        self.assertCaught(self.broken("runs-on: ubuntu-24.04", "runs-on: ubuntu-latest"), "pinned runner")

    def test_a_job_without_a_timeout(self) -> None:
        self.assertCaught(self.broken("    timeout-minutes: 10\n    permissions:\n      contents: read\n    steps:\n      - name: Check out\n", "    permissions:\n      contents: read\n    steps:\n      - name: Check out\n"), "timeout")

    def test_a_missing_job(self) -> None:
        self.assertCaught(self.broken("  actionlint:\n", "  actionlint-renamed:\n"), "jobs are")

    def test_a_pull_request_run_that_would_cancel_main(self) -> None:
        self.assertCaught(self.broken("cancel-in-progress: ${{ github.event_name == 'pull_request' }}", "cancel-in-progress: true"), "cancel only pull request runs")


class BrokenDeploy(unittest.TestCase):
    def broken(self, old: str, new: str) -> list:
        self.assertIn(old, DEPLOY, f"the sample's anchor is gone: {old!r}")
        return rules.deploy_problems(DEPLOY.replace(old, new, 1))

    def assertCaught(self, problems: list, fragment: str) -> None:
        self.assertTrue(any(fragment in p for p in problems), f"{fragment!r} not in {problems}")

    def test_a_manual_trigger(self) -> None:
        self.assertCaught(self.broken("on:\n  workflow_call:\n", "on:\n  workflow_dispatch:\n  workflow_call:\n"), "must not use workflow_dispatch")

    def test_a_push_trigger(self) -> None:
        self.assertCaught(self.broken("on:\n  workflow_call:\n", "on:\n  push:\n  workflow_call:\n"), "must not use push")

    def test_dev_job_in_the_wrong_environment(self) -> None:
        self.assertCaught(self.broken("    environment: dev\n", "    environment: prod\n"), "environment must be dev")

    def test_prod_job_without_an_environment(self) -> None:
        self.assertCaught(self.broken("    environment: prod\n", ""), "environment must be prod")

    def test_concurrency_that_cancels(self) -> None:
        self.assertCaught(self.broken("      group: deploy-prod\n      cancel-in-progress: false\n", "      group: deploy-prod\n      cancel-in-progress: true\n"), "concurrency must be group deploy-prod")

    def test_prod_that_ignores_a_failed_dev(self) -> None:
        self.assertCaught(self.broken(" &&\n      (needs.apply-dev.result == 'success' || needs.apply-dev.result == 'skipped')", ""), "needs.apply-dev.result == 'success'")

    def test_prod_that_runs_when_cancelled(self) -> None:
        self.assertCaught(self.broken("!cancelled() &&\n      ", ""), "!cancelled()")

    def test_prod_that_does_not_wait_for_dev(self) -> None:
        self.assertCaught(self.broken("    needs: apply-dev\n", ""), "must need apply-dev")

    def test_dev_that_uses_the_prod_plan(self) -> None:
        self.assertCaught(self.broken("version-id: ${{ inputs.dev_version_id }}", "version-id: ${{ inputs.prod_version_id }}"), "from the dev plan only")

    def test_prod_that_uses_the_dev_hash(self) -> None:
        self.assertCaught(self.broken("sha256: ${{ inputs.prod_sha256 }}", "sha256: ${{ inputs.dev_sha256 }}"), "from the prod plan only")

    def test_a_checkout_that_is_not_the_planned_commit(self) -> None:
        self.assertCaught(self.broken("          ref: ${{ github.sha }}\n", "          ref: main\n"), "check out github.sha first")

    def test_the_secret_not_required(self) -> None:
        self.assertCaught(self.broken("        required: true\n\npermissions", "        required: false\n\npermissions"), "require the secret")

    def test_extra_permissions(self) -> None:
        self.assertCaught(self.broken("    permissions:\n      contents: read\n      id-token: write\n    steps:\n      # The commit", "    permissions:\n      contents: read\n      id-token: write\n      pull-requests: write\n    steps:\n      # The commit"), "unexpected permissions")


if __name__ == "__main__":
    unittest.main()
