"""Rules for scripts/ci/local-checks.sh (infra-foundation T2.4, design section 0).

The script is the only way the agent runs Terraform and the linters, so it must stay
inside the working rule: no cloud credentials, no state backend, no host environment,
images pinned by digest, versions equal to infra/.tool-versions.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
SCRIPT = REPO / "scripts" / "ci" / "local-checks.sh"
TOOL_VERSIONS = REPO / "infra" / ".tool-versions"

FORBIDDEN_SUBSTRINGS = ("AWS_", ".aws", "backend-config", "--env-file")
FORBIDDEN_SUBCOMMAND = re.compile(r"\b(plan|apply|destroy|import|refresh)\b")
ENV_FORWARD = re.compile(r"(?<![\w-])-e\s+[A-Za-z_]\w*(?![\w=])")
# The one approved exception to "no host variable" (decision T24): the tflint container of `tflint --init`, on a CI
# runner, gets GITHUB_TOKEN. The block must be exactly this, once, and the switch may be set only on that one call.
TOKEN_EXCEPTION = (
    '  if [ "${FORWARD_GITHUB_TOKEN:-}" = "1" ] && [ "$image" = "$TFLINT_IMAGE" ] && [ "${CI:-}" = "true" ] && [ -n "${GITHUB_TOKEN:-}" ]; then\n'
    "    token_args=(-e GITHUB_TOKEN)\n"
    "  fi\n"
)
TOKEN_SWITCH = re.compile(r"^.*\bFORWARD_GITHUB_TOKEN=1\b.*$", re.MULTILINE)
IMAGE_ASSIGN = re.compile(r'^([A-Z]+_IMAGE)="([^"]*)"$', re.MULTILINE)
DOCKER_RUN_LINE = re.compile(r"^\s*docker run\b.*$", re.MULTILINE)
RUN_IN_CALL = re.compile(r'\brun_in\s+"\$([A-Za-z_]+)"')
SHA_REF = re.compile(r"@sha256:[0-9a-f]{64}$")


def violations(text: str) -> list[str]:
    """Every rule broken by the script text, as short messages."""
    found: list[str] = []
    for needle in FORBIDDEN_SUBSTRINGS:
        if needle in text:
            found.append(f"contains {needle!r}")
    if FORBIDDEN_SUBCOMMAND.search(text):
        found.append("names a state-changing or backend Terraform subcommand")
    if text.count(TOKEN_EXCEPTION) > 1:
        found.append("the GITHUB_TOKEN exception appears more than once")
    # Remove the approved block, then no other -e NAME may remain. A different variable, a weaker condition or a
    # second copy is therefore a violation.
    if ENV_FORWARD.search(text.replace(TOKEN_EXCEPTION, "")):
        found.append("forwards a host variable with -e NAME")
    if "-e GITHUB_TOKEN" in text and TOKEN_EXCEPTION not in text:
        found.append("forwards GITHUB_TOKEN outside the approved exception")
    switches = TOKEN_SWITCH.findall(text)
    if TOKEN_EXCEPTION in text and len(switches) != 1:
        found.append(f"FORWARD_GITHUB_TOKEN=1 must be set on exactly one call, found {len(switches)}")
    for line in switches:
        if "TFLINT_IMAGE" not in line or "--init" not in line:
            found.append("FORWARD_GITHUB_TOKEN=1 is set on a call other than tflint --init")
    images = IMAGE_ASSIGN.findall(text)
    if len(images) != 4:
        found.append(f"expected 4 *_IMAGE assignments, found {len(images)}")
    for name, ref in images:
        if not SHA_REF.search(ref):
            found.append(f"{name} is not pinned by digest")
    runs = DOCKER_RUN_LINE.findall(text)
    if len(runs) != 1:
        found.append(f"expected exactly one docker run line, found {len(runs)}")
    for line in runs:
        if '"$image"' not in line:
            found.append("docker run line does not use the image parameter")
    image_names = {name for name, _ in images}
    for var in RUN_IN_CALL.findall(text):
        if var not in image_names:
            found.append(f"run_in called with {var}, which is not a pinned *_IMAGE")
    return found


def image_versions(text: str) -> dict[str, str]:
    """tool name -> version, from the *_IMAGE assignments."""
    names = {
        "TERRAFORM_IMAGE": "terraform",
        "TFLINT_IMAGE": "tflint",
        "CHECKOV_IMAGE": "checkov",
        "ACTIONLINT_IMAGE": "actionlint",
    }
    out: dict[str, str] = {}
    for var, ref in IMAGE_ASSIGN.findall(text):
        tag = ref.split("@", 1)[0].rsplit(":", 1)[1]
        out[names[var]] = tag.removeprefix("v")
    return out


def tool_versions(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) == 2:
            out[parts[0]] = parts[1]
    return out


class RealScript(unittest.TestCase):
    def setUp(self) -> None:
        self.text = SCRIPT.read_text(encoding="utf-8")

    def test_script_has_no_violations(self) -> None:
        self.assertEqual(violations(self.text), [])

    def test_image_versions_equal_tool_versions(self) -> None:
        wanted = tool_versions(TOOL_VERSIONS.read_text(encoding="utf-8"))
        got = image_versions(self.text)
        for name in ("terraform", "tflint", "checkov", "actionlint"):
            self.assertEqual(got[name], wanted[name], name)

    def test_script_is_executable_and_strict(self) -> None:
        self.assertTrue(SCRIPT.stat().st_mode & 0o111, "not executable")
        self.assertIn("set -euo pipefail", self.text)
        self.assertTrue(self.text.startswith("#!/usr/bin/env bash"))

    def test_only_offline_subcommands_are_offered(self) -> None:
        for sub in ("fmt", "validate", "test", "tflint", "checkov", "actionlint", "guards", "lock", "all"):
            self.assertRegex(self.text, rf"\b{sub}\)")


class BadSamples(unittest.TestCase):
    """Each rule must fire on a modified copy, so the guard cannot pass vacuously."""

    def setUp(self) -> None:
        self.text = SCRIPT.read_text(encoding="utf-8")

    def assert_fires(self, bad: str, fragment: str) -> None:
        self.assertTrue(
            any(fragment in message for message in violations(bad)),
            f"expected a violation containing {fragment!r}, got {violations(bad)}",
        )

    def test_aws_variable_name(self) -> None:
        self.assert_fires(self.text + "\n# AWS_PROFILE=x\n", "AWS_")

    def test_aws_config_directory(self) -> None:
        self.assert_fires(self.text + '\nmount="$HOME/.aws"\n', ".aws")

    def test_backend_config(self) -> None:
        self.assert_fires(self.text + "\nx=-backend-config=backend.hcl\n", "backend-config")

    def test_env_file(self) -> None:
        self.assert_fires(self.text + "\nx=--env-file\n", "--env-file")

    def test_state_changing_subcommand(self) -> None:
        for word in ("plan", "apply", "destroy", "import", "refresh"):
            with self.subTest(word=word):
                self.assert_fires(self.text + f"\ntf infra {word}\n", "subcommand")

    def test_forwarded_host_variable(self) -> None:
        bad = self.text.replace("-e HOME=/tmp", "-e HOME", 1)
        self.assertNotEqual(bad, self.text)
        self.assert_fires(bad, "forwards a host variable")

    def test_forwarded_host_variable_is_found_even_in_a_new_line(self) -> None:
        self.assert_fires(self.text + "\ndocker_extra='-e GITHUB_TOKEN'\n", "forwards a host variable")

    def test_the_approved_github_token_exception_is_present_and_allowed(self) -> None:
        self.assertIn(TOKEN_EXCEPTION, self.text)
        self.assertEqual(violations(self.text), [])
    def test_forwarding_a_different_variable_fails(self) -> None:
        for name in ("GH_TOKEN", "GITHUB_PAT", "AWS_REGION", "HOME", "GITHUB_TOKEN2"):
            with self.subTest(name=name):
                bad = self.text.replace("token_args=(-e GITHUB_TOKEN)", f"token_args=(-e {name})", 1)
                self.assertNotEqual(bad, self.text)
                self.assertTrue(violations(bad), name)
    def test_forwarding_a_second_variable_next_to_the_token_fails(self) -> None:
        bad = self.text.replace("token_args=(-e GITHUB_TOKEN)", "token_args=(-e GITHUB_TOKEN -e GH_TOKEN)", 1)
        self.assert_fires(bad, "forwards a host variable")
    def test_the_token_exception_without_the_ci_condition_fails(self) -> None:
        bad = self.text.replace(' && [ "${CI:-}" = "true" ]', "", 1)
        self.assertNotEqual(bad, self.text)
        self.assert_fires(bad, "forwards")
    def test_the_token_exception_for_any_image_fails(self) -> None:
        bad = self.text.replace(' && [ "$image" = "$TFLINT_IMAGE" ]', "", 1)
        self.assertNotEqual(bad, self.text)
        self.assert_fires(bad, "forwards")
    def test_a_second_copy_of_the_exception_fails(self) -> None:
        self.assert_fires(self.text + "\n" + TOKEN_EXCEPTION, "more than once")
    def test_the_switch_on_another_call_fails(self) -> None:
        bad = self.text.replace('  tf infra fmt -check', '  FORWARD_GITHUB_TOKEN=1 tf infra fmt -check', 1)
        self.assertNotEqual(bad, self.text)
        self.assert_fires(bad, "exactly one call")
    def test_the_switch_on_a_non_init_tflint_call_fails(self) -> None:
        bad = self.text.replace('    run_in "$TFLINT_IMAGE" "" cache -- "--chdir=/repo/$d" "$config"\n', '    FORWARD_GITHUB_TOKEN=1 run_in "$TFLINT_IMAGE" "" cache -- "--chdir=/repo/$d" "$config"\n', 1)
        self.assertNotEqual(bad, self.text)
        self.assert_fires(bad, "exactly one call")
    def test_literal_env_values_are_allowed(self) -> None:
        self.assertEqual(ENV_FORWARD.findall("-e TF_IN_AUTOMATION=1 -e HOME=/tmp"), [])

    def test_image_without_digest(self) -> None:
        bad = re.sub(r"(TFLINT_IMAGE=\"[^\"@]*)@sha256:[0-9a-f]{64}", r"\1", self.text, count=1)
        self.assertNotEqual(bad, self.text)
        self.assert_fires(bad, "TFLINT_IMAGE is not pinned by digest")

    def test_latest_tag_without_digest(self) -> None:
        bad = self.text + '\nEXTRA_IMAGE="hashicorp/terraform:latest"\n'
        self.assert_fires(bad, "EXTRA_IMAGE is not pinned by digest")

    def test_second_docker_run(self) -> None:
        self.assert_fires(self.text + "\ndocker run --rm busybox true\n", "exactly one docker run line")

    def test_run_in_with_unpinned_image(self) -> None:
        self.assert_fires(self.text + '\nrun_in "$OTHER" x nocache -- true\n', "not a pinned *_IMAGE")

    def test_version_mismatch_is_detected(self) -> None:
        wanted = tool_versions("terraform 1.0.0\n")
        self.assertNotEqual(image_versions(self.text)["terraform"], wanted["terraform"])


if __name__ == "__main__":
    unittest.main()
