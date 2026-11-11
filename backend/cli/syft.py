"""Running Syft (CLI-SYFT-1…4, CLI-SEC-4, CLI-ENV-6; design §5.4).

This is the only module that imports ``subprocess``. Syft is started with an argument
list (``shell=False``), no stdin, a timeout and the cleared environment the caller built.
Nothing is installed, downloaded or updated. Syft's stderr is never read into a message.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from collections.abc import Mapping, Sequence
from types import MappingProxyType
from typing import Any, Final

from cli.errors import CliError
from cli.model import ServiceDir
from cli.sbom import MAX_SBOM_BYTES
from cli.text import sanitise

SYFT_VERSION: Final = "1.56.0"
"""The one Syft release this CLI accepts (ADR 0001, `docs/SPIKES.md`)."""

SYFT_FIXED_ENV: Final[Mapping[str, str]] = MappingProxyType(
    {
        # Never look for a newer Syft (CLI-ENV-6).
        "SYFT_CHECK_FOR_APP_UPDATE": "false",
        # Syft drops the `dev: true` packages of a package-lock.json unless told otherwise
        # (docs/SPIKES.md, Q7). Without them the dev dependencies never reach the graph (CLI-DEV-1).
        "SYFT_JAVASCRIPT_INCLUDE_DEV_DEPENDENCIES": "true",
    }
)
"""The only ``SYFT_*`` variables Syft is started with. ``syft.py`` sets them itself."""

VERSION_TIMEOUT_SECONDS: Final = 10.0
_VERSION_WORD: Final = re.compile(r"[0-9A-Za-z.+-]{1,40}")
_SHOWN_PATH_CHARS: Final = 100
_INSTALL_HINT: Final = (
    f"install Syft v{SYFT_VERSION} from https://github.com/anchore/syft/releases/tag/"
    f"v{SYFT_VERSION} and pass --syft PATH, or use --sbom FILE to skip Syft"
)


def syft_environment(base: Mapping[str, str]) -> dict[str, str]:
    """``base`` without any ``SYFT_*`` variable, plus ``SYFT_FIXED_ENV`` (CLI-DEV-1).

    The caller's mapping cannot leave the fixed values out or override them, and no other
    ``SYFT_*`` setting can reach Syft.
    """
    env = {name: value for name, value in base.items() if not name.startswith("SYFT_")}
    env.update(SYFT_FIXED_ENV)
    return env


def _label(service: ServiceDir) -> str:
    return f"'{sanitise(service.path)[:_SHOWN_PATH_CHARS]}'"


def locate_syft(configured: str | None) -> str:
    """Return ``--syft`` as given, or the ``syft`` found on ``PATH`` (CLI-SEC-4, CLI-SYFT-4)."""
    if configured is not None:
        return configured
    found = shutil.which("syft")
    if found is None:
        raise CliError(f"Syft was not found on PATH; {_INSTALL_HINT}")
    return found


def _found_version(line: str) -> str:
    """The version word of ``syft <version>``, only if it is a short plain token."""
    parts = line.split()
    if len(parts) == 2 and parts[0] == "syft" and _VERSION_WORD.fullmatch(parts[1]):
        return f" (found {parts[1]})"
    return ""


def check_version(exe: str, syft_env: Mapping[str, str]) -> str:
    """Require ``syft --version`` to print ``syft 1.56.0``; return the version (CLI-SYFT-1)."""
    try:
        proc = subprocess.run(
            [exe, "--version"],
            shell=False,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            timeout=VERSION_TIMEOUT_SECONDS,
            check=False,
            env=syft_environment(syft_env),
        )
    except subprocess.TimeoutExpired:
        raise CliError("Syft did not answer `--version` in time") from None
    except (OSError, ValueError):
        raise CliError(f"could not run the Syft executable; {_INSTALL_HINT}") from None
    if proc.returncode != 0:
        raise CliError(f"`syft --version` failed; {_INSTALL_HINT}")
    line = proc.stdout.decode("utf-8", errors="replace").strip()
    if line == f"syft {SYFT_VERSION}":
        return SYFT_VERSION
    raise CliError(
        f"unsupported Syft version{_found_version(line)}; this release needs exactly "
        f"{SYFT_VERSION}; {_INSTALL_HINT}"
    )


def is_under(child: str, parent: str) -> bool:
    """True if service path ``child`` is a proper descendant of service path ``parent``."""
    if child == parent:
        return False
    return parent == "." or child.startswith(parent + "/")


def nested_relative_to(service: ServiceDir, others: Sequence[str]) -> tuple[str, ...]:
    """Paths in ``others`` below ``service``, relative to it, sorted and unique (D4)."""
    relative = {
        path if service.path == "." else path[len(service.path) + 1 :]
        for path in others
        if is_under(path, service.path)
    }
    return tuple(sorted(relative))


def run_syft(
    exe: str,
    service: ServiceDir,
    others: Sequence[str],
    timeout: float,
    syft_env: Mapping[str, str],
) -> dict[str, Any]:
    """Run Syft on one service directory and return its CycloneDX document (CLI-SYFT-2/3).

    ``others`` holds the paths of the project's services; those below ``service`` are
    excluded so their packages are not counted twice. Every failure is a ``CliError``
    with a fixed message that names the service (D6: a failed service is fatal).
    """
    label = _label(service)
    argv = [exe, f"dir:{service.directory}", "-q", "-o", "cyclonedx-json"]
    for relative in nested_relative_to(service, others):
        argv += ["--exclude", f"./{relative}/**"]
    try:
        proc = subprocess.run(
            argv,
            shell=False,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            timeout=timeout,
            check=False,
            env=syft_environment(syft_env),
        )
    except subprocess.TimeoutExpired:
        raise CliError(f"Syft timed out for service {label}; raise --syft-timeout") from None
    except (OSError, ValueError):
        raise CliError(f"could not run Syft for service {label}") from None
    if proc.returncode != 0:
        raise CliError(f"Syft failed for service {label}")
    if len(proc.stdout) > MAX_SBOM_BYTES:
        raise CliError(f"Syft produced more than 32 MiB of output for service {label}")
    try:
        document = json.loads(proc.stdout)
    except (ValueError, RecursionError):
        raise CliError(f"Syft did not produce valid JSON for service {label}") from None
    if not isinstance(document, dict):
        raise CliError(f"Syft did not produce a JSON object for service {label}")
    return document
