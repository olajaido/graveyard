"""Requirements-file tests (KPW-TEST-11; KPW-REQ-1…7, KPW-SEC-7)."""

from __future__ import annotations

import io
import os
from pathlib import Path
from typing import Any

import pytest

from cli import requirements_file as rf
from cli.requirements_file import (
    MAX_REQUIREMENTS_BYTES,
    RequirementLoad,
    base_directory,
    load_requirements,
)
from core.install import Pinned, RequirementRef, Target, parse_install


def _write(path: Path, text: str | bytes) -> Path:
    if isinstance(text, bytes):
        path.write_bytes(text)
    else:
        path.write_text(text, encoding="utf-8")
    return path


def _load(path_text: str, base: Path) -> RequirementLoad:
    return load_requirements(RequirementRef(path_text), base)


def _failed(load: RequirementLoad, reason: str) -> None:
    assert load.reason == reason
    assert load.targets == ()


def test_valid_file(tmp_path: Path) -> None:
    _write(tmp_path / "requirements.txt", "requests==2.31.0\nFlask_Login==0.6.3\n")
    load = _load("requirements.txt", tmp_path)
    assert load.reason == "ok"
    assert load.not_checked == 0
    assert load.name == "requirements.txt"
    assert load.targets == (
        Target("pypi", "requests", Pinned("2.31.0")),
        Target("pypi", "flask-login", Pinned("0.6.3")),
    )


def test_relative_path_uses_payload_cwd(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    _write(project / "req.txt", "attrs==23.1.0\n")
    base = base_directory(str(project))
    assert base == project
    assert _load("req.txt", base).targets == (Target("pypi", "attrs", Pinned("23.1.0")),)


def test_base_directory_fallbacks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    for bad in (None, "", "relative/dir", str(tmp_path / "missing"), "bad\x00path"):
        assert base_directory(bad) == Path.cwd()
    file_path = _write(tmp_path / "f.txt", "x")
    assert base_directory(str(file_path)) == Path.cwd()


def test_absolute_inside_and_outside(tmp_path: Path) -> None:
    base = tmp_path / "base"
    base.mkdir()
    inside = _write(base / "in.txt", "attrs==23.1.0\n")
    outside = _write(tmp_path / "out.txt", "attrs==23.1.0\n")
    assert _load(str(inside), base).reason == "ok"
    _failed(_load(str(outside), base), "outside")


def test_dotdot_escape(tmp_path: Path) -> None:
    base = tmp_path / "base"
    base.mkdir()
    _write(tmp_path / "secret.txt", "attrs==23.1.0\n")
    _failed(_load("../secret.txt", base), "outside")


def test_escaping_symlink(tmp_path: Path) -> None:
    base = tmp_path / "base"
    base.mkdir()
    target = _write(tmp_path / "secret.txt", "attrs==23.1.0\n")
    (base / "link.txt").symlink_to(target)
    _failed(_load("link.txt", base), "outside")


def test_symlink_inside_is_followed(tmp_path: Path) -> None:
    real = _write(tmp_path / "real.txt", "attrs==23.1.0\n")
    (tmp_path / "link.txt").symlink_to(real)
    assert _load("link.txt", tmp_path).reason == "ok"


def test_symlink_loop_is_unreadable(tmp_path: Path) -> None:
    (tmp_path / "a").symlink_to(tmp_path / "b")
    (tmp_path / "b").symlink_to(tmp_path / "a")
    _failed(_load("a", tmp_path), "unreadable")


def test_missing_file(tmp_path: Path) -> None:
    _failed(_load("nope.txt", tmp_path), "missing")


def test_directory(tmp_path: Path) -> None:
    (tmp_path / "dir").mkdir()
    _failed(_load("dir", tmp_path), "not-file")


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="needs os.mkfifo")
def test_fifo_is_never_opened(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    os.mkfifo(tmp_path / "pipe")
    opened: list[object] = []
    real_open = Path.open

    def spy(self: Path, *args: Any, **kwargs: Any) -> Any:
        opened.append(self)
        return real_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", spy)
    _failed(_load("pipe", tmp_path), "not-file")  # would hang if opened
    assert opened == []


def test_oversized_file_is_not_read(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    with (tmp_path / "big.txt").open("wb") as handle:
        handle.truncate(MAX_REQUIREMENTS_BYTES + 1)  # sparse
    opened: list[object] = []
    real_open = Path.open

    def spy(self: Path, *args: Any, **kwargs: Any) -> Any:
        opened.append(self)
        return real_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", spy)
    _failed(_load("big.txt", tmp_path), "too-large")
    assert opened == []


def test_file_at_the_cap_is_accepted(tmp_path: Path) -> None:
    line = b"attrs==23.1.0\n"
    body = line + b"#" * (MAX_REQUIREMENTS_BYTES - len(line))
    assert len(body) == MAX_REQUIREMENTS_BYTES
    _write(tmp_path / "cap.txt", body)
    assert _load("cap.txt", tmp_path).reason == "ok"


def test_file_that_grew_reads_one_byte_more_than_the_cap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write(tmp_path / "grow.txt", "attrs==23.1.0\n")  # small on disk: passes the stat check
    requested: list[int] = []

    class Recorder(io.BytesIO):
        def read(self, size: int | None = -1) -> bytes:
            requested.append(-1 if size is None else size)
            return super().read(size)

    def fake_open(self: Path, *args: Any, **kwargs: Any) -> io.BytesIO:
        return Recorder(b"x" * (MAX_REQUIREMENTS_BYTES + 5))

    monkeypatch.setattr(Path, "open", fake_open)
    _failed(_load("grow.txt", tmp_path), "too-large")
    assert requested == [MAX_REQUIREMENTS_BYTES + 1]


@pytest.mark.parametrize(
    "path_text",
    [
        "~/req.txt",
        "~",
        "$HOME/req.txt",
        "req-*.txt",
        "req?.txt",
        "req[1].txt",
        "https://x/req.txt",
        "file:///etc/passwd",
        "a\x00b.txt",
        "",
    ],
)
def test_unsafe_paths_are_not_opened(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, path_text: str
) -> None:
    _write(tmp_path / "req-1.txt", "attrs==23.1.0\n")
    opened: list[object] = []
    monkeypatch.setattr(Path, "open", lambda self, *a, **k: opened.append(self))
    _failed(_load(path_text, tmp_path), "unsafe-path")
    assert opened == []


def test_nested_includes_are_counted_not_followed(tmp_path: Path) -> None:
    _write(tmp_path / "other.txt", "attrs==23.1.0\n")
    _write(
        tmp_path / "req.txt",
        "-r other.txt\n  -c constraints.txt\n--requirement other.txt\n"
        "--constraint c.txt\nrequests==2.31.0\n",
    )
    load = _load("req.txt", tmp_path)
    assert load.reason == "ok"
    assert load.not_checked == 4
    assert load.targets == (Target("pypi", "requests", Pinned("2.31.0")),)


def test_url_path_and_unpinned_lines_are_counted(tmp_path: Path) -> None:
    _write(
        tmp_path / "req.txt",
        "requests==2.31.0\n"
        "https://example.com/pkg-1.0.tar.gz\n"
        "./local/pkg\n"
        "flask>=2.0\n"
        "django\n"
        "git+https://example.com/x.git#egg=x\n",
    )
    load = _load("req.txt", tmp_path)
    assert load.reason == "ok"
    assert load.targets == (Target("pypi", "requests", Pinned("2.31.0")),)
    assert load.not_checked == 5


def test_binary_junk_does_not_raise(tmp_path: Path) -> None:
    _write(tmp_path / "junk.bin", bytes(range(256)) * 40)
    load = _load("junk.bin", tmp_path)
    assert load.reason == "ok"
    assert load.targets == ()
    assert load.not_checked >= 0


def test_env_style_file_leaks_nothing(tmp_path: Path) -> None:
    lines = [
        "AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
        "DATABASE_URL=postgres://user:hunter2pass@db.internal/app",
        "API_TOKEN=ghp_abcdefghijklmnopqrstuvwxyz0123456789",
        "-----BEGIN PRIVATE KEY-----",
        "MIIEvQIBADANBgkqhkiG9w0BAQEFAASC",
    ]
    _write(tmp_path / ".env", "\n".join(lines) + "\n")
    load = _load(".env", tmp_path)
    assert load.targets == ()
    rendered = repr(load) + str(load) + load.name + repr(load.targets)
    for line in lines:
        assert line not in rendered
        for piece in (line.split("=", 1)[-1], line.split("@")[-1]):
            if len(piece) > 8:
                assert piece not in rendered
    assert load.name == ".env"


def test_more_than_five_files_are_cut_by_the_parser() -> None:
    command = "pip install " + " ".join(f"-r r{i}.txt" for i in range(8))
    assert len(parse_install(command).requirement_files) == 5


def test_duplicate_targets_across_files_load_identically(tmp_path: Path) -> None:
    _write(tmp_path / "a.txt", "requests==2.31.0\nattrs==23.1.0\n")
    _write(tmp_path / "b.txt", "attrs==23.1.0\n")
    first, second = _load("a.txt", tmp_path), _load("b.txt", tmp_path)
    assert second.targets[0] == first.targets[1]  # equal values: the caller de-duplicates


def test_twenty_five_pinned_lines_are_all_returned(tmp_path: Path) -> None:
    _write(tmp_path / "req.txt", "".join(f"pkg-{i}==1.0.{i}\n" for i in range(25)))
    load = _load("req.txt", tmp_path)
    assert len(load.targets) == 25  # the 20-target cap belongs to the caller (KPW-REQ-5)
    assert all(isinstance(t.spec, Pinned) for t in load.targets)


def test_targets_keep_file_order(tmp_path: Path) -> None:
    names = [f"pkg-{c}" for c in "zyxwvutsrqponmlkjihgfedcb"]  # 25, descending
    _write(tmp_path / "req.txt", "".join(f"{n}==1.0.0\n" for n in names))
    load = _load("req.txt", tmp_path)
    assert [t.name for t in load.targets] == names


def test_name_is_sanitised_and_cut(tmp_path: Path) -> None:
    long_name = "a" * 60 + ".txt"
    _write(tmp_path / long_name, "attrs==23.1.0\n")
    assert len(_load(long_name, tmp_path).name) == rf.MAX_NAME_CHARS
    assert "\x1b" not in _load("x\x1b[31m.txt", tmp_path).name
    assert _load("sub/dir/../req.txt", tmp_path).name == "req.txt"


def test_never_raises_on_unexpected_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*args: object, **kwargs: object) -> object:
        raise RuntimeError("boom")

    monkeypatch.setattr(rf, "parse_requirements_txt", boom)
    _write(tmp_path / "req.txt", "attrs==23.1.0\n")
    _failed(_load("req.txt", tmp_path), "unreadable")


def test_order_recovery_is_capped_but_every_pin_is_kept(tmp_path: Path) -> None:
    count = rf.MAX_ORDER_LINES + 50
    lines = [f"p{i:06d}==1\n" for i in reversed(range(count))]  # file order is descending
    (tmp_path / "r.txt").write_text("".join(lines))
    result = load_requirements(RequirementRef("r.txt"), tmp_path)
    assert result.reason == "ok"
    names = [t.name for t in result.targets]
    assert len(names) == count
    head, tail = names[: rf.MAX_ORDER_LINES], names[rf.MAX_ORDER_LINES :]
    assert head == sorted(head, reverse=True)  # file order inside the cap
    assert tail == sorted(tail)  # sorted after it
