"""The bootstrap root and the module directories (infra-foundation T12; INF-BOOT-1, INF-COST-6, INF-VER-2, INF-STATE-7)."""

from __future__ import annotations

import re
import unittest

from helpers import REPO_ROOT  # noqa: F401  (helpers fixes sys.path)

import infra_text as t

BOOT = t.INFRA / "bootstrap"
MODULES = {"state": {"aws": "6.73.0", "random": "3.9.1"}, "github-oidc": {"aws": "6.73.0"}, "cost": {"aws": "6.73.0"}}


class Bootstrap(unittest.TestCase):
    def setUp(self) -> None:
        self.files = t.read_dir(BOOT)
        self.main = self.files["main.tf"]

    def test_backend_pins_and_provider(self) -> None:
        self.assertEqual(t.backend_problems(self.files["versions.tf"], "bootstrap/terraform.tfstate"), [])
        self.assertEqual(t.provider_pin_problems(self.files["versions.tf"]), [])
        self.assertEqual(t.required_version_problems(self.files["versions.tf"]), [])
        self.assertEqual(t.provider_problems(self.files["providers.tf"]), [])
        self.assertEqual(t.variable_problems(self.files["variables.tf"]), [])

    def test_the_root_declares_no_resource_and_only_reads_the_caller_identity(self) -> None:
        for name, text in self.files.items():
            if name.endswith(".tf"):
                self.assertEqual(t.resource_blocks(text), [], name)
        self.assertEqual(sorted(t.data_blocks(self.main)), ["aws_caller_identity", "aws_partition"])

    def test_the_three_modules_are_called_from_their_hyphenated_directories(self) -> None:
        self.assertEqual(re.findall(r'module\s+"([^"]+)"\s*\{', self.main), ["state", "github_oidc", "cost"])
        self.assertEqual(re.findall(r'source\s*=\s*"([^"]+)"', self.main), ["../modules/state", "../modules/github-oidc", "../modules/cost"])

    def test_the_key_policy_gets_the_role_resources_arns(self) -> None:
        self.assertIn("plan  = module.github_oidc.plan_role_arn", self.main)
        self.assertIn("apply = module.github_oidc.apply_role_arns", self.main)

    def test_the_project_tag_has_one_source(self) -> None:
        locals_text = self.files["locals.tf"]
        self.assertIn('project_tag_key   = "Project"', locals_text)
        self.assertIn('project_tag_value = "graveyard"', locals_text)
        self.assertIn("{ (local.project_tag_key) = local.project_tag_value }", locals_text)
        self.assertIn("project_tag_key                   = local.project_tag_key", self.main)
        self.assertIn("project_tag_value                 = local.project_tag_value", self.main)
        self.assertEqual(t.tag_problems(locals_text.replace("{ (local.project_tag_key) = local.project_tag_value },", 'Project = "graveyard"').replace("env = \"shared\"", "env = \"dev\""), "dev") != [], True)

    def test_env_tag_is_shared_and_other_tags_match_the_prd(self) -> None:
        locals_text = self.files["locals.tf"]
        self.assertIn('env = "shared"', locals_text)
        for key, value in t.PRD_TAGS.items():
            if key != "Project":
                self.assertRegex(locals_text, rf'{key}\s*=\s*"{re.escape(value)}"')

    def test_oidc_provider_default_is_false_in_the_root_and_the_module(self) -> None:
        module_vars = (t.INFRA / "modules" / "github-oidc" / "variables.tf").read_text()
        self.assertEqual(t.default_of(self.files["variables.tf"], "create_oidc_provider"), "false")
        self.assertEqual(t.default_of(module_vars, "create_oidc_provider"), "false")

    def test_root_defaults_equal_module_defaults(self) -> None:
        module_vars = (t.INFRA / "modules" / "github-oidc" / "variables.tf").read_text()
        for name in ("bedrock_narrate_profile_id", "bedrock_rites_profile_id", "bedrock_foundation_model_regions"):
            self.assertEqual(t.default_of(self.files["variables.tf"], name), t.default_of(module_vars, name), name)
            self.assertNotIn("*", t.default_of(self.files["variables.tf"], name))
        cost_vars = (t.INFRA / "modules" / "cost" / "variables.tf").read_text()
        for name in ("budget_limit", "anomaly_monitor_name", "anomaly_threshold_amount", "activate_cost_allocation_tag_keys"):
            self.assertEqual(t.default_of(self.files["variables.tf"], name), t.default_of(cost_vars, name), name)

    def test_bedrock_defaults_are_the_prd_profiles_and_the_seven_routing_regions(self) -> None:
        text = self.files["variables.tf"]
        self.assertEqual(t.default_of(text, "bedrock_narrate_profile_id"), '"eu.anthropic.claude-haiku-5-5"')
        self.assertEqual(t.default_of(text, "bedrock_rites_profile_id"), '"eu.anthropic.claude-sonnet-5-5"')
        regions = re.findall(r'"(eu-[a-z]+-\d)"', t.default_of(text, "bedrock_foundation_model_regions"))
        self.assertEqual(sorted(regions), ["eu-central-1", "eu-north-1", "eu-south-1", "eu-south-2", "eu-west-1", "eu-west-2", "eu-west-3"])

    def test_no_secret_or_account_values_are_committed(self) -> None:
        for name in ("terraform.tfvars.example", "backend.hcl.example"):
            self.assertIn("123456789012", self.files[name])
        self.assertNotIn("terraform.tfvars", self.files)
        self.assertNotIn("backend.hcl", self.files)

    def test_lock_files_of_the_root_and_every_module(self) -> None:
        self.assertEqual(t.lock_problems(self.files[".terraform.lock.hcl"], {"aws": "6.73.0", "random": "3.9.1"}), [])
        for module, providers in MODULES.items():
            text = (t.INFRA / "modules" / module / ".terraform.lock.hcl").read_text()
            self.assertEqual(t.lock_problems(text, providers), [], module)

    def test_every_module_pins_providers_exactly(self) -> None:
        for module in MODULES:
            text = (t.INFRA / "modules" / module / "versions.tf").read_text()
            self.assertEqual(t.provider_pin_problems(text), [], module)
            self.assertEqual(t.required_version_problems(text), [], module)

    def test_module_variables_have_types_and_descriptions(self) -> None:
        for module in MODULES:
            self.assertEqual(t.variable_problems((t.INFRA / "modules" / module / "variables.tf").read_text()), [], module)

    def test_every_module_has_tests(self) -> None:
        for module in MODULES:
            self.assertTrue(list((t.INFRA / "modules" / module / "tests").glob("*.tftest.hcl")), module)

    def test_tool_versions_file(self) -> None:
        lines = dict(line.split() for line in (t.INFRA / ".tool-versions").read_text().splitlines() if line.strip())
        self.assertEqual(lines, {"terraform": "1.17.2", "tflint": "0.66.0", "checkov": "3.4.5", "actionlint": "1.7.12"})


if __name__ == "__main__":
    unittest.main()
