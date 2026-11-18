"""Small text rules for Terraform files, shared by the root tests. Standard library only.

Each rule takes the text of a file and returns a list of problems, so the tests can run it on the real files
and on bad samples (a rule that never fails is worthless).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List

REPO = Path(__file__).resolve().parents[3]
INFRA = REPO / "infra"
ENV_ROOTS = ("dev", "prod")
PRD_TAGS = {
    "Project": "graveyard",
    "Owner": "olajide",
    "ManagedBy": "terraform",
    "CostCentre": "kiroween-2026",
    "Repo": "github.com/olajaido/graveyard",
}


def code(text: str) -> str:
    """Text without # and // comments."""
    return "\n".join(re.sub(r"(^|\s)(#|//).*$", r"\1", line) for line in text.splitlines())


def read_dir(path: Path) -> Dict[str, str]:
    return {p.name: p.read_text(encoding="utf-8") for p in sorted(path.iterdir()) if p.is_file()}


def backend_problems(text: str, key: str) -> List[str]:
    """The s3 backend block must hold the state key, the region, use_lockfile and encrypt, and nothing that names the account."""
    problems: List[str] = []
    match = re.search(r'backend\s+"s3"\s*\{(.*?)\n  \}', code(text), flags=re.S)
    if not match:
        return ["no backend \"s3\" block"]
    body = match.group(1)
    want = {"key": f'"{key}"', "region": '"eu-west-2"', "use_lockfile": "true", "encrypt": "true"}
    for name, value in want.items():
        if not re.search(rf"^\s*{name}\s*=\s*{re.escape(value)}\s*$", body, flags=re.M):
            problems.append(f"backend {name} must be {value}")
    for forbidden in ("bucket", "kms_key_id", "dynamodb_table", "role_arn", "profile", "access_key", "secret_key", "account_id"):
        if re.search(rf"^\s*{forbidden}\s*=", body, flags=re.M):
            problems.append(f"backend must not set {forbidden} (INF-STATE-7, INF-STATE-5)")
    return problems


def provider_pin_problems(text: str) -> List[str]:
    """Every provider in required_providers has an exact version: `= x.y.z` (INF-VER-2)."""
    problems: List[str] = []
    for match in re.finditer(r'source\s*=\s*"hashicorp/([a-z]+)"\s*\n\s*version\s*=\s*"([^"]*)"', code(text)):
        if not re.fullmatch(r"= \d+\.\d+\.\d+", match.group(2)):
            problems.append(f"provider {match.group(1)} version {match.group(2)!r} is not an exact pin")
    return problems


def required_version_problems(text: str) -> List[str]:
    if '>= 1.10, < 2.0' not in code(text):
        return ['required_version must be ">= 1.10, < 2.0" (INF-VER-1)']
    return []


def resource_blocks(text: str) -> List[str]:
    return re.findall(r'^\s*resource\s+"([^"]+)"', code(text), flags=re.M)


def data_blocks(text: str) -> List[str]:
    return re.findall(r'^\s*data\s+"([^"]+)"', code(text), flags=re.M)


def tag_problems(text: str, env: str) -> List[str]:
    """locals must hold exactly the PRD tag set, with Env as given."""
    problems: List[str] = []
    match = re.search(r"tags\s*=\s*\{(.*?)\n  \}", code(text), flags=re.S)
    if not match:
        return ["no tags map in locals"]
    found = dict(re.findall(r'^\s*([A-Za-z]+)\s*=\s*"([^"]*)"\s*$', match.group(1), flags=re.M))
    found["Env"] = "local.env" if re.search(r"^\s*Env\s*=\s*local\.env\s*$", match.group(1), flags=re.M) else found.get("Env", "")
    expected = dict(PRD_TAGS, Env="local.env")
    if found != expected:
        problems.append(f"tags {found} differ from the PRD set {expected}")
    if not re.search(rf'^\s*env\s*=\s*"{env}"\s*$', code(text), flags=re.M):
        problems.append(f'locals env must be "{env}"')
    return problems


def provider_problems(text: str) -> List[str]:
    problems: List[str] = []
    body = code(text)
    if "allowed_account_ids = var.allowed_account_ids" not in re.sub(r"\s+", " ", body).replace("allowed_account_ids  =", "allowed_account_ids ="):
        problems.append("the provider must set allowed_account_ids from var.allowed_account_ids (INF-CFG-2)")
    if not re.search(r"default_tags\s*\{\s*tags\s*=\s*local\.tags\s*\}", body):
        problems.append("the provider must set default_tags from local.tags (INF-TAG-1)")
    return problems


def variable_problems(text: str) -> List[str]:
    """Every variable has a type and a description (INF-CFG-4); region is validated to eu-west-2 (INF-REG-1)."""
    problems: List[str] = []
    for match in re.finditer(r'variable\s+"([^"]+)"\s*\{(.*?)\n\}', code(text), flags=re.S):
        name, body = match.groups()
        if not re.search(r"^\s*type\s*=", body, flags=re.M):
            problems.append(f"variable {name} has no type")
        if not re.search(r"^\s*description\s*=", body, flags=re.M):
            problems.append(f"variable {name} has no description")
        if name == "region" and "validation" not in body:
            problems.append("variable region has no validation (INF-REG-1)")
        if name == "allowed_account_ids" and "validation" not in body:
            problems.append("variable allowed_account_ids has no validation")
    return problems


def default_of(text: str, variable: str) -> str:
    """The text of a variable's default, whitespace collapsed."""
    match = re.search(rf'variable\s+"{variable}"\s*\{{(.*?)\n\}}', code(text), flags=re.S)
    if not match:
        return ""
    default = re.search(r"default\s*=\s*(.*?)\n\s*description", match.group(1), flags=re.S)
    return re.sub(r"\s+", " ", default.group(1)).strip() if default else ""


def lock_problems(text: str, providers: Dict[str, str]) -> List[str]:
    problems: List[str] = []
    for name, version in providers.items():
        block = re.search(rf'provider "registry\.terraform\.io/hashicorp/{name}" \{{(.*?)\n\}}', text, flags=re.S)
        if not block:
            problems.append(f"lock file has no {name} provider")
            continue
        if f'version     = "{version}"' not in block.group(1):
            problems.append(f"lock file pins {name} to another version than {version}")
        hashes = len(re.findall(r'"(?:h1|zh):', block.group(1)))
        if hashes < 3:
            problems.append(f"lock file has only {hashes} hashes for {name}")
    return problems
