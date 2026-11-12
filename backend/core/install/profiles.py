"""Option tables per package manager (design 4.4 of the ``kiro-power`` spec). Data only.

Each table maps an option spelling to a ``Kind``. An option in no table makes the
whole segment unchecked (KPW-PARSE-6): the tables are the first version and an
entry that is missing fails open, never to a wrong package.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum


class Kind(Enum):
    """What an option does to the argument scan."""

    VALUE = "value"  # takes a value (next token, ``=value`` or attached short form)
    BOOL = "bool"  # no value
    REGISTRY = "registry"  # custom registry or index: the segment is unchecked (KPW-PARSE-8)
    REQFILE = "reqfile"  # ``-r FILE``: becomes a RequirementRef (pip, uv)
    CONSTRAINT = "constraint"  # ``-c FILE``: consume the value, count one skip
    EDITABLE = "editable"  # ``-e PATH``: consume the value, count one skip


type Table = Mapping[str, Kind]


@dataclass(frozen=True)
class Profile:
    """The tables for one program and install verb."""

    name: str
    verbs: frozenset[str]
    global_options: Table  # options that may stand before the verb
    verb_options: Table  # options after the verb (includes the global ones)
    value_prefixes: tuple[str, ...] = ()  # ``--config.x=y`` style value options


def table(
    *,
    value: tuple[str, ...] = (),
    flag: tuple[str, ...] = (),
    registry: tuple[str, ...] = (),
    reqfile: tuple[str, ...] = (),
    constraint: tuple[str, ...] = (),
    editable: tuple[str, ...] = (),
) -> dict[str, Kind]:
    """Build a table from groups of spellings."""
    out: dict[str, Kind] = {}
    for names, kind in (
        (value, Kind.VALUE),
        (flag, Kind.BOOL),
        (registry, Kind.REGISTRY),
        (reqfile, Kind.REQFILE),
        (constraint, Kind.CONSTRAINT),
        (editable, Kind.EDITABLE),
    ):
        for n in names:
            out[n] = kind
    return out


# --- npm -----------------------------------------------------------------------------

NPM_GLOBAL = table(
    value=("--prefix", "-C", "--userconfig", "--cache", "--loglevel", "-w", "--workspace"),
    flag=(
        "-g",
        "--global",
        "-ws",
        "--workspaces",
        "--include-workspace-root",
        "--silent",
        "-s",
        "-q",
        "--quiet",
        "-d",
        "-dd",
        "-ddd",
        "--verbose",
        "--json",
        "--no-color",
    ),
    registry=("--registry",),
)
NPM_VERB = {
    **NPM_GLOBAL,
    **table(
        value=("--tag", "--omit", "--include", "--before", "--install-strategy", "--otp"),
        flag=(
            "-S",
            "--save",
            "-D",
            "--save-dev",
            "-O",
            "--save-optional",
            "-P",
            "--save-prod",
            "-E",
            "--save-exact",
            "--no-save",
            "-f",
            "--force",
            "--legacy-peer-deps",
            "--strict-peer-deps",
            "--no-audit",
            "--audit",
            "--no-fund",
            "--fund",
            "--ignore-scripts",
            "--prefer-offline",
            "--prefer-online",
            "--offline",
            "--dry-run",
            "--no-package-lock",
            "--package-lock-only",
            "--foreground-scripts",
            "--install-links",
            "--global-style",
            "--engine-strict",
            "--no-progress",
            "--progress",
        ),
    ),
}

# --- pnpm ----------------------------------------------------------------------------

PNPM_GLOBAL = table(
    value=("-C", "--dir", "-F", "--filter", "--filter-prod", "--loglevel", "--workspace-dir"),
    flag=("-w", "--workspace-root", "-r", "--recursive", "-g", "--global", "--silent"),
    registry=("--registry",),
)
PNPM_VERB = {
    **PNPM_GLOBAL,
    **table(
        value=("--store-dir", "--virtual-store-dir", "--reporter"),
        flag=(
            "-D",
            "--save-dev",
            "-O",
            "--save-optional",
            "-P",
            "--save-prod",
            "-E",
            "--save-exact",
            "--save-peer",
            "--ignore-scripts",
            "--no-optional",
            "--offline",
            "--prefer-offline",
            "--frozen-lockfile",
            "--ignore-workspace-root-check",
            "--workspace",
        ),
    ),
}

# --- yarn ----------------------------------------------------------------------------

YARN_GLOBAL = table(
    value=("--cwd", "--mode"),
    flag=("--silent", "--verbose", "--json", "--non-interactive"),
    registry=("--registry",),
)
YARN_VERB = {
    **YARN_GLOBAL,
    **table(
        flag=(
            "-D",
            "--dev",
            "-P",
            "--peer",
            "-O",
            "--optional",
            "-E",
            "--exact",
            "-T",
            "--tilde",
            "-C",
            "--caret",
            "--audit",
            "--ignore-scripts",
            "--prefer-offline",
            "--offline",
            "--frozen-lockfile",
            "--ignore-workspace-root-check",
            "-W",
            "-i",
            "--interactive",
        ),
    ),
}

# --- pip (also ``python -m pip``) ----------------------------------------------------

PIP_GLOBAL = table(
    value=(
        "--python",
        "--log",
        "--proxy",
        "--retries",
        "--timeout",
        "--cache-dir",
        "--exists-action",
        "--cert",
        "--client-cert",
    ),
    flag=(
        "-q",
        "--quiet",
        "-v",
        "--verbose",
        "--no-cache-dir",
        "--disable-pip-version-check",
        "--no-color",
        "-s",
        "--isolated",
        "--require-virtualenv",
        "--no-input",
    ),
)
PIP_INSTALL_ONLY = table(
    value=(
        "--target",
        "-t",
        "--prefix",
        "--root",
        "--src",
        "--platform",
        "--python-version",
        "--implementation",
        "--abi",
        "--upgrade-strategy",
        "--only-binary",
        "--no-binary",
        "--progress-bar",
        "--report",
        "--config-settings",
        "-C",
        "--root-user-action",
    ),
    flag=(
        "-U",
        "--upgrade",
        "--user",
        "--no-deps",
        "--pre",
        "--force-reinstall",
        "-I",
        "--ignore-installed",
        "--no-build-isolation",
        "--break-system-packages",
        "--dry-run",
        "--no-warn-script-location",
        "--require-hashes",
        "--prefer-binary",
        "--no-compile",
        "--compile",
        "--use-pep517",
        "--no-use-pep517",
        "--no-clean",
    ),
    registry=("-i", "--index-url", "--extra-index-url", "-f", "--find-links", "--no-index"),
    reqfile=("-r", "--requirement"),
    constraint=("-c", "--constraint"),
    editable=("-e", "--editable"),
)
PIP_VERB = {**PIP_GLOBAL, **PIP_INSTALL_ONLY}

# --- uv ------------------------------------------------------------------------------

UV_GLOBAL = table(
    value=("--directory", "--project", "--python", "-p", "--config-file", "--cache-dir"),
    flag=(
        "-q",
        "--quiet",
        "-v",
        "--verbose",
        "--no-progress",
        "--offline",
        "--frozen",
        "--locked",
        "--no-sync",
        "--no-cache",
        "-n",
        "--native-tls",
    ),
)
UV_ADD_VERB = {
    **UV_GLOBAL,
    **table(
        value=(
            "--group",
            "--optional",
            "--package",
            "--extra",
            "--rev",
            "--tag",
            "--branch",
            "--marker",
            "-m",
            "--bounds",
            "--index-strategy",
            "--script",
        ),
        flag=(
            "--dev",
            "--raw",
            "--raw-sources",
            "--no-install-project",
            "--no-install-workspace",
            "--upgrade",
            "-U",
        ),
        registry=(
            "--index",
            "--default-index",
            "-i",
            "--index-url",
            "--extra-index-url",
            "-f",
            "--find-links",
        ),
        reqfile=("-r", "--requirements"),
        editable=("-e", "--editable"),
    ),
}
UV_PIP_EXTRA = table(
    value=(
        "--link-mode",
        "--index-strategy",
        "--resolution",
        "--prerelease",
        "--exclude-newer",
    ),
    flag=("--system", "--reinstall", "--compile-bytecode", "--no-build", "--strict", "--refresh"),
)
UV_PIP_VERB = {**UV_GLOBAL, **PIP_INSTALL_ONLY, **UV_PIP_EXTRA}

# --- poetry --------------------------------------------------------------------------

POETRY_GLOBAL = table(
    value=("-C", "--directory", "-P", "--project"),
    flag=(
        "-q",
        "--quiet",
        "-v",
        "-vv",
        "-vvv",
        "--no-interaction",
        "-n",
        "--no-ansi",
        "--ansi",
        "--no-plugins",
        "--no-cache",
    ),
)
POETRY_VERB = {
    **POETRY_GLOBAL,
    **table(
        value=("-G", "--group", "-E", "--extras", "--python", "--platform"),
        flag=("-D", "--dev", "--optional", "--allow-prereleases", "--dry-run", "--lock"),
        registry=("--source",),
        editable=("-e", "--editable"),
    ),
}

# --- profiles ------------------------------------------------------------------------

NPM = Profile("npm", frozenset({"install", "i", "add"}), NPM_GLOBAL, NPM_VERB)
PNPM = Profile(
    "pnpm",
    frozenset({"add", "install", "i"}),
    PNPM_GLOBAL,
    PNPM_VERB,
    value_prefixes=("--config.",),
)
YARN = Profile("yarn", frozenset({"add"}), YARN_GLOBAL, YARN_VERB)
PIP = Profile("pip", frozenset({"install"}), PIP_GLOBAL, PIP_VERB)
UV_ADD = Profile("uv_add", frozenset({"add"}), UV_GLOBAL, UV_ADD_VERB)
UV_PIP = Profile("uv_pip", frozenset({"install"}), UV_GLOBAL, UV_PIP_VERB)
POETRY = Profile("poetry", frozenset({"add"}), POETRY_GLOBAL, POETRY_VERB)

PROFILES: tuple[Profile, ...] = (NPM, PNPM, YARN, PIP, UV_ADD, UV_PIP, POETRY)

NPM_FAMILY = frozenset({"npm", "pnpm", "yarn"})
