"""Static import closure of a first-party module (mortality-model-v2, design 4.2).

``closure("core.scoring", backend_dir)`` lists every file executed when the module is
imported: the module, the modules it imports under ``core.*`` (transitively), and the
``__init__.py`` of every parent package. Standard library and third-party imports are not
followed. Anything that would make the static answer differ from the real one raises
``ManifestError``: star imports, ``importlib``, ``__import__``, ``exec``, ``eval``,
``compile``, and a first-party import that does not resolve to a file under ``root``.

Pure Python with file reads only. ``root`` is passed in; nothing reads the current directory.
"""

from __future__ import annotations

import ast
from pathlib import Path

FIRST_PARTY_ROOT = "core"
DYNAMIC_NAMES = frozenset({"__import__", "exec", "eval", "compile"})
DYNAMIC_MODULE = "importlib"


class ManifestError(Exception):
    """The import closure cannot be determined statically."""


def _module_file(module: str, root: Path) -> Path | None:
    """File that importing ``module`` executes, or None if it does not resolve."""
    base = root.joinpath(*module.split("."))
    plain = base.with_suffix(".py")
    if plain.is_file():
        return plain
    init = base / "__init__.py"
    if init.is_file():
        return init
    return None


def _parents(module: str) -> list[str]:
    parts = module.split(".")
    return [".".join(parts[:i]) for i in range(1, len(parts))]


def _is_first_party(module: str) -> bool:
    return module == FIRST_PARTY_ROOT or module.startswith(FIRST_PARTY_ROOT + ".")


def _check_dynamic(tree: ast.AST, rel: str) -> None:
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] == DYNAMIC_MODULE:
                    raise ManifestError(f"{rel}: imports {DYNAMIC_MODULE}")
        elif isinstance(node, ast.ImportFrom):
            if not node.level and (node.module or "").split(".")[0] == DYNAMIC_MODULE:
                raise ManifestError(f"{rel}: imports {DYNAMIC_MODULE}")
            if any(alias.name == "*" for alias in node.names):
                raise ManifestError(f"{rel}: star import")
        elif isinstance(node, ast.Name) and node.id in DYNAMIC_NAMES:
            raise ManifestError(f"{rel}: uses {node.id}")


def _imported_modules(
    tree: ast.AST, module: str, is_package: bool, rel: str, root: Path
) -> set[str]:
    """First-party modules named by the imports of ``module`` (absolute dotted names)."""
    package = module.split(".") if is_package else module.split(".")[:-1]
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(a.name for a in node.names if _is_first_party(a.name))
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                keep = len(package) - (node.level - 1)
                if keep < 1:
                    raise ManifestError(f"{rel}: relative import beyond the top package")
                base = package[:keep]
                target = ".".join([*base, *(node.module.split(".") if node.module else [])])
            else:
                target = node.module or ""
            if not _is_first_party(target):
                continue
            found.add(target)
            for alias in node.names:
                # ``from pkg import name`` imports a submodule when such a file exists.
                if _module_file(f"{target}.{alias.name}", root) is not None:
                    found.add(f"{target}.{alias.name}")
    return found


def labelling_section(text: str, number: int) -> str:
    """Text of ``LABELLING.md`` from the ``## <number>.`` heading to the next ``## `` heading.

    The heading line is included and the next heading is not. Line endings are normalised
    to LF. Raises ``ManifestError`` when the section is missing.
    """
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    prefix = f"## {number}."
    start = next((i for i, line in enumerate(lines) if line.startswith(prefix)), None)
    if start is None:
        raise ManifestError(f"LABELLING.md: no section {number}")
    end = next(
        (i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")),
        len(lines),
    )
    return "\n".join(lines[start:end])


def closure(entry_module: str, root: Path) -> tuple[Path, ...]:
    """Files executed by importing ``entry_module``, sorted by path relative to ``root``."""
    if not _is_first_party(entry_module):
        raise ManifestError(f"{entry_module}: not a first-party ({FIRST_PARTY_ROOT}.*) module")

    files: dict[str, Path] = {}
    seen: set[str] = set()
    pending = [entry_module]
    while pending:
        module = pending.pop()
        if module in seen:
            continue
        seen.add(module)
        for parent in _parents(module):
            pending.append(parent)
        path = _module_file(module, root)
        if path is None:
            raise ManifestError(f"{module}: does not resolve to a file under {root}")
        rel = path.relative_to(root).as_posix()
        files[rel] = path
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=rel)
        except (SyntaxError, UnicodeDecodeError) as exc:
            raise ManifestError(f"{rel}: cannot parse ({exc})") from exc
        _check_dynamic(tree, rel)
        pending.extend(_imported_modules(tree, module, path.name == "__init__.py", rel, root))
    return tuple(files[rel] for rel in sorted(files))
