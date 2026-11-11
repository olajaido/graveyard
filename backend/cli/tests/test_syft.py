"""Tests for ``cli.syft`` with the stub Syft executable (T5.3; CLI-SYFT-1…4, CLI-TEST-5).

The stub is a real script run through ``subprocess``, so the argv, the environment and the
timeout are the real thing. Nothing here touches the network.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from cli import syft
from cli.errors import CliError
from cli.model import ServiceDir
from cli.tests.support import STUB_STDERR_SENTINEL, StubMode, make_stub_syft

PROJECT = Path(__file__).resolve().parent / "fixtures" / "anchors-project"
SAFE_ENV = {"PATH": "/usr/bin:/bin", "HOME": "/nonexistent", "SYFT_CHECK_FOR_APP_UPDATE": "false"}
TIMEOUT = 20.0


def _web() -> ServiceDir:
    return ServiceDir(path="web", directory=PROJECT / "web", lockfiles=("package-lock.json",))


def _api() -> ServiceDir:
    return ServiceDir(path="api", directory=PROJECT / "api", lockfiles=("uv.lock",))


def _argv(stub_calls: list[dict[str, object]], index: int = 0) -> list[str]:
    argv = stub_calls[index]["argv"]
    assert isinstance(argv, list)
    return [str(a) for a in argv]


# ------------------------------------------------------------------------ constants / locate


def test_the_pin_is_1_56_0() -> None:
    assert syft.SYFT_VERSION == "1.56.0"


def test_locate_returns_the_configured_path_without_consulting_which(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom(name: str) -> str:
        raise AssertionError("shutil.which must not be consulted when --syft is given")

    monkeypatch.setattr("shutil.which", boom)
    assert syft.locate_syft("/some/where/syft") == "/some/where/syft"


def test_locate_uses_which_otherwise(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("shutil.which", lambda name: f"/opt/{name}")
    assert syft.locate_syft(None) == "/opt/syft"


def test_locate_reports_how_to_install_when_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("shutil.which", lambda name: None)
    with pytest.raises(CliError) as caught:
        syft.locate_syft(None)
    message = caught.value.message
    assert "1.56.0" in message
    assert "--sbom" in message


# ------------------------------------------------------------------------------ check_version


def test_version_accepted(tmp_path: Path) -> None:
    stub = make_stub_syft(tmp_path)
    assert syft.check_version(str(stub.path), SAFE_ENV) == "1.56.0"


def test_other_version_rejected_and_shown(tmp_path: Path) -> None:
    stub = make_stub_syft(tmp_path, version="1.55.0")
    with pytest.raises(CliError) as caught:
        syft.check_version(str(stub.path), SAFE_ENV)
    assert "1.55.0" in caught.value.message
    assert "1.56.0" in caught.value.message


def test_malformed_version_line_is_not_echoed(tmp_path: Path) -> None:
    stub = make_stub_syft(tmp_path, version="bad version\x1b[31m")
    with pytest.raises(CliError) as caught:
        syft.check_version(str(stub.path), SAFE_ENV)
    message = caught.value.message
    assert "\x1b" not in message
    assert "bad" not in message


def test_version_check_with_missing_executable(tmp_path: Path) -> None:
    with pytest.raises(CliError):
        syft.check_version(str(tmp_path / "nope"), SAFE_ENV)


def test_version_check_with_a_directory_as_executable(tmp_path: Path) -> None:
    with pytest.raises(CliError):
        syft.check_version(str(tmp_path), SAFE_ENV)


def test_version_check_with_a_nul_byte_in_the_path() -> None:
    with pytest.raises(CliError):
        syft.check_version("/bin/sy\x00ft", SAFE_ENV)


def test_version_check_nonzero_exit(tmp_path: Path) -> None:
    script = tmp_path / "syft"
    script.write_text("#!/bin/sh\nexit 3\n", encoding="utf-8")
    script.chmod(0o755)
    with pytest.raises(CliError):
        syft.check_version(str(script), SAFE_ENV)


# -------------------------------------------------------------------------------- run_syft


def test_argv_without_nested_services(tmp_path: Path) -> None:
    stub = make_stub_syft(tmp_path)
    bom = syft.run_syft(str(stub.path), _web(), ["api", "web"], TIMEOUT, SAFE_ENV)
    assert bom["specVersion"] == "1.7"
    assert _argv(stub.calls()) == [f"dir:{PROJECT / 'web'}", "-q", "-o", "cyclonedx-json"]


def test_exclude_for_a_nested_service(tmp_path: Path) -> None:
    stub = make_stub_syft(tmp_path)
    parent = ServiceDir(path="web", directory=PROJECT / "web", lockfiles=("package-lock.json",))
    syft.run_syft(str(stub.path), parent, ["web", "web/sub", "api"], TIMEOUT, SAFE_ENV)
    assert _argv(stub.calls())[4:] == ["--exclude", "./sub/**"]


def test_root_service_excludes_every_other_service_in_sorted_order(tmp_path: Path) -> None:
    stub = make_stub_syft(tmp_path)
    root = ServiceDir(path=".", directory=PROJECT / "web", lockfiles=("package-lock.json",))
    syft.run_syft(str(stub.path), root, [".", "web", "api"], TIMEOUT, SAFE_ENV)
    assert _argv(stub.calls())[4:] == ["--exclude", "./api/**", "--exclude", "./web/**"]


def test_is_under_and_nested_relative_to() -> None:
    assert syft.is_under("a/b", "a")
    assert syft.is_under("a", ".")
    assert not syft.is_under(".", ".")
    assert not syft.is_under("ab", "a")
    assert not syft.is_under("a", "a")
    service = ServiceDir(path="a", directory=Path("/x/a"), lockfiles=())
    assert syft.nested_relative_to(service, ["a", "a/b", "a/b/c", "ab", "z"]) == ("b", "b/c")


def test_a_directory_name_with_shell_metacharacters_is_one_argv_element(tmp_path: Path) -> None:
    sboms = tmp_path / "sboms"
    sboms.mkdir()
    (sboms / "a b;c.cdx.json").write_text("{}", encoding="utf-8")
    directory = tmp_path / "a b;c"
    directory.mkdir()
    stub = make_stub_syft(tmp_path, sbom_dir=sboms)
    service = ServiceDir(path="a b;c", directory=directory, lockfiles=())
    assert syft.run_syft(str(stub.path), service, [], TIMEOUT, SAFE_ENV) == {}
    assert _argv(stub.calls())[0] == f"dir:{directory}"


def test_the_environment_is_cleared_and_the_token_is_not_passed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "decoy-token-value")
    stub = make_stub_syft(tmp_path)
    syft.run_syft(str(stub.path), _api(), [], TIMEOUT, SAFE_ENV)
    keys = stub.calls()[0]["env_keys"]
    assert isinstance(keys, list)
    assert "GITHUB_TOKEN" not in keys
    # The interpreter (and the OS) may add variables of their own. The baseline is what a
    # bare interpreter reports when started with the same environment.
    baseline = subprocess.run(
        [sys.executable, "-c", "import json, os; print(json.dumps(sorted(os.environ)))"],
        env=SAFE_ENV,
        capture_output=True,
        text=True,
        check=True,
    )
    assert keys == json.loads(baseline.stdout)
    assert "SYFT_CHECK_FOR_APP_UPDATE" in keys


def test_failure_message_does_not_contain_stderr(tmp_path: Path) -> None:
    stub = make_stub_syft(tmp_path, mode="fail")
    with pytest.raises(CliError) as caught:
        syft.run_syft(str(stub.path), _web(), [], TIMEOUT, SAFE_ENV)
    assert STUB_STDERR_SENTINEL not in caught.value.message
    assert "web" in caught.value.message


def test_timeout_is_an_error(tmp_path: Path) -> None:
    stub = make_stub_syft(tmp_path, mode="sleep")
    with pytest.raises(CliError) as caught:
        syft.run_syft(str(stub.path), _web(), [], 0.5, SAFE_ENV)
    assert "timed out" in caught.value.message


@pytest.mark.parametrize("mode", ["garbage", "array"])
def test_output_that_is_not_a_json_object(tmp_path: Path, mode: StubMode) -> None:
    stub = make_stub_syft(tmp_path, mode=mode)
    with pytest.raises(CliError):
        syft.run_syft(str(stub.path), _web(), [], TIMEOUT, SAFE_ENV)


def test_output_above_the_cap(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(syft, "MAX_SBOM_BYTES", 1024)
    stub = make_stub_syft(tmp_path, mode="big")
    with pytest.raises(CliError):
        syft.run_syft(str(stub.path), _web(), [], TIMEOUT, SAFE_ENV)


def test_missing_executable_and_directory_as_executable(tmp_path: Path) -> None:
    for exe in (str(tmp_path / "nope"), str(tmp_path)):
        with pytest.raises(CliError):
            syft.run_syft(exe, _web(), [], TIMEOUT, SAFE_ENV)


def test_a_hostile_service_name_is_sanitised_in_the_message(tmp_path: Path) -> None:
    stub = make_stub_syft(tmp_path, mode="fail")
    service = ServiceDir(path="evil\x1b[31m", directory=tmp_path, lockfiles=())
    with pytest.raises(CliError) as caught:
        syft.run_syft(str(stub.path), service, [], TIMEOUT, SAFE_ENV)
    assert "\x1b" not in caught.value.message


def test_stub_log_is_json_per_line(tmp_path: Path) -> None:
    stub = make_stub_syft(tmp_path)
    syft.run_syft(str(stub.path), _web(), [], TIMEOUT, SAFE_ENV)
    for line in stub.log_path.read_text(encoding="utf-8").splitlines():
        assert isinstance(json.loads(line), dict)
