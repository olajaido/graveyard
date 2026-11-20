import pytest

from core.scan.ids import SCAN_ID_RE, is_scan_id, new_scan_id


def test_format_and_length() -> None:
    sid = new_scan_id(1_763_000_000_000, bytes(range(10)), bytes(range(8)))
    assert len(sid) == 43
    assert SCAN_ID_RE.fullmatch(sid)
    assert sid.endswith("-0001020304050607")


def test_sorts_by_time() -> None:
    a = new_scan_id(1_000, b"\xff" * 10, b"\xff" * 8)
    b = new_scan_id(1_001, b"\x00" * 10, b"\x00" * 8)
    assert a[:26] < b[:26]


def test_rejects_bad_inputs() -> None:
    with pytest.raises(ValueError):
        new_scan_id(-1, bytes(10), bytes(8))
    with pytest.raises(ValueError):
        new_scan_id(1, bytes(9), bytes(8))


@pytest.mark.parametrize(
    "text",
    [
        "",
        "x",
        "01HZZZZZZZZZZZZZZZZZZZZZZZ-0123456789abcde",
        "01hzzzzzzzzzzzzzzzzzzzzzzz-0123456789abcdef",
        "../etc/passwd",
        None,
        5,
    ],
)
def test_is_scan_id_rejects(text: object) -> None:
    assert not is_scan_id(text)


def test_is_scan_id_accepts() -> None:
    assert is_scan_id(new_scan_id(5, bytes(10), bytes(8)))
