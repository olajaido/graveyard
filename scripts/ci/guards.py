#!/usr/bin/env python3
"""Repository guards for the infrastructure files (infra-foundation, design section 9).

Checks (each one is a subcommand; `all` is the default):

  account-ids       no AWS account ID, and no ARN with an account ID, in infra files
  tracked-files     no state, plan, backend or override file in the repository
  workflow-triggers no workflow uses the pull_request_target trigger
  action-pins       every third-party action is pinned by a full commit SHA
  module-policies   no data source in a module and no aws_iam_policy_document in infra/

The file list is `git ls-files --cached --others --exclude-standard`: tracked files plus new
files that are not git-ignored, which is what a commit would contain. On a CI checkout that
is exactly the tracked set. Git-ignored local files (terraform.tfvars, backend.hcl) are not
scanned.

Standard library only. Exit codes: 0 pass, 1 findings, 2 usage or git error.
Findings go to stderr as `<check>: <path>:<line>: <reason>`.
"""

from __future__ import annotations

import fnmatch
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence

# The AWS documentation placeholder account. Built from two parts so that this file does not
# contain a 12-digit number itself.
PLACEHOLDER_ACCOUNT = "123456789" + "012"

ACCOUNT_SCAN_PREFIXES = ("infra/", ".github/", "scripts/ci/", "docs/runbooks/")
ACCOUNT_SCAN_SUFFIXES = (".tf", ".hcl")
PLACEHOLDER_ALLOWED_SUFFIXES = (".tftest.hcl", ".example")
PLACEHOLDER_ALLOWED_PREFIXES = ("scripts/ci/tests/",)

ACCOUNT_ID = re.compile(r"(?<![0-9A-Za-z])[0-9]{12}(?![0-9A-Za-z])")
# A UUID (a KMS key ID, for example) can end in a group of 12 digits. It is not an account ID.
UUID = re.compile(r"(?<![0-9A-Za-z])[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}(?![0-9A-Za-z])")
ARN_WITH_ACCOUNT = re.compile(r"arn:aws[a-z-]*:[a-z0-9-]*:[a-z0-9-]*:([0-9]{12}):")

FORBIDDEN_TRACKED = (
    "*.tfstate",
    "*.tfstate.*",
    "*.tfplan",
    "backend.hcl",
    "*_override.tf",
    "terraform.tfvars",
)

PULL_REQUEST_TARGET = re.compile(r"\bpull_request_target\b")
USES_LINE = re.compile(r"^\s*(?:-\s*)?uses:\s*(\S+)")
SHA_PIN = re.compile(r"^[^@\s]+@[0-9a-f]{40}$")
DOCKER_PIN = re.compile(r"^docker://[^@\s]+@sha256:[0-9a-f]{64}$")
DATA_BLOCK = re.compile(r'^\s*data\s+"')

COMMENT = re.compile(r"(^|\s)(#|//).*$")


@dataclass(frozen=True)
class Finding:
    check: str
    path: str
    line: int
    reason: str

    def render(self) -> str:
        return f"{self.check}: {self.path}:{self.line}: {self.reason}"


Files = Dict[str, str]


def strip_comment(line: str) -> str:
    """Remove a trailing or whole-line # or // comment (comment start at line start or after space)."""
    return COMMENT.sub(r"\1", line)


def _git(root: Path, *args: str) -> bytes:
    done = subprocess.run(["git", *args], cwd=root, capture_output=True, check=False)
    if done.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {done.stderr.decode(errors='replace').strip()}")
    return done.stdout


def repository_root(start: Path) -> Path:
    out = _git(start, "rev-parse", "--show-toplevel").decode().strip()
    return Path(out)


def load_files(root: Path) -> Files:
    """Path (POSIX, relative) -> text, for tracked plus new non-ignored files. Binary files are skipped."""
    raw = _git(root, "ls-files", "-z", "--cached", "--others", "--exclude-standard")
    files: Files = {}
    for name in raw.decode("utf-8", errors="surrogateescape").split("\0"):
        if not name:
            continue
        path = root / name
        if not path.is_file() or path.is_symlink():
            files[name] = ""
            continue
        data = path.read_bytes()
        if b"\0" in data[:8000]:
            files[name] = ""
            continue
        files[name] = data.decode("utf-8", errors="replace")
    return files


def _basename(path: str) -> str:
    return path.rsplit("/", 1)[-1]


def _in_account_scope(path: str) -> bool:
    base = _basename(path)
    return (
        path.startswith(ACCOUNT_SCAN_PREFIXES)
        or base.endswith(ACCOUNT_SCAN_SUFFIXES)
        or ".tfvars" in base
    )


def _placeholder_allowed(path: str) -> bool:
    return path.endswith(PLACEHOLDER_ALLOWED_SUFFIXES) or path.startswith(PLACEHOLDER_ALLOWED_PREFIXES)


def check_account_ids(files: Files) -> List[Finding]:
    found: List[Finding] = []
    for path, text in sorted(files.items()):
        if not _in_account_scope(path):
            continue
        for number, raw_line in enumerate(text.splitlines(), 1):
            line = UUID.sub(" ", raw_line)
            reported = False
            for match in ARN_WITH_ACCOUNT.finditer(line):
                if match.group(1) == PLACEHOLDER_ACCOUNT and _placeholder_allowed(path):
                    continue
                found.append(Finding("account-ids", path, number, "ARN contains an AWS account ID"))
                reported = True
                break
            if reported:
                continue
            for match in ACCOUNT_ID.finditer(line):
                if match.group(0) == PLACEHOLDER_ACCOUNT and _placeholder_allowed(path):
                    continue
                found.append(Finding("account-ids", path, number, "looks like an AWS account ID (12 digits)"))
                break
    return found


def check_tracked_files(files: Files) -> List[Finding]:
    found: List[Finding] = []
    for path in sorted(files):
        base = _basename(path)
        for pattern in FORBIDDEN_TRACKED:
            if fnmatch.fnmatchcase(base, pattern):
                found.append(Finding("tracked-files", path, 1, f"file matches {pattern}; it must not be committed"))
                break
    return found


def check_workflow_triggers(files: Files) -> List[Finding]:
    found: List[Finding] = []
    for path, text in sorted(files.items()):
        if not path.startswith(".github/workflows/") or not path.endswith((".yml", ".yaml")):
            continue
        for number, line in enumerate(text.splitlines(), 1):
            if PULL_REQUEST_TARGET.search(strip_comment(line)):
                found.append(Finding("workflow-triggers", path, number, "pull_request_target is not allowed"))
    return found


def check_action_pins(files: Files) -> List[Finding]:
    found: List[Finding] = []
    for path, text in sorted(files.items()):
        if not path.startswith(".github/") or not path.endswith((".yml", ".yaml")):
            continue
        for number, line in enumerate(text.splitlines(), 1):
            match = USES_LINE.match(strip_comment(line))
            if not match:
                continue
            ref = match.group(1).strip("'\"")
            if ref.startswith("./"):
                continue
            if ref.startswith("docker://"):
                if not DOCKER_PIN.match(ref):
                    found.append(Finding("action-pins", path, number, f"{ref} is not pinned by an sha256 digest"))
                continue
            if not SHA_PIN.match(ref):
                found.append(Finding("action-pins", path, number, f"{ref} is not pinned by a 40-character commit SHA"))
    return found


def _strip_block_comments(text: str) -> str:
    return re.sub(r"/\*.*?\*/", lambda m: "\n" * m.group(0).count("\n"), text, flags=re.DOTALL)


def check_module_policies(files: Files) -> List[Finding]:
    found: List[Finding] = []
    for path, text in sorted(files.items()):
        if not path.startswith("infra/") or not path.endswith(".tf"):
            continue
        in_module = path.startswith("infra/modules/")
        for number, line in enumerate(_strip_block_comments(text).splitlines(), 1):
            code = strip_comment(line)
            if "aws_iam_policy_document" in code:
                found.append(Finding("module-policies", path, number, "aws_iam_policy_document is not allowed; use jsonencode in locals"))
            if in_module and DATA_BLOCK.match(code):
                found.append(Finding("module-policies", path, number, "a module must not declare a data source; pass the value in as a variable"))
    return found


# IAM: "Resource vendor must be fully qualified and cannot contain regexes". The partition and service segments of an
# ARN in a policy may be a literal or an interpolation, never contain * or ? (found when CreatePolicy rejected the
# apply guards). Interpolations are checked by the terraform tests, which see the rendered JSON.
ARN_HEAD = re.compile(r'"arn:((?:\$\{[^}]*\}|[^:"$])*):((?:\$\{[^}]*\}|[^:"$])*)(?=[:"])')
INTERPOLATION = re.compile(r"\$\{[^}]*\}")
def check_arn_segments(files: Files) -> List[Finding]:
    found: List[Finding] = []
    for path, text in sorted(files.items()):
        if not path.startswith("infra/") or not path.endswith(".tf"):
            continue
        for number, line in enumerate(_strip_block_comments(text).splitlines(), 1):
            for match in ARN_HEAD.finditer(strip_comment(line)):
                for label, segment in (("partition", match.group(1)), ("service", match.group(2))):
                    if re.search(r"[*?]", INTERPOLATION.sub("", segment)):
                        found.append(Finding("arn-segments", path, number, f"the {label} segment of an ARN must not contain * or ?: {match.group(0)[1:]}"))
    return found
SYFT_PIN = "scripts/build/syft-pin.json"
ROUTE_KEY = re.compile(r'"((?:GET|POST|PUT|PATCH|DELETE) /v1/[^"]*)"')


def check_build_pins(files: Files) -> List[Finding]:
    """The Syft layer pin is complete and nothing under scripts/build/ says "latest" (scan-backend SB-SBOM-3)."""
    found: List[Finding] = []
    pin_text = files.get(SYFT_PIN)
    if pin_text is None:
        if any(path.startswith("scripts/build/") for path in files):
            return [Finding("build-pins", SYFT_PIN, 1, "the Syft pin file is missing")]
        return []
    try:
        pin = json.loads(pin_text)
    except ValueError:
        return [Finding("build-pins", SYFT_PIN, 1, "the Syft pin file is not JSON")]
    if not isinstance(pin, dict) or not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", str(pin.get("version", ""))):
        found.append(Finding("build-pins", SYFT_PIN, 1, "version must be an exact x.y.z"))
    if not str(pin.get("url", "")).startswith("https://github.com/anchore/syft/releases/download/v"):
        found.append(Finding("build-pins", SYFT_PIN, 1, "url must be a pinned anchore/syft release download"))
    if not re.fullmatch(r"[0-9a-f]{64}", str(pin.get("sha256", ""))):
        found.append(Finding("build-pins", SYFT_PIN, 1, "sha256 must be 64 hex characters"))
    for path, text in sorted(files.items()):
        if path.startswith("scripts/build/") and not path.startswith("scripts/build/tests/"):
            for number, line in enumerate(text.splitlines(), 1):
                if re.search(r"\blatest\b", line, re.IGNORECASE):
                    found.append(Finding("build-pins", path, number, '"latest" is not allowed in a build script'))
    return found


def _route_keys(text: str) -> set:
    return set(ROUTE_KEY.findall(text))


def check_api_routes(files: Files) -> List[Finding]:
    """The route keys of backend/api/routes.py equal those of the api Terraform module (SB-API-7)."""
    code = files.get("backend/api/routes.py")
    module = files.get("infra/modules/api/variables.tf")
    if code is None or module is None:
        return []  # the spec has not reached these files yet
    in_code, in_module = _route_keys(code), _route_keys(module)
    if in_code == in_module:
        return []
    differ = ", ".join(sorted(in_code ^ in_module))
    return [Finding("api-routes", "infra/modules/api/variables.tf", 1, f"route keys differ from backend/api/routes.py: {differ}")]


CHECKS: Dict[str, Callable[[Files], List[Finding]]] = {
    "account-ids": check_account_ids,
    "tracked-files": check_tracked_files,
    "workflow-triggers": check_workflow_triggers,
    "action-pins": check_action_pins,
    "module-policies": check_module_policies,
    "arn-segments": check_arn_segments,
    "build-pins": check_build_pins,
    "api-routes": check_api_routes,
}


def run(root: Path, names: Sequence[str]) -> List[Finding]:
    files = load_files(root)
    findings: List[Finding] = []
    for name in names:
        findings.extend(CHECKS[name](files))
    return findings


def main(argv: Optional[Sequence[str]] = None, root: Optional[Path] = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    names = args or ["all"]
    if names == ["all"]:
        names = list(CHECKS)
    unknown = [n for n in names if n not in CHECKS]
    if unknown:
        sys.stderr.write(f"unknown check: {', '.join(unknown)}; choose from {', '.join(CHECKS)} or all\n")
        return 2
    try:
        repo = root if root is not None else repository_root(Path(__file__).resolve().parent)
        findings = run(repo, names)
    except RuntimeError as error:
        sys.stderr.write(f"{error}\n")
        return 2
    for finding in findings:
        sys.stderr.write(finding.render() + "\n")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
