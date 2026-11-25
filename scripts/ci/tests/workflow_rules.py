"""Rules for ci.yml and deploy.yml as functions over the file text, so the tests can run them on the real files
and on deliberately broken copies. Each returns a list of problems."""

from __future__ import annotations

import re
from typing import List

import actions_text as a
import guards

STATIC = ["guards", "tf-fmt", "tf-validate", "tf-test", "tflint", "checkov", "actionlint"]
CI_JOBS = ["kiro-not-ignored", "changes", *STATIC, "web", "plan-dev", "plan-prod", "deploy"]
OIDC_JOBS = {"plan-dev", "plan-prod", "deploy"}
DEPLOY_INPUTS = ["dev_has_changes", "dev_version_id", "dev_sha256", "prod_has_changes", "prod_version_id", "prod_sha256"]


def common_problems(text: str, path: str) -> List[str]:
    """Rules that hold for every workflow in this repository."""
    p: List[str] = []
    if not re.search(r"^permissions: \{\}\s*$", text, flags=re.M):
        p.append("top-level permissions must be {}")
    if re.search(r"pull_request_target", re.sub(r"(^|\s)#.*$", "", text, flags=re.M)):
        p.append("pull_request_target is not allowed (INF-OIDC-9)")
    p += [f.render() for f in guards.check_action_pins({path: text})]
    jobs = a.jobs_of(text)
    for name, job in jobs.items():
        perms = job["permissions"]
        if not perms:
            p.append(f"{name}: needs an explicit permissions block")
        if perms.get("contents") != "read":
            p.append(f"{name}: contents must be read")
        extra = set(perms) - {"contents", "id-token"}
        if extra:
            p.append(f"{name}: unexpected permissions {sorted(extra)}")
        if "id-token" in perms and perms["id-token"] != "write":
            p.append(f"{name}: id-token must be write when present")
        if "runs-on" in job["keys"] and not re.fullmatch(r"ubuntu-\d\d\.\d\d", job["keys"]["runs-on"]):
            p.append(f"{name}: runs-on must be a pinned runner image such as ubuntu-24.04")
        if "uses" not in job["keys"] and "timeout-minutes" not in job["keys"]:
            p.append(f"{name}: needs timeout-minutes")
        for step in job["steps"]:
            if "run" in step and "${{" in step["run"]:
                p.append(f"{name}: a run block interpolates an expression; use env (script injection)")
            if str(step.get("uses", "")).startswith("actions/checkout@") and step["with"].get("persist-credentials") != "false":
                p.append(f"{name}: checkout must set persist-credentials: false")
    return p


def ci_problems(text: str) -> List[str]:
    p = common_problems(text, ".github/workflows/ci.yml")
    head = text.split("\njobs:")[0]
    if not re.search(r"^on:\n  pull_request:\n  push:\n    branches: \[main\]\n", head, flags=re.M):
        p.append("ci.yml must trigger on pull_request and push to main only")
    head_code = re.sub(r"(^|\s)#.*$", "", head, flags=re.M)
    for banned in ("workflow_dispatch", "schedule:", "workflow_run", "pull_request_target"):
        if banned in head_code:
            p.append(f"ci.yml must not use {banned}")
    if "cancel-in-progress: ${{ github.event_name == 'pull_request' }}" not in head:
        p.append("ci.yml must cancel only pull request runs")
    jobs = a.jobs_of(text)
    if list(jobs) != CI_JOBS:
        p.append(f"jobs are {list(jobs)}, expected {CI_JOBS}")
        return p
    for name, job in jobs.items():
        has_id_token = "id-token" in job["permissions"]
        if has_id_token != (name in OIDC_JOBS):
            p.append(f"{name}: id-token: write belongs to exactly the plan jobs and deploy")
    # Decision T24: the workflow token reaches the tflint job only (plugin download, rate limit), read-only, with the
    # plugin cache restored before it. No other job may name it.
    holders = [name for name, job in jobs.items() if any("secrets.GITHUB_TOKEN" in line for line in job["lines"])]
    if holders != ["tflint"]:
        p.append(f"secrets.GITHUB_TOKEN may appear in the tflint job only, found in {holders}")
    else:
        tflint = jobs["tflint"]
        if tflint["permissions"] != {"contents": "read"}:
            p.append("tflint: permissions must be exactly contents: read")
        if sum(line.count("secrets.GITHUB_TOKEN") for line in tflint["lines"]) != 1:
            p.append("tflint: secrets.GITHUB_TOKEN must appear exactly once")
        if not any("actions/cache@" in s.get("uses", "") and "tflint.hcl" in "\n".join(tflint["lines"]) for s in tflint["steps"]):
            p.append("tflint: must restore a plugin cache keyed on infra/.tflint.hcl")
        step = next((s for s in tflint["steps"] if "local-checks.sh tflint" in s.get("run", "")), None)
        if step is None or step.get("env", {}).get("GITHUB_TOKEN") != "${{ secrets.GITHUB_TOKEN }}":
            p.append("tflint: the tflint step must set GITHUB_TOKEN in its own env")
    k = jobs["kiro-not-ignored"]
    if k["needs"] or "if" in k["keys"]:
        p.append("kiro-not-ignored must have no needs and no if (INF-KIRO-1)")
    if not any("check_kiro_not_ignored.py" in s.get("run", "") for s in k["steps"]):
        p.append("kiro-not-ignored must run check_kiro_not_ignored.py")
    c = jobs["changes"]
    if not any(s["with"].get("fetch-depth") == "0" for s in c["steps"]):
        p.append("changes needs fetch-depth: 0")
    if c["keys"].get("outputs") is None or "infra" not in c.get("outputs", {}):
        p.append("changes must output infra")
    if "web" not in c.get("outputs", {}):
        p.append("changes must output web")
    w = jobs["web"]
    if w["needs"] != ["changes"] or w["keys"].get("if") != "needs.changes.outputs.web == 'true'":
        p.append("web: must need changes only and run only when the web app changed")
    web_body = "\n".join(s.get("run", "") for s in w["steps"])
    for needle in ("npm ci", "npm run lint", "npm run format:check", "npm run typecheck", "git diff --exit-code -- web/lib/api/schema.d.ts", "npm test", "npm run build", "npm run check:build", "npm run lhci", "npm run build:e2e", "npm run e2e"):
        if needle not in web_body:
            p.append(f"web: must run {needle}")
    if any(re.search(r"aws|terraform|secrets\.", s.get("run", "") + str(s.get("env", ""))) for s in w["steps"]):
        p.append("web: must not touch AWS, Terraform or secrets")
    for name in STATIC:
        job = jobs[name]
        if job["needs"] != ["changes"]:
            p.append(f"{name}: must need changes only")
        if job["keys"].get("if") != "needs.changes.outputs.infra == 'true'":
            p.append(f"{name}: must run only when infra changed")
    wanted = {"guards": ["unittest discover -s scripts/ci/tests", "scripts/ci/guards.py"], "tflint": ["local-checks.sh tflint"], "checkov": ["local-checks.sh checkov"], "actionlint": ["local-checks.sh actionlint"], "tf-fmt": ["terraform fmt -check -recursive -diff infra"]}
    for name, needles in wanted.items():
        body = "\n".join(s.get("run", "") for s in jobs[name]["steps"])
        for needle in needles:
            if needle not in body:
                p.append(f"{name}: must run {needle}")
    for name in ("tf-validate", "tf-test"):
        body = "\n".join(s.get("run", "") for s in jobs[name]["steps"])
        if 'terraform -chdir="$ROOT" ' + name.split("-")[1] not in body:
            p.append(f"{name}: must run terraform {name.split('-')[1]} in the matrix root")
    for env in ("dev", "prod"):
        plan = jobs[f"plan-{env}"]
        if "environment" in plan["keys"]:
            p.append(f"plan-{env}: a plan job must have no environment (decision C2)")
        if sorted(plan["needs"]) != sorted(["changes", "kiro-not-ignored", *STATIC]):
            p.append(f"plan-{env}: must need every static job")
        cond = plan["keys"].get("if", "")
        for needle in ("needs.changes.outputs.infra == 'true'", "github.event_name == 'push'", "github.event.pull_request.head.repo.full_name == github.repository", "github.actor != 'dependabot[bot]'"):
            if needle not in cond:
                p.append(f"plan-{env}: the if must include {needle}")
        step = plan["steps"][-1]
        if step.get("uses") != "./.github/actions/terraform-plan" or step["with"].get("env") != env:
            p.append(f"plan-{env}: must call terraform-plan for {env}")
        if step["with"].get("upload") != "${{ github.event_name == 'push' && github.ref == 'refs/heads/main' }}":
            p.append(f"plan-{env}: a plan is stored only on a push to main")
        if step["with"].get("account-id") != "${{ secrets.AWS_ACCOUNT_ID }}":
            p.append(f"plan-{env}: the account ID must come from the secret")
        for key, var in (("aws-region", "AWS_REGION"), ("state-bucket", "TF_STATE_BUCKET"), ("state-kms-key-id", "TF_STATE_KMS_KEY_ID")):
            if step["with"].get(key) != "${{ vars." + var + " }}":
                p.append(f"plan-{env}: {key} must come from the variable {var}")
        want_out = {n: "${{ steps.plan.outputs." + n + " }}" for n in ("has_changes", "version_id", "sha256")}
        if plan.get("outputs") != want_out:
            p.append(f"plan-{env}: outputs must pass has_changes, version_id and sha256 through")
    d = jobs["deploy"]
    if d["keys"].get("uses") != "./.github/workflows/deploy.yml":
        p.append("deploy must call ./.github/workflows/deploy.yml")
    cond = d["keys"].get("if", "")
    for needle in ("github.event_name == 'push'", "github.ref == 'refs/heads/main'", "needs.plan-dev.outputs.has_changes == 'true'", "needs.plan-prod.outputs.has_changes == 'true'"):
        if needle not in cond:
            p.append(f"deploy: the if must include {needle}")
    if sorted(d["needs"]) != ["plan-dev", "plan-prod"]:
        p.append("deploy must need plan-dev and plan-prod")
    if d["secrets"] != {"AWS_ACCOUNT_ID": "${{ secrets.AWS_ACCOUNT_ID }}"}:
        p.append("deploy must pass exactly the secret AWS_ACCOUNT_ID, by name (never inherit)")
    if sorted(d["with"]) != sorted(DEPLOY_INPUTS):
        p.append("deploy must pass exactly the six plan inputs")
    for key in DEPLOY_INPUTS:
        env, name = key.split("_", 1)
        if d["with"].get(key) != "${{ needs.plan-" + env + ".outputs." + name + " }}":
            p.append(f"deploy: {key} must come from plan-{env}")
    return p


def deploy_problems(text: str) -> List[str]:
    p = common_problems(text, ".github/workflows/deploy.yml")
    head = text.split("\njobs:")[0]
    if not re.search(r"^on:\n  workflow_call:\n", head, flags=re.M):
        p.append("deploy.yml must be workflow_call")
    for banned in ("workflow_dispatch", "pull_request", "push:", "schedule:", "workflow_run"):
        if re.search(rf"^\s*{re.escape(banned)}", re.sub(r"(^|\s)#.*$", "", head, flags=re.M), flags=re.M):
            p.append(f"deploy.yml must not use {banned}")
    inputs = re.findall(r"^      ([a-z0-9_]+):\n        description", head.split("secrets:")[0], flags=re.M)
    if inputs != DEPLOY_INPUTS:
        p.append(f"inputs are {inputs}, expected {DEPLOY_INPUTS}")
    if "secrets:\n      AWS_ACCOUNT_ID:" not in head or "required: true" not in head.split("secrets:")[1]:
        p.append("deploy.yml must require the secret AWS_ACCOUNT_ID")
    jobs = a.jobs_of(text)
    if list(jobs) != ["apply-dev", "apply-prod"]:
        p.append(f"jobs are {list(jobs)}")
        return p
    for env in ("dev", "prod"):
        j = jobs[f"apply-{env}"]
        if j["keys"].get("environment") != env:
            p.append(f"apply-{env}: environment must be {env}")
        if j["permissions"] != {"contents": "read", "id-token": "write"}:
            p.append(f"apply-{env}: permissions must be contents read and id-token write")
        if j["concurrency"] != {"group": f"deploy-{env}", "cancel-in-progress": "false"}:
            p.append(f"apply-{env}: concurrency must be group deploy-{env} without cancelling")
        co = j["steps"][0]
        if not str(co.get("uses", "")).startswith("actions/checkout@") or co["with"].get("ref") != "${{ github.sha }}":
            p.append(f"apply-{env}: must check out github.sha first")
        step = j["steps"][1]
        if step.get("uses") != "./.github/actions/terraform-apply" or step["with"].get("env") != env:
            p.append(f"apply-{env}: must call terraform-apply for {env}")
        for key, source in (("version-id", f"version_id"), ("sha256", "sha256")):
            if step["with"].get(key) != "${{ inputs." + env + "_" + source + " }}":
                p.append(f"apply-{env}: {key} must come from the {env} plan only")
        if step["with"].get("account-id") != "${{ secrets.AWS_ACCOUNT_ID }}":
            p.append(f"apply-{env}: account-id must come from the secret")
    if jobs["apply-dev"]["needs"] or "inputs.dev_has_changes == 'true'" != jobs["apply-dev"]["keys"].get("if"):
        p.append("apply-dev: runs when the dev plan has changes, and needs nothing")
    prod = jobs["apply-prod"]
    cond = prod["keys"].get("if", "")
    if prod["needs"] != ["apply-dev"]:
        p.append("apply-prod must need apply-dev only")
    for needle in ("!cancelled()", "inputs.prod_has_changes == 'true'", "needs.apply-dev.result == 'success'", "needs.apply-dev.result == 'skipped'"):
        if needle not in cond:
            p.append(f"apply-prod: the if must include {needle}")
    return p
