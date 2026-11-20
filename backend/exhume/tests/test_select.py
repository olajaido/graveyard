import pytest

from core.scan.errors import NO_MANIFESTS, TOO_LARGE
from exhume.select import Limits, select_services

LIMITS = Limits(max_services=3, max_manifest_bytes=1000, max_file_bytes=500)
SHA = "a" * 40


def blob(path: str, size: int = 10, mode: str = "100644") -> dict[str, object]:
    return {"path": path, "type": "blob", "mode": mode, "sha": SHA, "size": size}


def test_groups_by_directory_and_sorts() -> None:
    plans = select_services(
        [
            blob("services/api/uv.lock"),
            blob("package-lock.json"),
            blob("requirements-dev.txt"),
            blob("requirements.txt"),
            blob("README.md"),
            {"path": "services", "type": "tree", "mode": "040000", "sha": SHA},
        ],
        LIMITS,
    )
    assert [p.path for p in plans] == [".", "services/api"]
    assert [f.name for f in plans[0].files] == [
        "package-lock.json",
        "requirements-dev.txt",
        "requirements.txt",
    ]


def test_skips_node_modules_symlinks_and_submodules() -> None:
    with pytest.raises(NO_MANIFESTS):
        select_services(
            [
                blob("node_modules/x/package-lock.json"),
                blob("a/venv/requirements.txt"),
                blob("link/package-lock.json", mode="120000"),
                {"path": "sub", "type": "commit", "mode": "160000", "sha": SHA},
            ],
            LIMITS,
        )


def test_no_manifests() -> None:
    with pytest.raises(NO_MANIFESTS):
        select_services([blob("pnpm-lock.yaml"), blob("src/a.py")], LIMITS)


def test_limits() -> None:
    with pytest.raises(TOO_LARGE):
        select_services([blob("package-lock.json", size=501)], LIMITS)
    with pytest.raises(TOO_LARGE):
        select_services([blob(f"d{i}/uv.lock", size=300) for i in range(4)], LIMITS)
    with pytest.raises(TOO_LARGE):
        select_services([blob(f"d{i}/uv.lock", size=10) for i in range(4)], LIMITS)
