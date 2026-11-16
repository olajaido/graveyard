"""Static import closure of a first-party module (mortality-model-v2, design 4.2).

``closure("core.scoring", backend_dir)`` lists every file executed when the module is
imported: the module, the modules it imports under ``core.*`` (transitively), and the
``__init__.py`` of every parent package. Standard library and third-party imports are not
followed. Anything that would make the static answer differ from the real one raises
``ManifestError``: star imports, ``importlib``, ``__import__``, ``exec``, ``eval``,
``compile``, and a first-party import that does not resolve to a file under ``root``.

``build_manifest``, ``verify_manifest`` and ``closure_sha256`` hash a file set and check it
again (design 4.3); the harness set of design 11.8 and ``manifest --harness`` sit on them.

Pure Python with file reads only. ``root`` is passed in; nothing reads the current directory.
"""

from __future__ import annotations

import ast
import hashlib
import json
from collections.abc import Callable, Iterable, Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final, TextIO

if TYPE_CHECKING:
    from eval.models import ModelSpec

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


def _in_package(module: str, top: str) -> bool:
    return module == top or module.startswith(top + ".")


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
    tree: ast.AST, module: str, is_package: bool, rel: str, root: Path, top: str
) -> set[str]:
    """Modules under ``top`` named by the imports of ``module`` (absolute dotted names)."""
    package = module.split(".") if is_package else module.split(".")[:-1]
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(a.name for a in node.names if _in_package(a.name, top))
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                keep = len(package) - (node.level - 1)
                if keep < 1:
                    raise ManifestError(f"{rel}: relative import beyond the top package")
                base = package[:keep]
                target = ".".join([*base, *(node.module.split(".") if node.module else [])])
            else:
                target = node.module or ""
            if not _in_package(target, top):
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


def _walk(
    entries: Sequence[str], root: Path, top: str, skip: Callable[[str], bool]
) -> dict[str, Path]:
    """Files executed by importing ``entries``; modules for which ``skip`` is true are left out."""
    files: dict[str, Path] = {}
    seen: set[str] = set()
    pending = list(entries)
    while pending:
        module = pending.pop()
        if module in seen or skip(module):
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
        pending.extend(_imported_modules(tree, module, path.name == "__init__.py", rel, root, top))
    return files


def closure(entry_module: str, root: Path) -> tuple[Path, ...]:
    """Files executed by importing ``entry_module``, sorted by path relative to ``root``."""
    if not _in_package(entry_module, FIRST_PARTY_ROOT):
        raise ManifestError(f"{entry_module}: not a first-party ({FIRST_PARTY_ROOT}.*) module")
    files = _walk([entry_module], root, FIRST_PARTY_ROOT, lambda _module: False)
    return tuple(files[rel] for rel in sorted(files))


# --- Generic manifests (design 4.3) -------------------------------------------------------

EXIT_OK: Final = 0
EXIT_USAGE: Final = 2
EXIT_INVALID: Final = 3
HARNESS_SCHEMA: Final = "graveyard.harness-manifest"
HARNESS_RECORD: Final = ("heldout", "FROZEN_HARNESS.json")
_USAGE: Final = "usage: python -m eval manifest --harness [--write|--check]\n"


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def closure_sha256(files: Mapping[str, str], weights: Mapping[str, str] | None = None) -> str:
    """SHA-256 of the sorted ``path<TAB>sha256`` lines of ``files``, then those of ``weights``."""
    lines = [f"{path}\t{files[path]}\n" for path in sorted(files)]
    extra = weights or {}
    lines += [f"{path}\t{extra[path]}\n" for path in sorted(extra)]
    return hashlib.sha256("".join(lines).encode("utf-8")).hexdigest()


def _hashes(root: Path, paths: Iterable[Path]) -> dict[str, str]:
    return {p.relative_to(root).as_posix(): _sha256_file(p) for p in paths}


def build_manifest(
    root: Path,
    files: Iterable[Path],
    *,
    header: Mapping[str, Any],
    weights: Iterable[Path] | None = None,
) -> dict[str, Any]:
    """Manifest of ``files`` (raw-byte SHA-256, paths relative to ``root``).

    ``header`` supplies the fixed fields (schema, entry, roots and so on). ``weights`` adds a
    ``weights`` object when given. ``closure_sha256`` covers the files, then the weights.
    """
    manifest: dict[str, Any] = dict(header)
    file_hashes = _hashes(root, files)
    manifest["files"] = file_hashes
    weight_hashes: dict[str, str] | None = None
    if weights is not None:
        weight_hashes = _hashes(root, weights)
        manifest["weights"] = weight_hashes
    manifest["closure_sha256"] = closure_sha256(file_hashes, weight_hashes)
    return manifest


def _hash_map(manifest: Mapping[str, Any], key: str) -> dict[str, str] | None:
    value = manifest.get(key)
    if isinstance(value, dict) and all(
        isinstance(k, str) and isinstance(v, str) for k, v in value.items()
    ):
        return dict(value)
    return None


def _compare(
    recorded: Mapping[str, str], root: Path, current: Iterable[Path], label: str
) -> list[str]:
    """Problems between a recorded path-to-hash map and the files that exist now."""
    problems: list[str] = []
    now = {p.relative_to(root).as_posix(): p for p in current}
    problems += [f"{label} added: {rel}" for rel in sorted(set(now) - set(recorded))]
    problems += [f"{label} removed: {rel}" for rel in sorted(set(recorded) - set(now))]
    for rel in sorted(set(recorded) & set(now)):
        if _sha256_file(now[rel]) != recorded[rel]:
            problems.append(f"{label} changed: {rel}")
    return problems


def verify_manifest(
    manifest: Mapping[str, Any],
    root: Path,
    files: Iterable[Path],
    weights: Iterable[Path] | None = None,
) -> list[str]:
    """Problems found (empty when the manifest matches); never raises on a bad manifest.

    ``files`` and ``weights`` are the sets recomputed from the working tree. Reports a changed
    file, a file the manifest lacks or lists without it existing, and a ``closure_sha256``
    that does not match the manifest's own ``files`` and ``weights``.
    """
    recorded = _hash_map(manifest, "files")
    if recorded is None:
        return ["manifest: 'files' is missing or malformed"]
    problems = _compare(recorded, root, files, "file")
    recorded_weights: dict[str, str] | None = None
    if weights is not None:
        recorded_weights = _hash_map(manifest, "weights")
        if recorded_weights is None:
            problems.append("manifest: 'weights' is missing or malformed")
        else:
            problems += _compare(recorded_weights, root, weights, "weights")
    if manifest.get("closure_sha256") != closure_sha256(recorded, recorded_weights):
        problems.append("closure_sha256 does not match the manifest's own files")
    return problems


# --- Frozen harness (design 11.8) ---------------------------------------------------------

HARNESS_ROOTS: Final = (
    "eval.gate",
    "eval.metrics",
    "eval.outcome",
    "eval.fixture",
    "eval.run",
    "eval.heldout.verdict",
    "eval.heldout.strata",
    "eval.heldout.datasets",
)
#: Report modules: imported by the frozen set (``run.py`` imports ``report.py``) but not frozen.
REPORT_MODULES: Final = ("eval.report", "eval.heldout.report")
#: Outside the frozen set. ``eval.tests`` also excludes everything below it.
HARNESS_EXCLUDED: Final = (
    *REPORT_MODULES,
    "eval.compare",
    "eval.analysis",
    "eval.probe",
    "eval.merge",
    "eval.__main__",
    "eval.tests",
)
#: Amendable file outside ``eval`` that the harness imports (``run.py``, design 11.8).
HARNESS_EXTRA_FILES: Final = ("cli/gate.py",)
HARNESS_PACKAGE: Final = "eval"
BACKEND_DIR: Final = Path(__file__).resolve().parents[1]


def _excluded(module: str) -> bool:
    return any(_in_package(module, name) for name in HARNESS_EXCLUDED)


def _module_path(module: str) -> str:
    return "backend/" + module.replace(".", "/") + ".py"


def harness_files(backend_dir: Path, roots: Sequence[str] = HARNESS_ROOTS) -> tuple[Path, ...]:
    """Frozen harness files under ``backend_dir``, sorted by relative path.

    The closure of ``roots`` within ``eval``, without the excluded modules, plus
    ``cli/gate.py``. Raises ``ManifestError`` when a root or an imported module is missing.
    """
    files = _walk(roots, backend_dir, HARNESS_PACKAGE, _excluded)
    for extra in HARNESS_EXTRA_FILES:
        path = backend_dir / extra
        if not path.is_file():
            raise ManifestError(f"{extra}: does not exist under {backend_dir}")
        files[extra] = path
    return tuple(files[rel] for rel in sorted(files))


def harness_boundary_violations(
    backend_dir: Path, roots: Sequence[str] = HARNESS_ROOTS
) -> list[str]:
    """Imports from a frozen module to an excluded module other than the two report modules."""
    problems: list[str] = []
    for path in harness_files(backend_dir, roots):
        rel = path.relative_to(backend_dir).as_posix()
        if not rel.startswith("eval/"):
            continue
        is_package = path.name == "__init__.py"
        parts = Path(rel).with_suffix("").parts
        module = ".".join(parts[:-1] if is_package else parts)
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=rel)
        for target in sorted(
            _imported_modules(tree, module, is_package, rel, backend_dir, HARNESS_PACKAGE)
        ):
            if _excluded(target) and not any(_in_package(target, r) for r in REPORT_MODULES):
                problems.append(f"{rel} imports {target}, which is outside the frozen set")
    return problems


def harness_header() -> dict[str, Any]:
    """Fixed fields of the harness manifest."""
    return {
        "schema": HARNESS_SCHEMA,
        "schema_version": 1,
        "roots": [_module_path(m) for m in HARNESS_ROOTS],
        "exclusions": list(HARNESS_EXCLUDED),
        "extra_files": [f"backend/{p}" for p in HARNESS_EXTRA_FILES],
    }


def build_harness_manifest(backend_dir: Path = BACKEND_DIR) -> dict[str, Any]:
    """Manifest of the frozen harness, paths relative to the parent of ``backend_dir``."""
    return build_manifest(backend_dir.parent, harness_files(backend_dir), header=harness_header())


def verify_harness_manifest(
    manifest: Mapping[str, Any], backend_dir: Path = BACKEND_DIR
) -> list[str]:
    """Problems between ``manifest`` and the working tree (design 11.8)."""
    try:
        files = harness_files(backend_dir)
    except ManifestError as exc:
        return [str(exc)]
    problems = [
        f"{key} differs from the harness definition"
        for key, expected in harness_header().items()
        if manifest.get(key) != expected
    ]
    return problems + verify_manifest(manifest, backend_dir.parent, files)


def dumps_manifest(manifest: Mapping[str, Any]) -> str:
    """Canonical text: sorted keys, two-space indent, LF, trailing newline."""
    return json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def run_manifest(
    argv: Sequence[str],
    *,
    out: TextIO,
    err: TextIO,
    backend_dir: Path = BACKEND_DIR,
    data_dir: Path | None = None,
) -> int:
    """``manifest --harness [--write|--check]``: returns 0, 2 (usage) or 3 (invalid or differs).

    No flag prints the manifest. ``--write`` creates ``<data>/heldout/FROZEN_HARNESS.json`` by
    exclusive create and refuses an existing file. ``--check`` compares the file with the tree.
    """
    args = list(argv)
    if args[:1] == ["--model"]:
        return _run_model_manifest(
            args, out=out, err=err, backend_dir=backend_dir, data_dir=data_dir
        )
    if args not in (["--harness"], ["--harness", "--write"], ["--harness", "--check"]):
        err.write(_USAGE)
        return EXIT_USAGE
    base = data_dir if data_dir is not None else backend_dir.parent / "eval"
    record = base.joinpath(*HARNESS_RECORD)
    if args[1:] == ["--check"]:
        try:
            loaded = json.loads(record.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            err.write(f"eval: cannot read {record.name}: {exc}\n")
            return EXIT_INVALID
        if not isinstance(loaded, dict):
            err.write(f"eval: {record.name} is not a JSON object\n")
            return EXIT_INVALID
        problems = verify_harness_manifest(loaded, backend_dir)
        for problem in problems:
            err.write(f"eval: {problem}\n")
        if problems:
            err.write(f"harness files differ from {record.name}\n")
            return EXIT_INVALID
        out.write(f"{record.name}: matches\n")
        return EXIT_OK
    try:
        text = dumps_manifest(build_harness_manifest(backend_dir))
    except ManifestError as exc:
        err.write(f"eval: {exc}\n")
        return EXIT_INVALID
    if args[1:] == ["--write"]:
        record.parent.mkdir(parents=True, exist_ok=True)
        try:
            with record.open("x", encoding="utf-8", newline="\n") as handle:
                handle.write(text)
        except FileExistsError:
            err.write(f"eval: {record.name} exists; it is never rewritten\n")
            return EXIT_INVALID
        out.write(f"wrote {record.name}\n")
        return EXIT_OK
    out.write(text)
    return EXIT_OK


# --- Model manifest (design 4.3) ----------------------------------------------------------

MODEL_SCHEMA: Final = "graveyard.model-manifest"
#: Manifest entry module per model version; ``v1`` has no manifest (its lock is V1_LOCK.json).
MODEL_ENTRIES: Final = {"v2": "core.scoring.versions"}
#: Weights file per model version, relative to the backend directory.
MODEL_WEIGHTS: Final = {"v2": "core/scoring/weights.v2.yaml"}
MODEL_MANIFEST_FILES: Final = {"v2": "FROZEN_MODEL.v2.json"}
MODEL_DIGEST_FILES: Final = {"v2": "FROZEN_WEIGHTS.v2.sha256"}
MODEL_MESSAGE: Final = "model files differ from {name}; a change is a documented v3"
LOCKFILE = "uv.lock"
_MODEL_USAGE: Final = "usage: python -m eval manifest --model v2 [--write|--check]\n"


def model_header(version: str) -> dict[str, Any]:
    """Fixed fields of the model manifest."""
    return {
        "schema": MODEL_SCHEMA,
        "schema_version": 1,
        "model_version": version,
        "entry": MODEL_ENTRIES[version],
    }


def _lockfile_sha256(backend_dir: Path) -> str | None:
    lock = backend_dir / LOCKFILE
    return _sha256_file(lock) if lock.is_file() else None


def build_model_manifest(version: str, backend_dir: Path = BACKEND_DIR) -> dict[str, Any]:
    """Manifest of the closure of the model entry plus its weights file (design 4.3).

    Paths are relative to the parent of ``backend_dir``. ``lockfile_sha256`` is informational
    and outside ``closure_sha256``.
    """
    files = closure(MODEL_ENTRIES[version], backend_dir)
    manifest = build_manifest(
        backend_dir.parent,
        files,
        header=model_header(version),
        weights=[backend_dir / MODEL_WEIGHTS[version]],
    )
    manifest["lockfile_sha256"] = _lockfile_sha256(backend_dir)
    return manifest


def verify_model_manifest(
    version: str, manifest: Mapping[str, Any], backend_dir: Path = BACKEND_DIR
) -> list[str]:
    """Problems between ``manifest`` and the working tree; never raises on a bad manifest."""
    try:
        files = closure(MODEL_ENTRIES[version], backend_dir)
    except ManifestError as exc:
        return [str(exc)]
    problems = [
        f"{key} differs from the model definition"
        for key, expected in model_header(version).items()
        if manifest.get(key) != expected
    ]
    weights = [backend_dir / MODEL_WEIGHTS[version]]
    return problems + verify_manifest(manifest, backend_dir.parent, files, weights)


def lockfile_warning(manifest: Mapping[str, Any], backend_dir: Path = BACKEND_DIR) -> str | None:
    """Warning (not an error) when ``uv.lock`` differs from the recorded hash."""
    recorded = manifest.get("lockfile_sha256")
    if recorded is None or recorded == _lockfile_sha256(backend_dir):
        return None
    return f"warning: backend/{LOCKFILE} differs from the manifest (informational)"


def _digest_problems(version: str, digest_path: Path, backend_dir: Path) -> list[str]:
    try:
        actual = _sha256_file(backend_dir / MODEL_WEIGHTS[version])
        expected = digest_path.read_text(encoding="utf-8").split()[0]
    except (OSError, UnicodeDecodeError, IndexError):
        return [f"cannot read the weights digest {digest_path.name}"]
    if actual != expected:
        return [f"weights differ from {digest_path.name}"]
    return []


def verify(
    spec: ModelSpec, data_dir: Path, backend_dir: Path = BACKEND_DIR
) -> tuple[list[str], list[str]]:
    """Run-time check of a frozen model (design 4.3): ``(problems, warnings)``.

    Empty problems for a spec without a manifest (v1). Otherwise the manifest and the weights
    digest file under ``data_dir`` are compared with the working tree.
    """
    if spec.manifest_file is None:
        return [], []
    record = data_dir / spec.manifest_file
    try:
        loaded = json.loads(record.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return [f"cannot read {record.name}: {exc}"], []
    if not isinstance(loaded, dict):
        return [f"{record.name} is not a JSON object"], []
    problems = verify_model_manifest(spec.version, loaded, backend_dir)
    problems += _digest_problems(spec.version, data_dir / spec.digest_file, backend_dir)
    warning = lockfile_warning(loaded, backend_dir)
    return problems, [warning] if warning else []


def _run_model_manifest(
    args: list[str], *, out: TextIO, err: TextIO, backend_dir: Path, data_dir: Path | None
) -> int:
    """``manifest --model v2 [--write|--check]``: returns 0, 2 (usage) or 3."""
    if (
        len(args) < 2
        or args[1] not in MODEL_ENTRIES
        or args[2:] not in ([], ["--write"], ["--check"])
    ):
        err.write(_MODEL_USAGE)
        return EXIT_USAGE
    version, mode = args[1], (args[2] if len(args) > 2 else "")
    base = data_dir if data_dir is not None else backend_dir.parent / "eval"
    record = base / MODEL_MANIFEST_FILES[version]
    digest = base / MODEL_DIGEST_FILES[version]
    if mode == "--check":
        try:
            loaded = json.loads(record.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            err.write(f"eval: cannot read {record.name}: {exc}\n")
            return EXIT_INVALID
        if not isinstance(loaded, dict):
            err.write(f"eval: {record.name} is not a JSON object\n")
            return EXIT_INVALID
        problems = verify_model_manifest(version, loaded, backend_dir)
        problems += _digest_problems(version, digest, backend_dir)
        for problem in problems:
            err.write(f"eval: {problem}\n")
        warning = lockfile_warning(loaded, backend_dir)
        if warning:
            err.write(f"eval: {warning}\n")
        if problems:
            err.write(MODEL_MESSAGE.format(name=record.name) + "\n")
            return EXIT_INVALID
        out.write(f"{record.name}: matches\n")
        return EXIT_OK
    try:
        text = dumps_manifest(build_model_manifest(version, backend_dir))
        weights_sha = _sha256_file(backend_dir / MODEL_WEIGHTS[version])
    except (ManifestError, OSError) as exc:
        err.write(f"eval: {exc}\n")
        return EXIT_INVALID
    if mode == "--write":
        existing = [p.name for p in (record, digest) if p.exists()]
        if existing:
            err.write(f"eval: {', '.join(existing)} exists; it is never rewritten\n")
            return EXIT_INVALID
        record.parent.mkdir(parents=True, exist_ok=True)
        try:
            with record.open("x", encoding="utf-8", newline="\n") as handle:
                handle.write(text)
            with digest.open("x", encoding="utf-8", newline="\n") as handle:
                handle.write(weights_sha + "\n")
        except FileExistsError:
            err.write(f"eval: {record.name} or {digest.name} exists; it is never rewritten\n")
            return EXIT_INVALID
        out.write(f"wrote {record.name} and {digest.name}\n")
        return EXIT_OK
    out.write(text)
    return EXIT_OK
