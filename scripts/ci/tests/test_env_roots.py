"""The dev and prod roots (infra-foundation T13.2; INF-LAY-2..4, INF-STATE-5..7, INF-TAG-1..2, INF-CFG-2, INF-REG-1)."""

from __future__ import annotations

import re
import unittest

from helpers import REPO_ROOT  # noqa: F401  (helpers fixes sys.path)

import infra_text as t


class EnvRoots(unittest.TestCase):
    def setUp(self) -> None:
        self.files = {e: t.read_dir(t.INFRA / "envs" / e) for e in t.ENV_ROOTS}

    def test_the_two_roots_have_the_same_files(self) -> None:
        self.assertEqual(sorted(self.files["dev"]), sorted(self.files["prod"]))
        self.assertTrue({"versions.tf", "providers.tf", "locals.tf", "variables.tf", "main.tf", "backend.hcl.example", "terraform.tfvars.example", ".terraform.lock.hcl"} <= set(self.files["dev"]))

    def test_the_roots_differ_only_in_the_env_name(self) -> None:
        for name, text in self.files["dev"].items():
            if name == ".terraform.lock.hcl":
                continue
            self.assertEqual(re.sub(r"\bdev\b", "prod", text), self.files["prod"][name], name)

    def test_the_roots_declare_no_resource_and_no_data_source(self) -> None:
        for env, files in self.files.items():
            for name, text in files.items():
                if name.endswith(".tf"):
                    self.assertEqual(t.resource_blocks(text), [], f"{env}/{name}")
                    self.assertEqual(t.data_blocks(text), [], f"{env}/{name}")

    def test_backend_blocks(self) -> None:
        for env, files in self.files.items():
            self.assertEqual(t.backend_problems(files["versions.tf"], f"envs/{env}/terraform.tfstate"), [], env)

    def test_pins_and_versions(self) -> None:
        for env, files in self.files.items():
            self.assertEqual(t.provider_pin_problems(files["versions.tf"]), [], env)
            self.assertEqual(t.required_version_problems(files["versions.tf"]), [], env)
            self.assertIn('version = "= 6.73.0"', re.sub(r"\s+", " ", files["versions.tf"]))

    def test_tags(self) -> None:
        for env, files in self.files.items():
            self.assertEqual(t.tag_problems(files["locals.tf"], env), [], env)
            self.assertIn('name_prefix = "graveyard-${local.env}"', files["locals.tf"])

    def test_provider_and_variables(self) -> None:
        for env, files in self.files.items():
            self.assertEqual(t.provider_problems(files["providers.tf"]), [], env)
            self.assertEqual(t.variable_problems(files["variables.tf"]), [], env)

    def test_lock_files(self) -> None:
        for env, files in self.files.items():
            self.assertEqual(t.lock_problems(files[".terraform.lock.hcl"], {"aws": "6.73.0"}), [], env)

    def test_examples_use_the_placeholder_only(self) -> None:
        for env, files in self.files.items():
            self.assertIn("123456789012", files["terraform.tfvars.example"])
            self.assertNotIn("graveyard-tfstate-", files["terraform.tfvars.example"])
            self.assertIn("kms_key_id", files["backend.hcl.example"])


class BadSamples(unittest.TestCase):
    """Every rule must fail on a bad sample, so none of them can pass vacuously."""

    GOOD_BACKEND = 'terraform {\n  backend "s3" {\n    key          = "envs/dev/terraform.tfstate"\n    region       = "eu-west-2"\n    use_lockfile = true\n    encrypt      = true\n  }\n}\n'

    def test_good_backend_passes(self) -> None:
        self.assertEqual(t.backend_problems(self.GOOD_BACKEND, "envs/dev/terraform.tfstate"), [])

    def test_backend_rules(self) -> None:
        cases = {
            "wrong key": self.GOOD_BACKEND.replace("envs/dev", "envs/prod"),
            "no lockfile": self.GOOD_BACKEND.replace("use_lockfile = true", "use_lockfile = false"),
            "no encryption": self.GOOD_BACKEND.replace("encrypt      = true", "encrypt      = false"),
            "bucket named": self.GOOD_BACKEND.replace("    encrypt", '    bucket = "graveyard-tfstate-abcd"\n    encrypt'),
            "kms arn named": self.GOOD_BACKEND.replace("    encrypt", '    kms_key_id = "arn"\n    encrypt'),
            "lock table": self.GOOD_BACKEND.replace("    encrypt", '    dynamodb_table = "locks"\n    encrypt'),
            "wrong region": self.GOOD_BACKEND.replace("eu-west-2", "us-east-1"),
            "no backend": "terraform {}\n",
        }
        for label, text in cases.items():
            with self.subTest(label):
                self.assertNotEqual(t.backend_problems(text, "envs/dev/terraform.tfstate"), [])

    def test_a_commented_bucket_is_not_a_bucket(self) -> None:
        text = self.GOOD_BACKEND.replace("    encrypt", '    # bucket = "x"\n    encrypt')
        self.assertEqual(t.backend_problems(text, "envs/dev/terraform.tfstate"), [])

    def test_pin_rules(self) -> None:
        good = 'aws = {\n source  = "hashicorp/aws"\n version = "= 6.73.0"\n}\n'
        self.assertEqual(t.provider_pin_problems(good), [])
        for bad in ("~> 6.0", ">= 6.73.0", "6.73.0", "latest", "= 6.73"):
            with self.subTest(bad):
                self.assertNotEqual(t.provider_pin_problems(good.replace("= 6.73.0", bad)), [])

    def test_resource_and_data_rules(self) -> None:
        self.assertEqual(t.resource_blocks('resource "aws_s3_bucket" "x" {}'), ["aws_s3_bucket"])
        self.assertEqual(t.data_blocks('data "aws_partition" "p" {}'), ["aws_partition"])
        self.assertEqual(t.resource_blocks('# resource "aws_s3_bucket" "x" {}'), [])

    def test_tag_rules(self) -> None:
        good = 'locals {\n  env = "dev"\n  tags = {\n    Project    = "graveyard"\n    Env        = local.env\n    Owner      = "olajide"\n    ManagedBy  = "terraform"\n    CostCentre = "kiroween-2026"\n    Repo       = "github.com/olajaido/graveyard"\n  }\n}\n'
        self.assertEqual(t.tag_problems(good, "dev"), [])
        for label, bad in {
            "Environment instead of Env": good.replace("Env  ", "Environment"),
            "missing Repo": good.replace('    Repo       = "github.com/olajaido/graveyard"\n', ""),
            "wrong case": good.replace('"graveyard"', '"Graveyard"'),
            "extra tag": good.replace("  }\n}", '    Extra = "x"\n  }\n}'),
            "wrong env": good.replace('env = "dev"', 'env = "prod"'),
        }.items():
            with self.subTest(label):
                self.assertNotEqual(t.tag_problems(bad, "dev"), [])

    def test_provider_rules(self) -> None:
        good = 'provider "aws" {\n  region              = var.region\n  allowed_account_ids = var.allowed_account_ids\n\n  default_tags {\n    tags = local.tags\n  }\n}\n'
        self.assertEqual(t.provider_problems(good), [])
        self.assertNotEqual(t.provider_problems(good.replace("allowed_account_ids = var.allowed_account_ids", "")), [])
        self.assertNotEqual(t.provider_problems(good.replace("tags = local.tags", "tags = {}")), [])

    def test_variable_rules(self) -> None:
        good = 'variable "region" {\n  type = string\n  description = "x"\n  validation {\n    condition = true\n    error_message = "x"\n  }\n}\n'
        self.assertEqual(t.variable_problems(good), [])
        self.assertNotEqual(t.variable_problems(good.replace("  type = string\n", "")), [])
        self.assertNotEqual(t.variable_problems(good.replace('  description = "x"\n', "")), [])
        self.assertNotEqual(t.variable_problems(good.replace("validation", "other")), [])

    def test_lock_rules(self) -> None:
        good = 'provider "registry.terraform.io/hashicorp/aws" {\n  version     = "6.73.0"\n  constraints = "= 6.73.0"\n  hashes = [\n    "h1:a",\n    "h1:b",\n    "zh:c",\n  ]\n}\n'
        self.assertEqual(t.lock_problems(good, {"aws": "6.73.0"}), [])
        self.assertNotEqual(t.lock_problems(good, {"aws": "6.74.0"}), [])
        self.assertNotEqual(t.lock_problems(good, {"random": "3.9.1"}), [])
        self.assertNotEqual(t.lock_problems(good.replace('    "zh:c",\n', ""), {"aws": "6.73.0"}), [])


if __name__ == "__main__":
    unittest.main()
