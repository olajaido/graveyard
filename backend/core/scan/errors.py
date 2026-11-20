"""Error codes of the scan backend (SB-ERR-1).

Each code has one exception class with the same name: Step Functions reports the class
name as the error name, so the state machine can map it to a fixed code without any text.
"""

from __future__ import annotations

from typing import Final

TITLES: Final[dict[str, str]] = {
    "INVALID_INPUT": "The request is not valid.",
    "REPO_NOT_FOUND": "The repository was not found or is not public. You can upload an SBOM.",
    "NO_MANIFESTS": "No supported lockfile was found. You can upload an SBOM instead.",
    "TOO_LARGE": "The repository has more lockfile content than a scan accepts.",
    "TREE_TRUNCATED": "The repository is too large to list completely.",
    "TOO_MANY_PACKAGES": "The repository has more packages than a scan accepts.",
    "GITHUB_RATE_LIMITED": "GitHub is limiting requests right now. Try again later.",
    "GITHUB_AUTH_FAILED": "Graveyard could not authenticate to GitHub.",
    "SBOM_FAILED": "The SBOM could not be generated.",
    "SBOM_INVALID": "The generated SBOM is not usable.",
    "TIMEOUT": "The scan took too long and was stopped.",
    "INTERNAL": "The scan failed because of an internal error.",
}
CODES: Final[tuple[str, ...]] = tuple(TITLES)


class ScanError(Exception):
    """Base class. ``code`` equals the class name."""

    code = "INTERNAL"

    def __init__(self) -> None:
        super().__init__(self.code)


class INVALID_INPUT(ScanError):  # noqa: N801
    code = "INVALID_INPUT"


class REPO_NOT_FOUND(ScanError):  # noqa: N801
    code = "REPO_NOT_FOUND"


class NO_MANIFESTS(ScanError):  # noqa: N801
    code = "NO_MANIFESTS"


class TOO_LARGE(ScanError):  # noqa: N801
    code = "TOO_LARGE"


class TREE_TRUNCATED(ScanError):  # noqa: N801
    code = "TREE_TRUNCATED"


class TOO_MANY_PACKAGES(ScanError):  # noqa: N801
    code = "TOO_MANY_PACKAGES"


class GITHUB_RATE_LIMITED(ScanError):  # noqa: N801
    code = "GITHUB_RATE_LIMITED"


class GITHUB_AUTH_FAILED(ScanError):  # noqa: N801
    code = "GITHUB_AUTH_FAILED"


class SBOM_FAILED(ScanError):  # noqa: N801
    code = "SBOM_FAILED"


class SBOM_INVALID(ScanError):  # noqa: N801
    code = "SBOM_INVALID"


class TIMEOUT(ScanError):  # noqa: N801
    code = "TIMEOUT"


class INTERNAL(ScanError):  # noqa: N801
    code = "INTERNAL"


def code_for(error_name: object) -> str:
    """The fixed code for an error name from the state machine; anything else is INTERNAL."""
    return error_name if isinstance(error_name, str) and error_name in TITLES else "INTERNAL"


def title_for(code: object) -> str:
    return TITLES[code_for(code)]
