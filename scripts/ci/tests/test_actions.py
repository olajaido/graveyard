"""The composite actions (infra-foundation T15.2; INF-CI-6, INF-CI-7, INF-CI-12..14, INF-VER-3, INF-VER-4, decision C5).

Static rules read the files. Execution tests run the actual `run:` scripts with fake `terraform` and `aws`
executables, so the verify step is seen refusing on every mismatch and the plan, upload and init steps are
seen doing what the design says. Nothing here touches AWS, a network or a real Terraform.
"""

from __future__ import annotations

import fnmatch
import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import Dict, Optional

from helpers import PLACEHOLDER, REPO_ROOT  # noqa: F401  (helpers fixes sys.path)

import actions_text as a
import guards

TOOLS = all(shutil.which(t) for t in ("sha256sum", "jq", "bash"))
SHA = "0123456789abcdef" * 4
KEY_ID = "00000000-0000-0000-0000-000000000000"


class Static(unittest.TestCase):
    def setUp(self) -> None:
        self.texts = {n: (a.ACTIONS / n / "action.yml").read_text(encoding="utf-8") for n in ("terraform-init", "terraform-plan", "terraform-apply")}
        self.steps = {n: a.action_steps(n) for n in self.texts}

    def test_every_third_party_action_is_pinned_by_sha(self) -> None:
        files = {f".github/actions/{n}/action.yml": t for n, t in self.texts.items()}
        self.assertEqual(guards.check_action_pins(files), [])
        uses = re.findall(r"uses:\s*(\S+)", "".join(self.texts.values()))
        self.assertTrue(any("@" in u for u in uses) and any(u.startswith("./") for u in uses))

    def test_the_pins_are_the_ones_the_design_recorded(self) -> None:
        design = (REPO_ROOT / ".kiro/specs/infra-foundation/design.md").read_text(encoding="utf-8")
        for text in self.texts.values():
            for ref in re.findall(r"uses:\s*([\w./-]+@[0-9a-f]{40})", text):
                self.assertIn(ref.split("@")[1], design, ref)

    def test_no_run_block_interpolates_an_expression(self) -> None:
        # Values reach a script only through env:, never through ${{ }} text (script injection).
        for name, steps in self.steps.items():
            for s in steps:
                if "run" in s:
                    self.assertNotIn("${{", s["run"], f"{name}: {s.get('name')}")

    def test_every_run_step_uses_bash_and_every_used_variable_is_declared(self) -> None:
        builtin = {"HOME", "GITHUB_OUTPUT", "GITHUB_ENV", "GITHUB_STEP_SUMMARY", "PATH"}
        for name, steps in self.steps.items():
            for s in steps:
                if "run" not in s:
                    continue
                self.assertEqual(s.get("shell"), "bash", f"{name}: {s.get('name')}")
                local = set(re.findall(r"^\s*(?:local\s+)?([A-Za-z_][A-Za-z0-9_]*)=", s["run"], flags=re.M))
                for var in set(re.findall(r"\$\{?([A-Z][A-Z0-9_]+)", s["run"])):
                    self.assertTrue(var in s["env"] or var in builtin or var in local, f"{name}: {s.get('name')}: ${var} is not declared in env")

    def test_no_plan_or_artifact_upload_anywhere(self) -> None:
        # Plans never go to an artifact. The one exception is the public web build of infra-edge (a.artifact_problems).
        for p in (REPO_ROOT / ".github").rglob("*.yml"):
            rel = p.relative_to(REPO_ROOT).as_posix()
            self.assertEqual(a.artifact_problems(rel, p.read_text(encoding="utf-8")), [], rel)

    def test_init_rules(self) -> None:
        text = self.texts["terraform-init"]
        self.assertIn("terraform_wrapper: false", text)
        self.assertEqual(text.count("-lockfile=readonly"), 2)
        self.assertIn("infra/.tool-versions", text)
        self.assertIn("hashFiles('infra/**/.terraform.lock.hcl')", text)
        self.assertIn("TF_PLUGIN_CACHE_DIR=", text)
        self.assertIn("mask-aws-account-id: true", text)
        self.assertIn("allowed-account-ids: ${{ inputs.account-id }}", text)
        self.assertIn("role-duration-seconds: 3600", text)
        self.assertIn("role-to-assume: arn:aws:iam::${{ inputs.account-id }}:role/${{ inputs.role }}", text)
        self.assertNotIn("backend-config=bucket", text)

    def test_the_plan_gets_the_zone_id_as_a_terraform_variable(self) -> None:
        plan = a.step_named(self.steps["terraform-plan"], "Plan")
        self.assertEqual(plan["env"]["TF_VAR_route53_zone_id"], "${{ inputs.route53-zone-id }}")
    def test_plan_rules(self) -> None:
        plan = a.step_named(self.steps["terraform-plan"], "Plan")
        self.assertIn("-detailed-exitcode", plan["run"])
        self.assertIn('-out="$PLANFILE"', plan["run"])
        upload = a.step_named(self.steps["terraform-plan"], "Store the plan")
        self.assertEqual(upload["if"], "inputs.upload == 'true' && steps.plan.outputs.has_changes == 'true'")
        for needle in ("--server-side-encryption aws:kms", "--checksum-algorithm SHA256", "--ssekms-key-id \"$key_arn\"", "--metadata \"commit-sha=${COMMIT_SHA},run-id=${RUN_ID},env=${ENV_NAME}\"", '--key "plans/${RUN_ID}/${ENV_NAME}.tfplan"'):
            self.assertIn(needle, upload["run"])
        cleanup = a.step_named(self.steps["terraform-plan"], "Delete the local plan file")
        self.assertEqual(cleanup["if"], "always()")
        summary = a.step_named(self.steps["terraform-plan"], "job summary")
        self.assertIn('sed -e "s/$ACCOUNT_ID/<account>/g" -e "s/$ZONE_ID/<zone>/g"', summary["run"])
        self.assertIn("head -c 900000", summary["run"])

    def test_apply_rules(self) -> None:
        steps = self.steps["terraform-apply"]
        names = [str(s.get("name")) for s in steps]
        fetch, verify, apply = (next(i for i, n in enumerate(names) if frag in n) for frag in ("Fetch the saved plan", "Verify the saved plan", "Apply the saved plan"))
        self.assertLess(fetch, verify)
        self.assertLess(verify, apply)
        run = a.step_named(steps, "Verify")["run"]
        self.assertEqual(run.count("|| fail"), 4)
        for needle in ("EXPECTED_SHA256", "COMMIT_SHA", "RUN_ID", "ENV_NAME", "commit-sha", "run-id"):
            self.assertIn(needle, run)
        self.assertIn("exit 1", run)
        apply_run = a.step_named(steps, "Apply the saved plan")["run"]
        self.assertIn('apply -input=false -lock-timeout=5m "$PLANFILE"', apply_run)
        for s in steps:
            if "run" in s and s is not a.step_named(steps, "Apply the saved plan"):
                self.assertNotRegex(s["run"], r"terraform[^\n]* apply")
        fetch_run = a.step_named(steps, "Fetch the saved plan")["run"]
        self.assertIn('--version-id "$VERSION_ID"', fetch_run)

    def test_apply_uses_the_apply_role_of_its_own_env(self) -> None:
        init = a.step_named(self.steps["terraform-apply"], "Initialise with the apply role")
        self.assertEqual(init["with"]["role"], "graveyard-ci/graveyard-${{ inputs.env }}-apply")
        plan_init = a.step_named(self.steps["terraform-plan"], "Initialise with the plan role")
        self.assertEqual(plan_init["with"]["role"], "graveyard-ci/graveyard-plan")

    def test_names_agree_with_the_iam_module(self) -> None:
        core = (REPO_ROOT / "infra/modules/github-oidc/policies_apply_core.tf").read_text(encoding="utf-8")
        module = (REPO_ROOT / "infra/modules/github-oidc/apply_roles.tf").read_text(encoding="utf-8")
        plan_role = (REPO_ROOT / "infra/modules/github-oidc/plan_role.tf").read_text(encoding="utf-8")
        self.assertIn('name                 = "graveyard-${each.key}-apply"', module)
        self.assertIn('name                 = "graveyard-plan"', plan_role)
        # The key the plan action writes is covered by the pattern the apply role may read, and not by another env's.
        key = "plans/${RUN_ID}/${ENV_NAME}.tfplan"
        self.assertIn('plans/*/${e}.tfplan', core)
        for env in ("dev", "prod"):
            concrete = key.replace("${RUN_ID}", "123456").replace("${ENV_NAME}", env)
            self.assertTrue(fnmatch.fnmatchcase(concrete, f"plans/*/{env}.tfplan"))
            other = "prod" if env == "dev" else "dev"
            self.assertFalse(fnmatch.fnmatchcase(concrete, f"plans/*/{other}.tfplan"))

    def test_the_default_region_and_the_input_names_match_the_design(self) -> None:
        for name, text in self.texts.items():
            self.assertIn("default: eu-west-2", text, name)
        self.assertEqual(sorted(re.findall(r"^  ([a-z0-9-]+):", re.search(r"^inputs:\n(.*?)^\S", self.texts["terraform-apply"], flags=re.S | re.M).group(1), flags=re.M)),
                         ["account-id", "aws-region", "env", "sha256", "state-bucket", "state-kms-key-id", "version-id"])


class Shims:
    """Fake terraform and aws executables that record their arguments and behave as told."""

    def __init__(self, tmp: Path) -> None:
        self.bin = tmp / "bin"
        self.bin.mkdir()
        self.log = tmp / "calls.log"
        self.log.write_text("")

    def make(self, name: str, body: str) -> None:
        path = self.bin / name
        path.write_text("#!/bin/bash\n" + body)
        path.chmod(path.stat().st_mode | stat.S_IEXEC)

    def calls(self) -> list:
        return [line for line in self.log.read_text().splitlines() if line]


@unittest.skipUnless(TOOLS, "needs sha256sum, jq and bash on PATH (they are on the CI runners)")
class Execution(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_ctx = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp_ctx.cleanup)
        self.tmp = Path(self.tmp_ctx.name)
        self.shims = Shims(self.tmp)
        self.out, self.env_file, self.summary = self.tmp / "out", self.tmp / "env", self.tmp / "summary"
        for f in (self.out, self.env_file, self.summary):
            f.write_text("")

    def run_step(self, action: str, fragment: str, env: Dict[str, str], cwd: Optional[Path] = None, script: Optional[str] = None) -> subprocess.CompletedProcess:
        step = a.step_named(a.action_steps(action), fragment)
        if script is not None:
            step = {"run": script}
        full = {
            "PATH": f"{self.shims.bin}:{os.environ.get('PATH', '')}",
            "HOME": str(self.tmp),
            "GITHUB_OUTPUT": str(self.out),
            "GITHUB_ENV": str(self.env_file),
            "GITHUB_STEP_SUMMARY": str(self.summary),
            "CALLS": str(self.shims.log),
            **env,
        }
        # The way GitHub runs `shell: bash`: errexit and pipefail are on before the script starts. Running with plain
        # `bash -c` hid a bug: a nonzero exit of the plan command ended the step before its own exit-code check.
        return subprocess.run(["bash", "--noprofile", "--norc", "-e", "-o", "pipefail", "-c", step["run"]], env=full, cwd=cwd or self.tmp, capture_output=True, text=True)

    def outputs(self) -> Dict[str, str]:
        return dict(line.split("=", 1) for line in self.out.read_text().splitlines() if "=" in line)

    # ---- verify
    def prepare_plan(self, content: bytes = b"plan bytes", meta: Optional[dict] = None) -> Dict[str, str]:
        plan, metafile = self.tmp / "dev.tfplan", self.tmp / "dev.tfplan.meta.json"
        plan.write_bytes(content)
        sha = subprocess.run(["sha256sum", str(plan)], capture_output=True, text=True).stdout.split()[0]
        metafile.write_text(json.dumps(meta if meta is not None else {"commit-sha": "c0ffee", "run-id": "42", "env": "dev"}))
        return {"ENV_NAME": "dev", "EXPECTED_SHA256": sha, "COMMIT_SHA": "c0ffee", "RUN_ID": "42", "PLANFILE": str(plan), "META_FILE": str(metafile)}

    def test_verify_accepts_a_matching_plan(self) -> None:
        done = self.run_step("terraform-apply", "Verify", self.prepare_plan())
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("matches", done.stdout)

    def test_verify_refuses_each_mismatch(self) -> None:
        cases = {
            "tampered plan": (lambda e: e.update(EXPECTED_SHA256="f" * 64), "SHA-256"),
            "another commit": (lambda e: e.update(COMMIT_SHA="deadbeef"), "another commit"),
            "another run": (lambda e: e.update(RUN_ID="43"), "another run"),
            "another env": (lambda e: e.update(ENV_NAME="prod"), "another env"),
        }
        for label, (mutate, message) in cases.items():
            with self.subTest(label):
                env = self.prepare_plan()
                mutate(env)
                done = self.run_step("terraform-apply", "Verify", env)
                self.assertEqual(done.returncode, 1, label)
                self.assertIn(message, done.stderr)
                self.assertIn("refusing to apply", done.stderr)

    def test_verify_refuses_metadata_that_is_missing_or_empty(self) -> None:
        for label, meta in {"empty object": {}, "no commit": {"run-id": "42", "env": "dev"}, "no env": {"commit-sha": "c0ffee", "run-id": "42"}, "null": {"commit-sha": None, "run-id": "42", "env": "dev"}}.items():
            with self.subTest(label):
                done = self.run_step("terraform-apply", "Verify", self.prepare_plan(meta=meta))
                self.assertEqual(done.returncode, 1, label)

    def test_verify_refuses_when_the_plan_file_was_replaced_after_the_hash(self) -> None:
        env = self.prepare_plan()
        Path(env["PLANFILE"]).write_bytes(b"another plan, same metadata")
        self.assertEqual(self.run_step("terraform-apply", "Verify", env).returncode, 1)

    # ---- input checks
    def test_apply_input_checks(self) -> None:
        good = {"ENV_NAME": "prod", "VERSION_ID": "3HL4kqtJlcpXroDTDmJ.rmSpXd3dIN", "EXPECTED_SHA256": SHA}
        self.assertEqual(self.run_step("terraform-apply", "Check the inputs", good).returncode, 0)
        for label, patch in {
            "env staging": {"ENV_NAME": "staging"},
            "env empty": {"ENV_NAME": ""},
            "version id with a space": {"VERSION_ID": "a b"},
            "version id with a quote": {"VERSION_ID": 'a"b'},
            "version id empty": {"VERSION_ID": ""},
            "sha too short": {"EXPECTED_SHA256": SHA[:-1]},
            "sha uppercase": {"EXPECTED_SHA256": SHA.upper()},
            "sha with a command": {"EXPECTED_SHA256": SHA + "; rm -rf /"},
        }.items():
            with self.subTest(label):
                self.assertEqual(self.run_step("terraform-apply", "Check the inputs", {**good, **patch}).returncode, 1, label)

    def test_plan_env_check(self) -> None:
        for env, code in (("dev", 0), ("prod", 0), ("prod; id", 1), ("", 1), ("DEV", 1)):
            self.assertEqual(self.run_step("terraform-plan", "Check the env name", {"ENV_NAME": env}).returncode, code, env)

    # ---- plan exit codes
    def plan_with_exit(self, code: int, script: Optional[str] = None) -> subprocess.CompletedProcess:
        """Run the Plan step, as GitHub runs it, with a fake terraform that exits with `code`."""
        self.shims.make("terraform", f'echo "$@" >> "$CALLS"\nexit {code}\n')
        self.out.write_text("")
        return self.run_step("terraform-plan", "Plan", {"ENV_NAME": "dev", "PLANFILE": str(self.tmp / "dev.tfplan")}, script=script)
    def test_plan_exit_code_0_is_success_without_changes(self) -> None:
        done = self.plan_with_exit(0)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(self.outputs(), {"has_changes": "false"})
    def test_plan_exit_code_2_is_success_with_changes(self) -> None:
        # -detailed-exitcode: 2 means "succeeded, there are changes". It must not fail the step.
        done = self.plan_with_exit(2)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(self.outputs(), {"has_changes": "true"})
    def test_plan_any_other_exit_code_fails_the_step_with_that_code_and_no_output(self) -> None:
        for code in (1, 3, 127):
            done = self.plan_with_exit(code)
            self.assertEqual(done.returncode, code, f"exit {code}: {done.stderr}")
            self.assertEqual(self.outputs(), {}, code)
            self.assertIn(f"exit code {code}", done.stderr)
    def test_plan_runs_terraform_with_the_expected_flags(self) -> None:
        self.plan_with_exit(0)
        call = self.shims.calls()[-1]
        for flag in ("-chdir=infra/envs/dev", "plan", "-input=false", "-lock-timeout=5m", "-detailed-exitcode", f"-out={self.tmp}/dev.tfplan"):
            self.assertIn(flag, call)
    def test_the_plan_step_is_run_with_errexit_in_these_tests(self) -> None:
        # The harness must keep the GitHub flags, or the bare `terraform plan; code=$?` bug would pass again.
        self.assertIn('"--noprofile", "--norc", "-e", "-o", "pipefail"', Path(__file__).read_text(encoding="utf-8"))
    # ---- mutations of the Plan step: each must be seen failing by the tests above
    def test_a_plan_step_that_treats_exit_code_2_as_a_failure_is_caught(self) -> None:
        step = a.step_named(a.action_steps("terraform-plan"), "Plan")["run"]
        self.assertIn("2) has_changes=true ;;", step)
        bad = step.replace("2) has_changes=true ;;", '2) echo "changes" >&2; exit 1 ;;')
        done = self.plan_with_exit(2, script=bad)
        self.assertNotEqual(done.returncode, 0, "the mutant must fail on exit code 2, which the real step passes")
    def test_a_plan_step_that_reads_the_code_after_errexit_is_caught(self) -> None:
        # The original bug: with errexit on, the bare command ends the step on exit code 2 before `code=$?` is read.
        step = a.step_named(a.action_steps("terraform-plan"), "Plan")["run"]
        self.assertIn('|| code=$?', step)
        bad = step.replace("code=0\n", "").replace(' || code=$?', "\n        code=$?")
        bad = "\n".join(line.lstrip() if line.startswith("        ") else line for line in bad.splitlines()) + "\n"
        self.assertNotEqual(bad, step)
        done = self.plan_with_exit(2, script=bad)
        self.assertNotEqual(done.returncode, 0, "the mutant must fail on exit code 2")
        self.assertEqual(self.outputs(), {})
    def test_a_plan_step_that_swallows_real_errors_is_caught(self) -> None:
        step = a.step_named(a.action_steps("terraform-plan"), "Plan")["run"]
        bad = step.replace('*) echo "terraform plan failed with exit code $code" >&2; exit "$code" ;;', "*) has_changes=false ;;")
        self.assertNotEqual(bad, step)
        done = self.plan_with_exit(1, script=bad)
        self.assertEqual(done.returncode, 0, "the mutant must wrongly succeed on exit code 1")
        self.assertNotEqual(self.outputs(), {}, "so the tests above, which expect a failure and no output, would catch it")
    # ---- summary
    def test_summary_masks_the_account_and_is_cut_at_900_kb(self) -> None:
        self.shims.make("terraform", f'echo "arn:aws:iam::{PLACEHOLDER}:role/x and {PLACEHOLDER}"\nhead -c 1200000 /dev/zero | tr "\\0" "a"\n')
        done = self.run_step("terraform-plan", "job summary", {"ENV_NAME": "dev", "ACCOUNT_ID": PLACEHOLDER, "ZONE_ID": "Z0123456789ABCDEFGHIJ", "PLANFILE": str(self.tmp / "dev.tfplan"), "RAW_TEXT": str(self.tmp / "raw.txt"), "MASKED_TEXT": str(self.tmp / "masked.txt")})
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertFalse((self.tmp / "raw.txt").exists() or (self.tmp / "masked.txt").exists())
        text = self.summary.read_text()
        self.assertNotIn(PLACEHOLDER, text)
        self.assertIn("<account>", text)
        self.assertLess(len(text), 900_200)
        self.assertGreater(len(text), 899_000)
        self.assertIn("Terraform plan: dev", text)

    # ---- upload
    def upload_env(self, **patch: str) -> Dict[str, str]:
        plan = self.tmp / "dev.tfplan"
        plan.write_bytes(b"binary plan")
        return {"ENV_NAME": "dev", "ACCOUNT_ID": PLACEHOLDER, "REGION": "eu-west-2", "STATE_BUCKET": "graveyard-tfstate-abcd1234", "STATE_KEY_ID": KEY_ID,
                "PLANFILE": str(plan), "COMMIT_SHA": "c0ffee", "RUN_ID": "42", **patch}

    def test_upload_writes_the_plan_with_sse_kms_the_exact_key_and_the_three_metadata_keys(self) -> None:
        self.shims.make("aws", 'printf "%s\\n" "$*" >> "$CALLS"\necho 3HL4kqtJ.rmSpXd3dIN\n')
        done = self.run_step("terraform-plan", "Store the plan", self.upload_env())
        self.assertEqual(done.returncode, 0, done.stderr)
        out = self.outputs()
        self.assertEqual(out["version_id"], "3HL4kqtJ.rmSpXd3dIN")
        self.assertEqual(out["sha256"], subprocess.run(["sha256sum", str(self.tmp / "dev.tfplan")], capture_output=True, text=True).stdout.split()[0])
        call = self.shims.calls()[0]
        for needle in ("s3api put-object", "--bucket graveyard-tfstate-abcd1234", "--key plans/42/dev.tfplan", "--server-side-encryption aws:kms",
                       f"--ssekms-key-id arn:aws:kms:eu-west-2:{PLACEHOLDER}:key/{KEY_ID}", "--checksum-algorithm SHA256",
                       "--metadata commit-sha=c0ffee,run-id=42,env=dev", "--query VersionId"):
            self.assertIn(needle, call)

    def test_upload_fails_when_the_bucket_returns_no_version_id(self) -> None:
        for answer in ("None", ""):
            self.shims.make("aws", f'echo "{answer}"\n')
            self.assertEqual(self.run_step("terraform-plan", "Store the plan", self.upload_env()).returncode, 1, answer)

    def test_upload_fails_when_the_cli_fails(self) -> None:
        self.shims.make("aws", "exit 255\n")
        self.assertEqual(self.run_step("terraform-plan", "Store the plan", self.upload_env()).returncode, 255 % 256)

    # ---- fetch and apply
    def test_fetch_asks_for_the_exact_version_of_this_runs_plan(self) -> None:
        self.shims.make("aws", 'printf "%s\\n" "$*" >> "$CALLS"\necho "{}"\n')
        env = {"ENV_NAME": "prod", "VERSION_ID": "v1.2", "STATE_BUCKET": "graveyard-tfstate-abcd1234", "RUN_ID": "42", "PLANFILE": str(self.tmp / "prod.tfplan"), "META_FILE": str(self.tmp / "m.json")}
        done = self.run_step("terraform-apply", "Fetch the saved plan", env)
        self.assertEqual(done.returncode, 0, done.stderr)
        call = self.shims.calls()[0]
        for needle in ("s3api get-object", "--key plans/42/prod.tfplan", "--version-id v1.2", "--query Metadata", str(self.tmp / "prod.tfplan")):
            self.assertIn(needle, call)

    def test_apply_applies_the_saved_plan_file_and_nothing_else(self) -> None:
        self.shims.make("terraform", 'echo "$@" >> "$CALLS"\n')
        done = self.run_step("terraform-apply", "Apply the saved plan", {"ENV_NAME": "dev", "PLANFILE": str(self.tmp / "dev.tfplan")})
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(self.shims.calls(), [f"-chdir=infra/envs/dev apply -input=false -lock-timeout=5m {self.tmp}/dev.tfplan"])

    # ---- init
    def test_backend_init_keeps_the_account_off_the_command_line(self) -> None:
        self.shims.make("terraform", 'echo "$@" >> "$CALLS"\n')
        env = {"ROOT": "infra/envs/dev", "ACCOUNT_ID": PLACEHOLDER, "REGION": "eu-west-2", "STATE_BUCKET": "graveyard-tfstate-abcd1234", "STATE_KEY_ID": KEY_ID, "BACKEND_FILE": str(self.tmp / "backend.hcl")}
        done = self.run_step("terraform-init", "S3 backend", env)
        self.assertEqual(done.returncode, 0, done.stderr)
        call = self.shims.calls()[0]
        self.assertEqual(call, f"-chdir=infra/envs/dev init -input=false -lockfile=readonly -backend-config={self.tmp}/backend.hcl")
        self.assertNotIn(PLACEHOLDER, call)
        self.assertNotIn(PLACEHOLDER, done.stdout + done.stderr)
        text = (self.tmp / "backend.hcl").read_text()
        self.assertIn('bucket     = "graveyard-tfstate-abcd1234"', text)
        self.assertIn(f'kms_key_id = "arn:aws:kms:eu-west-2:{PLACEHOLDER}:key/{KEY_ID}"', text)
        self.assertIn(f'TF_VAR_allowed_account_ids=["{PLACEHOLDER}"]', self.env_file.read_text())

    def test_backend_init_refuses_missing_values(self) -> None:
        self.shims.make("terraform", 'echo "$@" >> "$CALLS"\n')
        base = {"ROOT": "infra/envs/dev", "ACCOUNT_ID": PLACEHOLDER, "REGION": "eu-west-2", "STATE_BUCKET": "graveyard-tfstate-abcd1234", "STATE_KEY_ID": KEY_ID, "BACKEND_FILE": str(self.tmp / "b.hcl")}
        for missing in ("ACCOUNT_ID", "STATE_BUCKET", "STATE_KEY_ID"):
            with self.subTest(missing):
                done = self.run_step("terraform-init", "S3 backend", {**base, missing: ""})
                self.assertEqual(done.returncode, 1)
        self.assertEqual(self.shims.calls(), [])

    def test_init_without_a_backend(self) -> None:
        self.shims.make("terraform", 'echo "$@" >> "$CALLS"\n')
        done = self.run_step("terraform-init", "without a backend", {"ROOT": "infra/modules/state"})
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(self.shims.calls(), ["-chdir=infra/modules/state init -backend=false -input=false -lockfile=readonly"])

    def test_the_version_step_reads_the_tool_versions_file(self) -> None:
        (self.tmp / "infra").mkdir()
        (self.tmp / "infra" / ".tool-versions").write_text("terraform 1.17.2\ntflint 0.66.0\n")
        done = self.run_step("terraform-init", "pinned Terraform version", {})
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(self.outputs(), {"terraform": "1.17.2"})
        (self.tmp / "infra" / ".tool-versions").write_text("terraform latest\n")
        self.assertEqual(self.run_step("terraform-init", "pinned Terraform version", {}).returncode, 1)
        (self.tmp / "infra" / ".tool-versions").write_text("tflint 0.66.0\n")
        self.assertEqual(self.run_step("terraform-init", "pinned Terraform version", {}).returncode, 1)

    def test_the_cleanup_steps_delete_the_plan_files(self) -> None:
        plan, meta = self.tmp / "dev.tfplan", self.tmp / "dev.tfplan.meta.json"
        plan.write_bytes(b"x")
        meta.write_text("{}")
        self.assertEqual(self.run_step("terraform-apply", "Delete the local plan files", {"PLANFILE": str(plan), "META_FILE": str(meta)}).returncode, 0)
        self.assertFalse(plan.exists() or meta.exists())
        plan.write_bytes(b"x")
        self.assertEqual(self.run_step("terraform-plan", "Delete the local plan file", {"PLANFILE": str(plan)}).returncode, 0)
        self.assertFalse(plan.exists())


class StaticBadSamples(unittest.TestCase):
    """The static rules must fail on a modified copy, so they cannot pass vacuously."""

    def test_the_step_reader_finds_what_it_should(self) -> None:
        text = "runs:\n  using: composite\n  steps:\n    - name: One\n      shell: bash\n      env:\n        A: x\n      run: |\n        echo $A\n    - name: Two\n      uses: a/b@" + "a" * 40 + "\n"
        steps = a.steps_of(text)
        self.assertEqual([s["name"] for s in steps], ["One", "Two"])
        self.assertEqual(steps[0]["run"], "echo $A\n")
        self.assertEqual(steps[0]["env"], {"A": "x"})

    def test_an_interpolated_run_block_would_be_caught(self) -> None:
        steps = a.steps_of("    - name: Bad\n      shell: bash\n      run: |\n        echo ${{ inputs.env }}\n")
        self.assertIn("${{", steps[0]["run"])

    def test_a_tag_pinned_action_is_caught(self) -> None:
        self.assertNotEqual(guards.check_action_pins({".github/actions/x/action.yml": "      - uses: actions/cache@v6\n"}), [])


if __name__ == "__main__":
    unittest.main()
