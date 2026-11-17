"""Offline tests for scripts/heldout_pin.py (mortality-model-v2 T5.4; MV2-POP-2, MV2-POP-3).

All HTTP goes through ``httpx.MockTransport``; no test touches the network.
"""

from __future__ import annotations

import base64
import hashlib
import importlib.util
import io
import json
import sys
import tarfile
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "heldout_pin.py"
SHA = "a" * 40
TOP_JS = "export const top = [\n  'left-pad',\n  'ms',\n  '@scope/pkg',\n]\n"


@pytest.fixture(scope="module")
def pin() -> Iterator[Any]:
    spec = importlib.util.spec_from_file_location("heldout_pin", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["heldout_pin"] = module
    spec.loader.exec_module(module)
    try:
        yield module
    finally:
        sys.modules.pop("heldout_pin", None)


def make_tarball(top_js: str = TOP_JS, extra: dict[str, bytes] | None = None) -> bytes:
    buf = io.BytesIO()
    members = {"package/package.json": b"{}", "package/lib/top.js": top_js.encode()}
    members.update(extra or {})
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name, content in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(content)
            tar.addfile(info, io.BytesIO(content))
    return buf.getvalue()


def integrity_of(data: bytes) -> str:
    return "sha512-" + base64.b64encode(hashlib.sha512(data).digest()).decode()


def hugovk_bytes(count: int = 6) -> bytes:
    rows = [{"download_count": 1000 - i, "project": f"Pkg_{i}"} for i in range(count)]
    return json.dumps({"last_update": "2026-11-01 00:00:00", "rows": rows}).encode()


def transport(
    tarball: bytes,
    *,
    integrity: str | None = None,
    seen: list[str] | None = None,
    overrides: dict[str, Callable[[], httpx.Response]] | None = None,
) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if seen is not None:
            seen.append(url)
        for prefix, make in (overrides or {}).items():
            if url.startswith(prefix):
                return make()
        if url.startswith("https://api.github.com/repos/hugovk/top-pypi-packages/commits"):
            return httpx.Response(200, json=[{"sha": SHA}])
        if url == f"https://raw.githubusercontent.com/hugovk/top-pypi-packages/{SHA}/{_F}":
            return httpx.Response(200, content=hugovk_bytes())
        if url == "https://registry.npmjs.org/npm-high-impact/latest":
            dist = {
                "integrity": integrity or integrity_of(tarball),
                "tarball": "https://registry.npmjs.org/npm-high-impact/-/npm-high-impact-1.0.0.tgz",
            }
            return httpx.Response(200, json={"version": "1.0.0", "dist": dist})
        if url.endswith("npm-high-impact-1.0.0.tgz"):
            return httpx.Response(200, content=tarball)
        return httpx.Response(404)

    return httpx.MockTransport(handler)


_F = "top-pypi-packages.min.json"


@pytest.fixture(autouse=True)
def small_top_n(pin: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pin, "PYPI_TOP_N", 5)


def run(pin: Any, out: Path, tr: httpx.MockTransport) -> int:
    return int(pin.main(["--out-dir", str(out)], transport=tr))


def test_success_writes_files_and_verify_passes(pin: Any, tmp_path: Path) -> None:
    out = tmp_path / "snap"
    assert run(pin, out, transport(make_tarball())) == 0
    assert sorted(p.name for p in out.iterdir()) == [
        "npm-high-impact.json",
        "pins.json",
        "pypi-top-5000.json",
    ]
    pins = json.loads((out / "pins.json").read_text())
    assert pins["sources"]["pypi-top-5000"]["commit_sha"] == SHA
    assert pins["sources"]["pypi-top-5000"]["row_count"] == 5
    assert pins["sources"]["npm-high-impact"]["row_count"] == 3
    assert json.loads((out / "npm-high-impact.json").read_text()) == [
        "left-pad",
        "ms",
        "@scope/pkg",
    ]
    assert pin.main(["--verify", "--out-dir", str(out)]) == 0


def test_verify_detects_tampering(pin: Any, tmp_path: Path) -> None:
    out = tmp_path / "snap"
    assert run(pin, out, transport(make_tarball())) == 0
    (out / "npm-high-impact.json").write_text('["evil"]\n')
    assert pin.main(["--verify", "--out-dir", str(out)]) == 1


def test_integrity_mismatch_aborts_and_writes_nothing(pin: Any, tmp_path: Path) -> None:
    out = tmp_path / "snap"
    bad = integrity_of(b"something else")
    assert run(pin, out, transport(make_tarball(), integrity=bad)) == 1
    assert not out.exists()


def test_wrong_member_shape_aborts_and_writes_nothing(pin: Any, tmp_path: Path) -> None:
    out = tmp_path / "snap"
    tarball = make_tarball("module.exports = ['ms'];\n")
    assert run(pin, out, transport(tarball)) == 1
    assert not out.exists()


def test_extra_members_are_never_read(pin: Any, tmp_path: Path, monkeypatch: Any) -> None:
    tarball = make_tarball(extra={"package/other.bin": b"x" * 100, "package/zzz.js": b"1"})
    read: list[str] = []
    original = tarfile.TarFile.extractfile

    def spy(self: tarfile.TarFile, member: Any) -> Any:
        read.append(member.name if isinstance(member, tarfile.TarInfo) else str(member))
        return original(self, member)

    monkeypatch.setattr(tarfile.TarFile, "extractfile", spy)
    assert pin.read_member(tarball, "package/lib/top.js") == TOP_JS.encode()
    assert read == ["package/lib/top.js"]


def test_missing_member_raises(pin: Any) -> None:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        info = tarfile.TarInfo("package/other.js")
        tar.addfile(info, io.BytesIO(b""))
    with pytest.raises(pin.PinError):
        pin.read_member(buf.getvalue(), "package/lib/top.js")


def test_redirect_is_not_followed(pin: Any, tmp_path: Path) -> None:
    out = tmp_path / "snap"
    seen: list[str] = []
    redirect = {
        "https://raw.githubusercontent.com": lambda: httpx.Response(
            302, headers={"Location": "https://evil.example/x"}
        )
    }
    assert run(pin, out, transport(make_tarball(), seen=seen, overrides=redirect)) == 1
    assert not any("evil.example" in u for u in seen)
    assert not out.exists()


def test_off_allowlist_host_refused_without_request(pin: Any) -> None:
    seen: list[str] = []
    client = httpx.Client(transport=transport(b"", seen=seen))
    with pytest.raises(pin.PinError):
        pin.get_bytes(client, "https://evil.example/a", 100)
    with pytest.raises(pin.PinError):
        pin.get_bytes(client, "http://registry.npmjs.org/a", 100)
    assert seen == []


def test_size_cap_aborts(pin: Any) -> None:
    client = httpx.Client(transport=transport(make_tarball()))
    with pytest.raises(pin.PinError):
        pin.get_bytes(
            client, "https://registry.npmjs.org/npm-high-impact/-/npm-high-impact-1.0.0.tgz", 1
        )


def test_failure_leaves_no_files_and_existing_pins_not_overwritten(
    pin: Any, tmp_path: Path
) -> None:
    out = tmp_path / "snap"
    out.mkdir()
    (out / "pins.json").write_text("{}")
    assert run(pin, out, transport(make_tarball())) == 1
    assert (out / "pins.json").read_text() == "{}"
    assert [p.name for p in out.iterdir()] == ["pins.json"]
